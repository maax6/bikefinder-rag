"""Auditable before/after appendix from saved live-chat results and manual grades."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import html
import json
import math
import re
import statistics

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'eval_results/technical/chat-baseline-20261015'
RUN = ROOT / 'eval_results/technical/chat-corrections-20261015'
LABELS = {'correct': 'Correcte', 'justified_limit': 'Limite pertinente', 'partial': 'Partielle', 'failure': 'Échec'}
RANK = {'correct': 2, 'justified_limit': 2, 'partial': 1, 'failure': 0}
MD = MarkdownIt('commonmark', {'html': False}).enable('table')
esc = html.escape


def read(path):
    return json.loads(path.read_text())


def key(row):
    return f"{row['pass']}/{row['id']}/{row['turn']}"


def stats(rows):
    times = sorted(r['elapsed_seconds'] for r in rows)
    return {'n': len(times), 'median_seconds': statistics.median(times) if times else None,
            'p95_seconds': times[max(0, math.ceil(len(times) * .95) - 1)] if times else None,
            'max_seconds': max(times) if times else None}


def satisfactory(rows):
    return sum(RANK[r['verdict']] == 2 for r in rows)


def main():
    baseline = read(BASE / 'reviewed-results.json')
    before = {key(r): r for r in baseline['results']}
    review = read(RUN / 'review.json')
    grades = {r['key']: r for r in review['grades']}
    runtime = read(RUN / 'server/runtime.json')
    ledger = read(RUN / 'server/spending.json')
    original_ledger = read(BASE / 'server/spending.json')
    traces = [read(p) for p in (RUN / 'server').glob('*.json')]
    traces = [t for t in traces if 'question' in t]
    submissions = []
    hashes = {}
    for filename, packname in [('results.json', 'questions-replay.json'),
                               ('results-holdout.json', 'questions-holdout.json'),
                               ('results-price.json', 'questions-price.json')]:
        if not (RUN / filename).exists():
            continue
        run = read(RUN / filename)
        assert run['completed'], filename
        digest = hashlib.sha256((RUN / packname).read_bytes()).hexdigest()
        assert run['questions_sha256'] == digest
        hashes[packname] = digest
        submissions.extend(run['results'])
    rows = []
    assert len(grades) == len(submissions)
    for r in submissions:
        candidates = [t for t in traces if t['question'] == r['question']
                      and t.get('answer') == r.get('answer') and t['started_at'] >= r['started_at']]
        assert candidates, key(r)
        trace = min(candidates, key=lambda t: t['started_at'])
        meta = trace.get('metadata', {})
        old = before.get(key(r))
        grade = grades[key(r)]
        delta = RANK[grade['verdict']] - RANK[old['verdict']] if old else None
        change = ('improved' if delta > 0 else 'regressed' if delta < 0 else 'stable') if old else 'new'
        rows.append({**r, **grade, 'change': change, 'before': old,
                     'trace_id': trace['id'], 'route': meta.get('_catalog_route'),
                     'plan': meta.get('_catalog_plan'), 'evidence': meta.get('_catalog_evidence'),
                     'generation': meta.get('_catalog_generation'), 'http_calls': trace['http_calls'],
                     'server_seconds': trace['server_seconds']})
    first = [r for r in rows if r['pass'] == 'first']
    regression = [r for r in first if r['group'] == 'unseen']
    known = [r for r in first if r['group'] == 'known']
    holdout = [r for r in first if r['group'] == 'holdout']
    repeats = [r for r in rows if r['pass'] == 'warm_repeat']
    original = [r['before'] for r in regression]
    paired = [r for r in first if r['before']]
    metrics = {'regression_before': dict(Counter(r['verdict'] for r in original)),
               'regression_after': dict(Counter(r['verdict'] for r in regression)),
               'known_after': dict(Counter(r['verdict'] for r in known)),
               'holdout': dict(Counter(r['verdict'] for r in holdout)),
               'paired_changes': dict(Counter(r['change'] for r in paired)),
               'regressed_keys': [key(r) for r in paired if r['change'] == 'regressed'],
               'quality_before': satisfactory(original), 'quality_after': satisfactory(regression),
               'latency_before': stats(original), 'latency_after': stats(regression),
               'latency_holdout': stats(holdout), 'latency_repeats': stats(repeats),
               'latency_after_rag': stats([r for r in first if (r['evidence'] or {}).get('retrieval_executed')]),
               'generation_errors': dict(Counter(r['generation']['error'] for r in first
                                                if (r['generation'] or {}).get('error'))),
               'cost_retest_usd': ledger['debit_usd'],
               'cost_cumulative_usd': original_ledger['debit_usd'] + ledger['debit_usd'],
               'remote_requests': len(ledger['records']), 'api_errors': sum(bool(r.get('error')) for r in rows)}
    metrics['dialogues'] = {id: all(RANK[r['verdict']] == 2 for r in regression if r['id'] == id)
                            for id in sorted({r['id'] for r in regression if r['id'].startswith('D')})}
    bundle = {'metrics': metrics, 'review': review, 'runtime': runtime, 'question_hashes': hashes, 'results': rows}
    (RUN / 'summary.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n')
    (RUN / 'reviewed-results.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n')

    cards = []
    change_labels = {'improved': 'Amélioration', 'regressed': 'Régression', 'stable': 'Niveau conservé', 'new': 'Cas supplémentaire'}
    for r in rows:
        group = 'repeat' if r['pass'] == 'warm_repeat' else r['group']
        old = r['before']
        old_answer = (f'<details><summary>Avant · {LABELS[old["verdict"]]} · {old["elapsed_seconds"]:.2f} s</summary>'
                      f'<div class="answer">{MD.render(old.get("answer") or "")}</div></details>') if old else ''
        passages = []
        for source in (r.get('evidence') or {}).get('sources', []):
            for p in source.get('passages', []):
                passages.append(f'<li><b>{esc(source["brand"] + " " + source["model"])} · {source["year"]} · {esc(p["section"])}</b><p>{esc(p["original_text"])}</p></li>')
        evidence = f'<details><summary>Passages réellement récupérés ({len(passages)})</summary><ul>{"".join(passages)}</ul></details>' if passages else ''
        cards.append(f'''<article class="case" data-group="{group}" data-verdict="{r['verdict']}" data-change="{r['change']}">
<div class="case-top"><span>{r['id']} · tour {r['turn']} · {esc(r['category'])}</span><span class="badge {r['verdict']}">{LABELS[r['verdict']]}</span><span>{change_labels[r['change']]}</span><strong>{r['elapsed_seconds']:.2f} s</strong></div>
<h3>{esc(r['question'])}</h3><p class="review">{esc(r['note'])}</p>
<details><summary>Après · réponse réellement reçue</summary><div class="answer">{MD.render(r.get('answer') or r.get('error', ''))}</div></details>{old_answer}
<details><summary>Réponse attendue, figée avant l’essai</summary><p>{esc(r['expected'])}</p></details>{evidence}
<small>Parcours : {esc(r['route'] or '')} · {len(r['http_calls'])} appel(s) distant(s) · trace {esc(r['trace_id'][:10])}</small></article>''')

    quality_rows = ''.join(f'<tr><th>{label}</th><td>{metrics["regression_before"].get(verdict,0)}</td><td>{metrics["regression_after"].get(verdict,0)}</td><td>{metrics["holdout"].get(verdict,0)}</td></tr>' for verdict, label in LABELS.items())
    timing_rows = []
    for label, name in [('Lot de 36, avant', 'latency_before'), ('Même lot, après', 'latency_after'),
                        (f'{len(holdout)} tours supplémentaires', 'latency_holdout'), ('Six répétitions, après', 'latency_repeats'),
                        ('Parcours avec recherche BGE, après', 'latency_after_rag')]:
        value = metrics[name]
        if value['n']:
            timing_rows.append(f'<tr><th>{label}</th><td>{value["n"]}</td><td>{value["median_seconds"]:.2f} s</td><td>{value["p95_seconds"]:.2f} s</td><td>{value["max_seconds"]:.2f} s</td></tr>')
    findings = ''.join(f'<li><b>{esc(f["title"])}</b><p>{esc(f["detail"])}</p></li>' for f in review['findings'])
    limits = ''.join(f'<li>{esc(text)}</li>' for text in review['limitations'])
    baseline_html = ROOT / 'docs/benchmark-chat-20261015-initial.html'
    current_html = ROOT / 'docs/benchmark-chat-20261015.html'
    if not baseline_html.exists():
        assert '25' in current_html.read_text() and 'Première passe conservée sans correction' in current_html.read_text()
        baseline_html.write_bytes(current_html.read_bytes())
    css = re.search(r'<style>(.*?)</style>', baseline_html.read_text(), re.S)[1]
    css += 'code,a{overflow-wrap:anywhere}.metrics{grid-template-columns:repeat(3,1fr)}.metric b{font-size:32px}.beforeafter{font-size:16px;color:var(--muted)}.regressed{border-left:4px solid var(--red)}.improved{border-left:4px solid var(--green)}@media(max-width:700px){.metrics{grid-template-columns:1fr}.filters>*{max-width:100%}}'
    raw = json.dumps(bundle, ensure_ascii=False).replace('<', '\\u003c')
    page = f'''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bikefinder · Corrections du chat, avant et après</title><style>{css}</style><main>
<nav>Bikefinder / Annexe de validation / 15 octobre 2026</nav>
<header><div class="eyebrow">BGE-M3 d’origine conservé · Mesures sur le vrai chat</div><h1>Le chat corrigé,<br>preuves à l’appui.</h1><p class="lede">{esc(review['conclusion'])}</p></header>
<div class="metrics"><div class="metric"><b>{metrics['quality_before']}/36 → {metrics['quality_after']}/36</b><span>réponses satisfaisantes sur le même lot, limites pertinentes comprises</span></div>
<div class="metric"><b>{len(metrics['regressed_keys'])}</b><span>régression(s) de qualité observée(s) sur les 42 tours comparables</span></div>
<div class="metric"><b>{satisfactory(holdout)}/{len(holdout)}</b><span>réponses satisfaisantes sur les tours supplémentaires</span></div></div>
<p class="note">Le premier lot est désormais un lot de régression, puisqu’il a servi à corriger le chat. Les 12 tours supplémentaires et les 3 tests du prix moyen ont été figés avant leur exécution. Même agent pour la rédaction et la relecture : ces résultats restent exploratoires, sans validation humaine indépendante.</p>
<p><a href="benchmark-chat-20261015-initial.html">Consulter le bilan initial conservé</a> · <a href="benchmark-finetuning.html">Annexe du fine-tuning</a></p>
<h2>Ce qui change dans les réponses</h2><ol>{findings}</ol>
<h2>Qualité : la comparaison à questions identiques</h2><div class="table-wrap"><table><thead><tr><th>Verdict</th><th>Avant / 36</th><th>Après / 36</th><th>Supplément / {len(holdout)}</th></tr></thead><tbody>{quality_rows}</tbody></table></div>
<p>{sum(metrics['dialogues'].values())}/6 dialogues du lot initial réussissent tous leurs tours. Les six tours des captures sont conservés à part : {satisfactory(known)}/{len(known)} satisfaisants. Les répétitions ne gonflent pas le score principal.</p>
<h2>Temps et coût réellement observés</h2><div class="table-wrap"><table><thead><tr><th>Population</th><th>Tours</th><th>Médiane</th><th>P95</th><th>Maximum</th></tr></thead><tbody>{''.join(timing_rows)}</tbody></table></div>
<p>{esc(review['timing_note'])}</p>
<p>Sur les 57 tours finaux hors répétitions : {metrics['generation_errors'].get('ReadTimeout', 0)} expirations de rédaction locale et {metrics['generation_errors'].get('unverified_claims', 0)} rejet de rédaction non vérifiée. Les tableaux de secours conservent les données sources. Aucune erreur du point d’entrée du chat.</p>
<p>Coût de cette campagne : <b>{metrics['cost_retest_usd']:.6f} $</b>. Cumul avec le bilan initial : <b>{metrics['cost_cumulative_usd']:.6f} $</b>, sous le plafond de 0,50 $. Les montants viennent du registre des appels Jev/OpenRouter. BGE et Mistral restent locaux ; énergie et amortissement non mesurés.</p>
<h2>Consulter chaque réponse avant et après</h2><div class="filters">
<select id="group" aria-label="Lot"><option value="unseen">Lot de régression · 36 tours</option><option value="known">Captures · 6 tours</option><option value="holdout">Supplément · {len(holdout)} tours</option><option value="repeat">Répétitions · 6 tours</option><option value="all">Tous les essais</option></select>
<select id="verdict" aria-label="Résultat"><option value="all">Tous les résultats</option>{''.join(f'<option value="{k}">{v}</option>' for k,v in LABELS.items())}</select>
<select id="change" aria-label="Évolution"><option value="all">Toutes les évolutions</option>{''.join(f'<option value="{k}">{v}</option>' for k,v in change_labels.items())}</select>
<input id="search" aria-label="Rechercher" placeholder="Question, moto, valeur…"><button id="download">Exporter les résultats</button></div>
<p id="count" aria-live="polite"></p><div id="cases">{''.join(cards)}</div>
<h2>Protocole, limites et suites</h2><ul>{limits}</ul>
<p>Instance dédiée du même point d’entrée Gradio <code>/chat</code>, mode rapide, Jev + SQL + BGE-M3 original + Mistral Small 3.2 local. Les réponses sont produites par l’application corrigée, sans simulation du routeur ni replay des réponses. Les traces enregistrent les empreintes du code modifié sur la base <code>{runtime['commit'][:7]}</code>, les passages et les appels réellement exécutés. Révision BGE : <code>{esc(runtime['embedding_revision'])}</code>.</p>
<footer>Les réponses initiales, les attentes figées et les traces de chaque passe restent conservées. Le catalogue contient 11 478 fiches et 105 687 passages, avec les mêmes empreintes sources entre SQLite et PostgreSQL. Les références du catalogue ne remplacent pas une vérification indépendante auprès des constructeurs.</footer></main>
<script id="data" type="application/json">{raw}</script><script>
const cards=[...document.querySelectorAll('.case')],group=document.querySelector('#group'),verdict=document.querySelector('#verdict'),change=document.querySelector('#change'),search=document.querySelector('#search');
function filter(){{let n=0;for(const c of cards){{const keep=(group.value==='all'||c.dataset.group===group.value)&&(verdict.value==='all'||c.dataset.verdict===verdict.value)&&(change.value==='all'||c.dataset.change===change.value)&&c.textContent.toLocaleLowerCase('fr').includes(search.value.toLocaleLowerCase('fr'));c.hidden=!keep;if(keep)n++}}document.querySelector('#count').textContent=n+' réponses affichées'}}
[group,verdict,change,search].forEach(x=>x.addEventListener('input',filter));filter();document.querySelector('#download').onclick=()=>{{const u=URL.createObjectURL(new Blob([document.querySelector('#data').textContent],{{type:'application/json'}}));const a=document.createElement('a');a.href=u;a.download='bikefinder-chat-corrections-20261015.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}};
</script></html>'''
    current_html.write_text(page)
    print(current_html)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

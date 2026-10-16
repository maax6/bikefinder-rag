"""Render the dated real-chat audit; scores come from explicit assistant review."""
from collections import Counter
from pathlib import Path
import hashlib
import html
import json
import math
import re
import statistics

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'eval_results/technical/chat-clarifications-20261016'
OLD = ROOT / 'eval_results/technical/chat-corrections-20261015'
MD = MarkdownIt('commonmark', {'html': False}).enable('table')
esc = html.escape
LABELS = {'correct': 'Correcte', 'justified_limit': 'Limite utile', 'partial': 'Partielle', 'failure': 'Échec'}
RANK = {'correct': 2, 'justified_limit': 2, 'partial': 1, 'failure': 0}


def read(path):
    return json.loads(path.read_text())


def key(row):
    return f"{row['pass']}/{row['id']}/{row['turn']}"


def stats(rows):
    times = sorted(r['elapsed_seconds'] for r in rows)
    return {'n': len(times), 'median': statistics.median(times) if times else None,
            'p95': times[math.ceil(.95 * len(times)) - 1] if times else None,
            'maximum': max(times) if times else None}


def collect():
    traces = [read(p) for folder in ['server', 'server-polish', 'server-external', 'server-notices'] for p in (RUN / folder).glob('*.json')]
    traces = [t for t in traces if 'question' in t]
    old = {key(r): r for r in read(OLD / 'reviewed-results.json')['results']}
    rows = []
    for suffix in ['regression', 'new', 'polish', 'notices']:
        path = RUN / f'results-{suffix}.json'
        if not path.exists():
            continue
        result, pack = read(path), read(RUN / f'questions-{suffix}.json')
        assert result['questions_sha256'] == hashlib.sha256((RUN / f'questions-{suffix}.json').read_bytes()).hexdigest()
        cases = {c['id']: c for c in pack['cases']}
        for row in result['results']:
            row = dict(row)
            original_key = key(row)
            if suffix in {'polish', 'notices'}:
                row.update(pass_name=suffix, group='targeted_polish')
                row['pass'] = suffix
            matches = [t for t in traces if t['question'] == row['question'] and t.get('answer') == row.get('answer')
                       and t['started_at'] >= row['started_at']]
            trace = min(matches, key=lambda t: t['started_at']) if matches else {}
            meta = trace.get('metadata', {})
            rows.append({**row, 'key': key(row), 'before': next((r for r in rows if r['key'] == original_key), None) if suffix == 'notices' else old.get(original_key),
                         'provenance': cases[row['id']].get('provenance'), 'trace_id': trace.get('id'),
                         'route': meta.get('_catalog_route'), 'plan': meta.get('_catalog_plan'),
                         'generation': meta.get('_catalog_generation'), 'evidence': meta.get('_catalog_evidence'),
                         'server_seconds': trace.get('server_seconds'), 'http_calls': trace.get('http_calls', [])})
    return rows


def main():
    assert read(RUN / 'results-regression.json')['completed']
    assert read(RUN / 'results-polish.json')['completed']
    assert read(RUN / 'results-new.json')['completed']
    assert read(RUN / 'results-notices.json')['completed']
    rows = collect()
    review = read(RUN / 'review.json')
    grades = {g['key']: g for g in review['grades']}
    assert set(grades) == {r['key'] for r in rows}, 'Each observed response needs a review'
    for r in rows:
        r.update(grades[r['key']])
    first = [r for r in rows if r['pass'] == 'first']
    paired = [r for r in first if r['before']]
    external = [r for r in first if r['group'] == 'external_forum']
    grid = [r for r in first if 'rubric' in r]
    assert len(grid) == 20 + len(external)
    polish = [r for r in rows if r['pass'] in {'polish', 'notices'}]
    attempts = [r for r in first if (r['generation'] or {}).get('call_attempted')]
    external_attempts = [r for r in external if (r['generation'] or {}).get('call_attempted')]
    cost = sum(read(RUN / f / 'spending.json')['debit_usd'] for f in ['server', 'server-polish', 'server-external', 'server-notices'])
    metrics = {
        'submissions': len(rows), 'unique_first_turns': len(first), 'paired': len(paired),
        'paired_verdicts': dict(Counter(r['verdict'] for r in paired)),
        'external_verdicts': dict(Counter(r['verdict'] for r in external)),
        'external_mistral_attempts': len(external_attempts),
        'external_grid_totals': {c: sum(r['rubric'][c] for r in external) for c in ['accuracy', 'completeness', 'sources', 'usefulness']},
        'regressions': [r['key'] for r in paired if RANK[r['verdict']] < RANK[r['before']['verdict']]],
        'improvements': [r['key'] for r in paired if RANK[r['verdict']] > RANK[r['before']['verdict']]],
        'grid_n': len(grid), 'polish_n': len(polish), 'grid_totals': {c: sum(r['rubric'][c] for r in grid) for c in ['accuracy', 'completeness', 'sources', 'usefulness']},
        'mistral_attempts': len(attempts), 'mistral_modes': dict(Counter((r['generation'] or {}).get('mode', 'fallback') for r in attempts)),
        'generation_errors': dict(Counter(r['generation']['error'] for r in attempts if r['generation'].get('error'))),
        'api_errors': sum(bool(r.get('error')) for r in rows), 'cost_usd': cost,
        'cumulative_cost_usd': .017885532 + cost,
        'latency': {'paired_before': stats([r['before'] for r in paired]), 'paired_after': stats(paired),
                    'external': stats(external), 'mistral': stats(attempts),
                    'external_mistral': stats(external_attempts),
                    'regression_mistral': stats([r for r in paired if (r['generation'] or {}).get('call_attempted')]),
                    'repeat': stats([r for r in rows if r['pass'] == 'warm_repeat'])}}
    bundle = {'metrics': metrics, 'review': review, 'runtime': read(RUN / 'server/runtime.json'),
              'runtime_polish': read(RUN / 'server-polish/runtime.json'),
              'runtime_external': read(RUN / 'server-external/runtime.json'),
              'runtime_notices': read(RUN / 'server-notices/runtime.json'), 'results': rows,
              'pending_cases': read(RUN / 'questions-new.json')['cases'] if not external else []}
    (RUN / 'reviewed-results.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n')
    (RUN / 'summary.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n')
    css = re.search(r'<style>(.*?)</style>', (ROOT / 'docs/benchmark-chat-20261015-initial.html').read_text(), re.S)[1]
    css += '.metrics{grid-template-columns:repeat(3,1fr)}.metric b{font-size:32px}a,code{overflow-wrap:anywhere}.case[hidden]{display:none}.answer{overflow-x:auto}.grade{font-size:14px;color:var(--muted)}@media(max-width:700px){.metrics{grid-template-columns:1fr}}'
    cards = []
    for r in rows:
        provenance = r.get('provenance')
        source = f'<p>Question publique : <a href="{esc(provenance["url"], quote=True)}">fil original</a> · {esc(provenance["post_date"])}. {esc(provenance["adaptation"])}</p>' if provenance else ''
        g = r.get('generation') or {}
        candidate = g.get('candidate')
        draft = '<details><summary>Proposition de Mistral avant contrôle</summary><pre>' + esc(json.dumps(candidate, ensure_ascii=False, indent=2)) + '</pre><p>' + esc(r.get('draft_note', 'Pas de relecture détaillée séparée de cette proposition.')) + '</p></details>' if candidate else ''
        grade = '<p class="grade">Exactitude / complétude / sources / utilité : ' + ' / '.join(str(r['rubric'][c]) for c in ['accuracy', 'completeness', 'sources', 'usefulness']) + ' — chaque critère sur 2.</p>' if 'rubric' in r else ''
        before = r['before']
        old_answer = f'<details><summary>Réponse précédente · {before["elapsed_seconds"]:.2f} s</summary><div class="answer">{MD.render(before["answer"])}</div></details>' if before else ''
        passages = []
        for s in (r.get('evidence') or {}).get('sources', []):
            for p in s.get('passages', []):
                passages.append(f'<li><b>{esc(s["brand"] + " " + s["model"])} · {s["year"]} · {esc(p["section"])}</b><p>{esc(p["original_text"])}</p></li>')
        evidence = '<details><summary>Passages effectivement fournis</summary><ul>' + ''.join(passages) + '</ul></details>' if passages else ''
        group = 'polish' if r['pass'] in {'polish', 'notices'} else 'repeat' if r['pass'] == 'warm_repeat' else 'external' if provenance else 'regression'
        cards.append(f'''<article class="case" data-group="{group}" data-verdict="{r['verdict']}"><div class="case-top"><span>{r['id']} · tour {r['turn']}</span><span class="badge {r['verdict']}">{LABELS[r['verdict']]}</span><strong>{r['elapsed_seconds']:.2f} s</strong></div><h3>{esc(r['question'])}</h3>{source}<p class="review">{esc(r['note'])}</p>{grade}<details><summary>Réponse finale réellement affichée</summary><div class="answer">{MD.render(r.get('answer') or r.get('error') or '')}</div></details>{old_answer}{draft}<details><summary>Attendu figé avant l’essai</summary><p>{esc(r['expected'])}</p></details>{evidence}<small>Parcours : {esc(r.get('route') or '')} · rédaction : {esc(g.get('mode', g.get('error', 'pas de Mistral')))} · trace {esc(r.get('trace_id') or 'absente')}</small></article>''')
    times = ''.join(f'<tr><th>{label}</th><td>{v["n"]}</td><td>{v["median"]:.2f} s</td><td>{v["p95"]:.2f} s</td><td>{v["maximum"]:.2f} s</td></tr>' for label, k in [('Même lot, 15 octobre', 'paired_before'), ('Même lot, 16 octobre', 'paired_after'), ('Questions publiques', 'external'), ('Mistral · régression', 'regression_mistral'), ('Mistral · questions publiques', 'external_mistral'), ('Mistral · ensemble des premières passes', 'mistral'), ('Répétitions à chaud', 'repeat')] if (v := metrics['latency'][k])['n'])
    findings = ''.join(f'<li><b>{esc(f["title"])}</b><p>{esc(f["detail"])}</p></li>' for f in review['findings'])
    rubric = ''.join(f'<tr><th>{label}</th><td>{metrics["grid_totals"][c] - metrics["external_grid_totals"][c]} / 40</td><td>{metrics["external_grid_totals"][c]} / 20</td><td>{esc(explanation)}</td></tr>' for c, label, explanation in [('accuracy', 'Exactitude', 'Faits exacts et qualifications conservées.'), ('completeness', 'Complétude', 'Question traitée ou précision ciblée demandée.'), ('sources', 'Sources', 'Fiche exacte et citation adéquate ; pas de fait inventé.'), ('usefulness', 'Utilité / lisibilité', 'Réponse directe, prochaine étape utile, réserves proportionnées.')])
    external_cards = ''.join(f'<details><summary>À tester · {c["id"]} · {esc(c["turns"][0]["question"])}</summary><p><a href="{esc(c["provenance"]["url"], quote=True)}">Question originale</a> · {esc(c["provenance"]["post_date"])}</p><p>{esc(c["provenance"]["adaptation"])}</p><p>Attendu : {esc(c["turns"][0]["expected"])}</p></details>' for c in bundle['pending_cases'] if c.get('provenance'))
    raw = json.dumps(bundle, ensure_ascii=False).replace('<', '\\u003c')
    page = f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bikefinder · XJ6, avertissements et qualité finale</title><style>{css}</style></head><body><main><nav>Bikefinder / Annexe de validation / 16 octobre 2026</nav><header><div class="eyebrow">BGE-M3 d’origine · Vrai chat · Relecture par assistant</div><h1>Moins de bruit.<br>Des réponses évaluées.</h1><p class="lede">{esc(review['conclusion'])}</p></header><div class="metrics"><div class="metric"><b>{len(metrics['regressions'])} / {len(paired)}</b><span>régressions de contenu observées sur les tours comparables</span></div><div class="metric"><b>{len(grid)} réponses</b><span>relues selon quatre critères, dont dix questions publiques</span></div><div class="metric"><b>{metrics['latency']['mistral']['median']:.2f} s</b><span>médiane des tours sollicitant Mistral ; P95 {metrics['latency']['mistral']['p95']:.2f} s</span></div></div><p class="note">Le même assistant a corrigé le code et relu les sorties. Les questions publiques sont authentiques, mais sélectionnées par cet assistant ; cette campagne n’est ni une étude représentative de motards, ni une validation humaine indépendante.</p><p><a href="benchmark-chat-20261015.html">Bilan précédent conservé</a> · <a href="benchmark-finetuning.html">Annexe fine-tuning</a> · <a href="benchmark.html">Benchmark initial</a></p><h2>Corrections et constats</h2><ol>{findings}</ol><h2>La qualité des réponses finales</h2><p>Grille figée avant l’essai : 20 réponses du lot de régression ; {len(external)} questions publiques exécutées. Les retouches finales de présentation font l’objet de {len(polish)} tours supplémentaires séparés. Les 20 premières notes décrivent le lot de régression avant huit retouches contrôlées ; les 10 notes publiques décrivent leur première passe, sans correction du routage sur leurs résultats. Les deux derniers tours ne rejouent que le dialogue XJ6 après suppression d’un doublon A2. Chaque critère vaut 0, 1 ou 2 ; les notes détaillées figurent dans chaque cas. Une limite correcte peut rester peu utile. Les clarifications et tableaux ne sont pas attribués à Mistral. Le critère sources vaut aussi 2 lorsqu’aucun fait technique n’est avancé : un bon score de sources ne prouve donc ni la pertinence ni une réponse effective.</p><div class="table-wrap"><table><thead><tr><th>Critère</th><th>20 réponses de régression</th><th>10 questions publiques</th><th>Lecture</th></tr></thead><tbody>{rubric}</tbody></table></div><p>{esc(review['generation_note'])}</p><h2>Dix questions de motards, sans gabarit</h2><p>{esc(review['external_note'])}</p><p>Les liens d’origine, les éventuelles adaptations et les attendus figés sont visibles par question. Les réponses des forums n’ont pas servi de vérité technique. Les questions dépourvues d’année n’ont pas reçu artificiellement une année pour faciliter le test.</p>{external_cards}<h2>Délais et coût</h2><div class="table-wrap"><table><thead><tr><th>Population</th><th>Tours</th><th>Médiane</th><th>P95</th><th>Maximum</th></tr></thead><tbody>{times}</tbody></table></div><p>{esc(review['timing_note'])}</p><p>Coût distant observé : {cost:.6f} $ ; cumul des campagnes depuis le lot initial : {metrics['cumulative_cost_usd']:.6f} $, sous 0,50 $. Mistral tourne localement : son temps et son énergie ne sont pas chiffrés en dollars.</p><h2>Protocole et limites</h2><ul>{''.join('<li>'+esc(t)+'</li>' for t in review['limitations'])}</ul><p>{esc(review['software_validation'])}</p><h2>Inspecter les {len(rows)} réponses</h2><div class="filters"><label>Lot <select id="group"><option value="all">Tous</option><option value="regression">Régression et XJ6</option><option value="external">Forums</option><option value="repeat">Répétitions</option><option value="polish">Retouches finales</option></select></label><label>Verdict <select id="verdict"><option value="all">Tous</option>{''.join(f'<option value="{k}">{v}</option>' for k,v in LABELS.items())}</select></label><button id="download">Télécharger les données</button></div><div id="cases">{''.join(cards)}</div><footer>Questions, sorties et traces conservées. Aucune adaptation BGE ni fusion expérimentale activée.</footer></main><script id="data" type="application/json">{raw}</script><script>const group=document.getElementById('group'),verdict=document.getElementById('verdict');function filter(){{document.querySelectorAll('.case').forEach(e=>e.hidden=!(group.value==='all'||e.dataset.group===group.value)||!(verdict.value==='all'||e.dataset.verdict===verdict.value));}}group.addEventListener('change',filter);verdict.addEventListener('change',filter);document.getElementById('download').addEventListener('click',()=>{{let u=URL.createObjectURL(new Blob([document.getElementById('data').textContent],{{type:'application/json'}}));let a=document.createElement('a');a.href=u;a.download='bikefinder-chat-20261016.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}});</script></body></html>'''
    path = ROOT / 'docs/benchmark-chat-20261016-first-pass.html'
    path.write_text(page)
    print(path)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

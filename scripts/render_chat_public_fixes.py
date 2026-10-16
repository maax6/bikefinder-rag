"""Render observed post-fix chat responses against the preserved first pass."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import re
from render_chat_clarifications import MD, esc, key, read, stats, LABELS, RANK

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'eval_results/technical/chat-public-fixes-20261016'
BASE=ROOT/'eval_results/technical/chat-clarifications-20261016'
CRITERIA=['accuracy','completeness','sources','usefulness']


def collect():
    pack=read(RUN/'questions.json'); raw=read(RUN/'results.json')
    assert raw['completed'] and raw['questions_sha256']==hashlib.sha256((RUN/'questions.json').read_bytes()).hexdigest()
    before={key(r):r for r in read(BASE/'reviewed-results.json')['results']}
    traces=[read(p) for p in (RUN/'server').glob('*.json')]
    traces=[t for t in traces if 'question' in t]
    cases={c['id']:c for c in pack['cases']}
    rows=[]
    for r in raw['results']:
        matches=[t for t in traces if t['question']==r['question'] and t.get('answer')==r.get('answer') and t['started_at']>=r['started_at']]
        assert matches, key(r)
        trace=min(matches,key=lambda t:t['started_at']); meta=trace['metadata']
        rows.append({**r,'key':key(r),'before':before[key(r)],'trace_id':trace['id'],
                     'provenance':cases[r['id']].get('provenance'),'route':meta.get('_catalog_route'),
                     'plan':meta.get('_catalog_plan'),'generation':meta.get('_catalog_generation'),
                     'evidence':meta.get('_catalog_evidence'),'http_calls':trace['http_calls'],
                     'server_seconds':trace['server_seconds']})
    assert len(set(r['trace_id'] for r in rows))==len(rows)
    final_path=RUN/'results-final-scope.json'
    if final_path.exists():
        final=read(final_path)
        assert final['completed']
        assert final['questions_sha256']==hashlib.sha256((RUN/'questions-final-scope.json').read_bytes()).hexdigest()
        final_traces=[read(p) for p in (RUN/'server-final-scope').glob('*.json')]
        for r in final['results']:
            b=next(x for x in rows if x['key']==key(r))
            matches=[t for t in final_traces if t.get('question')==r['question'] and t.get('answer')==r.get('answer') and t['started_at']>=r['started_at']]
            assert matches
            trace=min(matches,key=lambda t:t['started_at']);meta=trace['metadata']
            rows.append({**r,'pass':'final_scope','key':f"final_scope/{r['id']}/{r['turn']}",
                'before':b,'trace_id':trace['id'],'provenance':cases[r['id']].get('provenance'),
                'route':meta.get('_catalog_route'),'plan':meta.get('_catalog_plan'),
                'generation':meta.get('_catalog_generation'),'evidence':meta.get('_catalog_evidence'),
                'http_calls':trace['http_calls'],'server_seconds':trace['server_seconds']})
    return rows


def main():
    rows=collect();review=read(RUN/'review.json');grades={g['key']:g for g in review['grades']}
    assert set(grades)=={r['key'] for r in rows}
    for r in rows:r.update(grades[r['key']])
    first=[r for r in rows if r['pass']=='first'];public=[r for r in first if r['group']=='external_forum']
    regression=[r for r in first if r['id'] not in {'X01',*[f'R{i:02d}' for i in range(1,11)]}]
    targeted=[r for r in public if r['before']['verdict'] in {'partial','failure'}]
    attempts=[r for r in first if (r.get('generation') or {}).get('call_attempted')]
    grid=[r for r in first if 'rubric' in r];assert len(grid)==30 and len(public)==10 and len(regression)==57
    cost=sum(read(p)['debit_usd'] for p in RUN.glob('server*/spending.json'))
    metrics={'submissions':len(rows),'first_turns':len(first),'regression_turns':len(regression),
        'regressions':[r['key'] for r in first if RANK[r['verdict']]<RANK[r['before']['verdict']]],
        'rubric_decreases':[{'key':r['key'],'criteria':[c for c in CRITERIA if r['rubric'][c]<r['before']['rubric'][c]]}
            for r in grid if any(r['rubric'][c]<r['before']['rubric'][c] for c in CRITERIA)],
        'targeted_n':len(targeted),'targeted_fixed':sum(r['verdict'] in {'correct','justified_limit'} for r in targeted),
        'public_before':dict(Counter(r['before']['verdict'] for r in public)),
        'public_after':dict(Counter(r['verdict'] for r in public)),
        'grid_n':len(grid),'grid':{group:{c:sum(r['rubric'][c] for r in grid if (r in public)==(group=='public')) for c in CRITERIA} for group in ['regression','public']},
        'mistral_attempts':len(attempts),'generation_errors':dict(Counter(r['generation']['error'] for r in attempts if r['generation'].get('error'))),
        'mistral_modes':dict(Counter(r['generation'].get('mode','fallback') for r in attempts)),
        'api_errors':sum(bool(r.get('error')) for r in rows),'cost_usd':cost,'cumulative_cost_usd':.020972238+cost,
        'latency':{'regression_before':stats([r['before'] for r in regression]),'regression_after':stats(regression),
            'public_before':stats([r['before'] for r in public]),'public_after':stats(public),
            'mistral':stats(attempts),'warm_repeat':stats([r for r in rows if r['pass']=='warm_repeat'])}}
    bundle={'metrics':metrics,'review':review,'runtime':read(RUN/'server/runtime.json'),
            'runtime_final_scope':read(RUN/'server-final-scope/runtime.json'),'results':rows}
    (RUN/'summary.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
    (RUN/'reviewed-results.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2)+'\n')
    css=re.search(r'<style>(.*?)</style>',(ROOT/'docs/benchmark-chat-20261016-first-pass.html').read_text(),re.S)[1]
    cards=[]
    for r in rows:
        b=r['before'];g=r.get('generation') or {};p=r.get('provenance');ev=r.get('evidence') or {}
        provenance=f'<p>Question publique : <a href="{esc(p["url"],quote=True)}">fil original</a> · {esc(p["adaptation"])}</p>' if p else ''
        rubric='<p class="grade">Exactitude / complétude / sources / utilité : '+ ' / '.join(str(r['rubric'][c]) for c in CRITERIA)+' (sur 2 chacun).</p>' if 'rubric' in r else ''
        candidate='<details><summary>Proposition de Mistral avant contrôle</summary><pre>'+esc(json.dumps(g['candidate'],ensure_ascii=False,indent=2))+'</pre><p>'+esc(r.get('draft_note',''))+'</p></details>' if g.get('candidate') else ''
        passages=''.join('<li><b>'+esc(s['brand']+' '+s['model']+' '+str(s['year'])+' / '+p['section'])+'</b><p>'+esc(p['original_text'])+'</p></li>' for s in ev.get('sources',[]) for p in s.get('passages',[]))
        proof='<details><summary>Passages réellement fournis</summary><ul>'+passages+'</ul></details>' if passages else ''
        mode=g.get('mode',g.get('error','réponse déterministe, sans Mistral'))
        group='repeat' if r['pass']=='warm_repeat' else 'public' if r in public else 'regression'
        phase={'first':'première passe','warm_repeat':'répétition','final_scope':'contrôle final UK'}[r['pass']]
        cards.append(f'''<article class="case" data-group="{group}" data-verdict="{r['verdict']}"><div class="case-top"><span>{r['id']} · tour {r['turn']} · {phase}</span><span class="badge {r['verdict']}">{LABELS[r['verdict']]}</span><strong>{r['elapsed_seconds']:.2f} s</strong></div><h3>{esc(r['question'])}</h3>{provenance}<p class="review">{esc(r['note'])}</p>{rubric}<details><summary>Après · réponse réellement affichée</summary><div class="answer">{MD.render(r.get('answer') or r.get('error') or '')}</div></details><details><summary>Avant · {LABELS[b['verdict']]} · {b['elapsed_seconds']:.2f} s</summary><div class="answer">{MD.render(b['answer'])}</div></details>{candidate}{proof}<details><summary>Attendu initial conservé</summary><p>{esc(r['expected'])}</p></details><small>Parcours : {esc(r.get('route') or '')} · {esc(mode)} · trace {esc(r['trace_id'])}</small></article>''')
    comparison=''.join(f'<tr><th>{r["id"]}</th><td>{esc(r["question"])}</td><td>{LABELS[r["before"]["verdict"]]}</td><td>{LABELS[r["verdict"]]}</td></tr>' for r in public)
    grid_table=''.join(f'<tr><th>{label}</th><td>{metrics["grid"]["regression"][c]} / 40</td><td>{metrics["grid"]["public"][c]} / 20</td></tr>' for c,label in zip(CRITERIA,['Exactitude','Complétude','Sources','Utilité / lisibilité']))
    timings=''.join(f'<tr><th>{label}</th><td>{v["n"]}</td><td>{v["median"]:.2f} s</td><td>{v["p95"]:.2f} s</td><td>{v["maximum"]:.2f} s</td></tr>' for k,label in [('regression_before','57 tours avant'),('regression_after','57 tours après'),('public_before','10 questions publiques avant'),('public_after','10 questions publiques après'),('mistral','Après : tours sollicitant Mistral'),('warm_repeat','Six répétitions à chaud')] if (v:=metrics['latency'][k])['n'])
    raw=json.dumps(bundle,ensure_ascii=False).replace('<','\\u003c')
    page=f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bikefinder · Corrections des questions libres</title><style>{css}</style></head><body><main><nav>Bikefinder / Annexe du vrai chat / 16 octobre 2026</nav><header><div class="eyebrow">BGE-M3 d’origine · Questions connues rejouées · Relecture par assistant</div><h1>Des modèles reconnus.<br>Des limites plus utiles.</h1><p class="lede">{esc(review['conclusion'])}</p></header><div class="metrics"><div class="metric"><b>{metrics['targeted_fixed']} / {metrics['targeted_n']}</b><span>cas ciblés désormais satisfaisants selon leur attendu : réponse sourcée ou limite utile</span></div><div class="metric"><b>{len(metrics['regressions'])} / {len(first)}</b><span>régressions de contenu observées sur les tours comparables</span></div><div class="metric"><b>{metrics['latency']['mistral']['median']:.2f} s</b><span>médiane des tours sollicitant Mistral ; les clarifications rapides restent séparées</span></div></div><p class="note">Ces questions ont servi à corriger le code. Le rejeu mesure la réparation et la non-régression, pas une généralisation sur un nouveau lot indépendant. Même assistant pour le code et la relecture.</p><p><a href="benchmark-chat-20261016-first-pass.html">Première passe conservée, avec les cinq échecs et deux réponses partielles</a> · <a href="benchmark-finetuning.html">Annexe fine-tuning</a></p><h2>Ce qui a changé</h2><ul>{''.join('<li>'+esc(x)+'</li>' for x in review['changes'])}</ul><h2>Les dix questions publiques : avant / après</h2><p>{esc(review['public_note'])}</p><div class="table-wrap"><table><thead><tr><th>Cas</th><th>Question originale</th><th>Avant</th><th>Après</th></tr></thead><tbody>{comparison}</tbody></table></div><h2>Qualité de 30 réponses finales</h2><p>La même grille de 0 à 2 : exactitude, réponse complète ou précision nécessaire, sources et utilité. Les réponses déterministes ne sont pas attribuées à Mistral. Un score de sources maximal est aussi possible sans affirmation technique : il ne signifie pas que la question a reçu une réponse factuelle.</p><div class="table-wrap"><table><thead><tr><th>Critère</th><th>20 réponses de régression</th><th>10 questions publiques</th></tr></thead><tbody>{grid_table}</tbody></table></div><p>{esc(review['generation_note'])}</p><h2>Temps et coût</h2><div class="table-wrap"><table><thead><tr><th>Population</th><th>Tours</th><th>Médiane</th><th>P95</th><th>Maximum</th></tr></thead><tbody>{timings}</tbody></table></div><p>{esc(review['timing_note'])}</p><p>Coût distant du rejeu : {cost:.6f} $. Cumul des campagnes : {metrics['cumulative_cost_usd']:.6f} $, sous le plafond de 0,50 $. Mistral est local ; son énergie et son temps ne sont pas facturés ici.</p><h2>Protocole, limites et suites</h2><ul>{''.join('<li>'+esc(x)+'</li>' for x in review['limitations'])}</ul><p>{esc(review['validation'])}</p><h2>Inspecter les {len(rows)} sorties du rejeu</h2><div class="filters"><label>Lot <select id="group"><option value="all">Tous</option><option value="public">Questions publiques connues</option><option value="regression">Régression et dialogue XJ6</option><option value="repeat">Répétitions</option></select></label><label>Verdict <select id="verdict"><option value="all">Tous</option>{''.join(f'<option value="{k}">{v}</option>' for k,v in LABELS.items())}</select></label><button id="download">Télécharger les données</button></div>{''.join(cards)}<footer>Questions, réponses, temps, coûts, propositions Mistral et preuves conservés. BGE-M3 original ; aucun adaptateur LoRA, aucune fusion expérimentale.</footer></main><script id="data" type="application/json">{raw}</script><script>const group=document.getElementById('group'),verdict=document.getElementById('verdict');function filter(){{document.querySelectorAll('.case').forEach(e=>e.hidden=!(group.value==='all'||e.dataset.group===group.value)||!(verdict.value==='all'||e.dataset.verdict===verdict.value));}}group.addEventListener('change',filter);verdict.addEventListener('change',filter);document.getElementById('download').addEventListener('click',()=>{{let u=URL.createObjectURL(new Blob([document.getElementById('data').textContent],{{type:'application/json'}}));let a=document.createElement('a');a.href=u;a.download='bikefinder-chat-public-fixes-20261016.json';a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}});</script></body></html>'''
    (ROOT/'docs/benchmark-chat-20261016.html').write_text(page)
    print(json.dumps(metrics,ensure_ascii=False,indent=2))

if __name__=='__main__':main()

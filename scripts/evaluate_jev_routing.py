#!/usr/bin/env python3
"""Frozen natural-question suite: routing, constraints, source IDs and latency.

No Mistral batch: its slow path is marked rather than invoking hundreds of
generations. Filters are checked against independently matched SQL result IDs.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
from pathlib import Path
import random
import time
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/technical/routing-eval-20261013'

def build(conn):
    from bikefinder_rag.catalog.enriched import _rows
    records=_rows(conn,'SELECT id,brand,model,year FROM technical_fiches f WHERE year IN (2000,2010,2020,2025) ORDER BY id',[])
    rng=random.Random(20261013);chosen=rng.sample(records,20)
    output=[]
    def add(question,kind,expected,group):
        output.append({'id':f'q{len(output):03}','question':question,'kind':kind,'expected':expected,'group':group,
            'split':'heldout' if int(hashlib.sha256(group.encode()).hexdigest()[:8],16)%3==0 else 'development'})
    patterns=[
        'Motos en dessous de {p} eu et minimum {h} cv en {y}',
        'Je cherche des motos de {y} sous {p} euros, au moins {h} chevaux.',
        'Liste les motos en {y} : moins de {p} €, minimum {h} ch.',
        'Tu peux me trouver des motos de {y} avec {h} ch minimum et un prix inférieur à {p} euros ?',
        'Pour {y}, budget maximum {p} euros et puissance minimum {h} ch.',
        'Sors-moi les motos de {y} à moins de {p} euros et avec au moins {h} chevaux.',
        'Quelles fiches de {y} dépassent {h} ch et coûtent moins de {p} € ?',
        'Combien de motos de {y} ont au moins {h} ch et un tarif sous {p} euros ?',
        'En {y}, motos avec minimum {h} cv pour un budget maximum {p} euros.',
        'Motos de {y} : puissance au moins {h} chevaux, prix inférieur à {p} €.',
        'Quelles Honda de {y} sont sous {p} euros avec {h} ch minimum ?',
        'Je veux les BMW en {y} à moins de {p} € et au moins {h} ch.',
        'Combien de Yamaha de {y} sont à maximum {p} euros et minimum {h} ch ?',
        'Quelles motos Kawasaki de {y} font plus de {h} chevaux pour moins de {p} euros ?',
        'Liste les modèles Suzuki en {y}, tarif maximum {p} €, au moins {h} ch.',
        'Tu as quoi en {y} sous {p} euros et avec {h} chevaux minimum ?',
        'Trouve les motos du millésime {y} qui coûtent moins de {p} € et font au moins {h} ch.',
        'Pourrais-tu lister les fiches de {y} avec un prix maximum de {p} euros et une puissance minimum de {h} ch ?',
    ]
    for i,pattern in enumerate(patterns):
        for k in range(10):
            p=[6000,8000,10000,12000,15000][k%5];h=[50,75,100,125,150][(k+i)%5];y=[2000,2010,2020,2025][k%4]
            q=pattern.format(p=p,h=h,y=y)
            price_op='<=' if 'maximum' in q else '<';power_op='>' if 'plus de' in q or 'dépassent' in q else '>='
            brand=next((b for b in ['Honda','BMW','Yamaha','Kawasaki','Suzuki'] if b in q),None)
            add(q,'filter',{'identity':{'year':y,**({'brand':brand} if brand else {})},'conditions':[{'field':'price_eur','op':price_op,'value':p},{'field':'power_ch','op':power_op,'value':h}], 'operation':'count' if q.startswith('Combien') else 'filter'},f'numeric-{i}')
    list_patterns=['Liste les {b} de {y}.','Quelles motos {b} du millésime {y} as-tu dans le catalogue ?','Combien de fiches {b} de {y} ?','Montre-moi les modèles {b} en {y}.','Tu as quelles {b} en {y} ?','Je voudrais voir toutes les {b} de {y}.','Quel est le nombre de motos {b} en {y} dans les données ?','Peux-tu lister les {b} du millésime {y} avec les sources ?']
    for i,pattern in enumerate(list_patterns):
        for k in range(10):
            b=['Honda','BMW','Yamaha','Suzuki','Kawasaki'][k%5];y=[2000,2010,2020,2025][k%4];q=pattern.format(b=b,y=y)
            add(q,'filter',{'identity':{'brand':b,'year':y},'conditions':[],'operation':'count' if i in [2,6] else 'filter'},f'brand-{i}')
    equipment_patterns=[
        'Quelles motos en {y} ont {e} de série ?',
        'Liste les motos de {y} avec {e} en option.',
        'Combien de fiches de {y} documentent {e} de série ?',
        'Montre-moi les motos du millésime {y} sans {e} explicitement.',
        'Pour {y}, sur quelles motos {e} est-il inconnu ?',
        'Je cherche des motos en {y} avec {e} installé de série.',
        'Quels modèles de {y} proposent {e} en option ?',
        'Tu as des motos de {y} équipées de {e} de série ?',
    ]
    for i,pattern in enumerate(equipment_patterns):
        for k in range(10):
            e=['ABS','CBS','régulateur de vitesse','poignées chauffantes','contrôle de traction'][k%5];y=[2000,2010,2020,2025][k%4]
            status='optional' if i in [1,6] else 'explicitly_absent' if i==3 else 'unknown' if i==4 else 'standard'
            add(pattern.format(e=e,y=y),'filter',{'identity':{'year':y},'conditions':[],'equipment':e,'status':status,'operation':'count' if i==2 else 'filter'},f'equipment-{i}')
    topics=[('autonomy_km','Quelle est l’autonomie estimée de la {name} de {year} ?'),('power_ch','Combien de chevaux développe la {name} en {year} ?'),('transmission','Que dit la fiche de la {name} de {year} sur sa transmission ?'),('suspension','Quels réglages de suspension sont documentés pour la {name}, millésime {year} ?'),('cooling','Comment est refroidi le moteur de la {name} en {year}, selon la fiche ?')]
    for i,(field,pattern) in enumerate(topics):
        for r in chosen:
            add(pattern.format(name=r['brand']+' '+r['model'],year=r['year']),'details',{'models':[{'brand':r['brand'],'model':r['model']}],'year':r['year'],'field':field},f'details-{i}')
    unsupported=[
        'Quelles motos d’occasion actuelles à moins de 10000 euros ont au moins 100 ch ?',
        'Quelles motos de 2020 ont ABS et sont homologuées en France ?',
        'Quelles motos de 2020 sont A2 avec minimum 100 ch ?',
        'Motos de 2020 à moins de 200 kg, sans préciser sec ou plein.',
        'Motos de 2020 avec au moins 100 kW et sous 10000 euros.',
        'Quelles motos de 2020 ont la meilleure réputation de fiabilité chez les propriétaires ?',
        'Motos de 2020 sous 8000 euros mais au-dessus de 15000 euros.',
        'Je cherche des motos de 2020 à moins de 120 kg et au moins 100 ch.',
        'Donne le prix neuf actuel des motos de 2020.',
        'Quelle est l’autonomie de la BMW R 1150 GS ?',
    ]
    for i,q in enumerate(unsupported):
        for y in [2000,2020,2025]:add(q.replace('2020',str(y)),'clarification',{},f'unsupported-{i}')
    for i,r in enumerate(chosen[:10]):
        q=f"Pour la {r['brand']} {r['model']} de {r['year']}, explique pourquoi les caractéristiques du moteur et de la suspension changent les sensations de conduite, sans inventer de mesures."
        add(q,'complex',{},'complex')
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'questions.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    return output

def evaluate(case):
    from bikefinder_rag.db.client import get_connection
    from bikefinder_rag.agent.jev_router import route_question
    from bikefinder_rag.agent.catalog_fast_path import answer_catalog_question
    from bikefinder_rag.catalog.measures import filtered
    conn=get_connection()
    try:
        start=time.perf_counter();baseline=answer_catalog_question(conn,case['question']);baseline_direct=baseline is not None
        result=route_question(conn,case['question']);checks={}
        expected=case['expected'];plan=result.get('plan') or {}
        if case['kind']=='filter':
            checks['direct_answer']=result['answer'] is not None and result['route'] in ['filter','count']
            checks['identity']=plan.get('identity')==expected['identity']
            checks['numeric_bounds']=sorted(plan.get('conditions',[]),key=lambda r:r['field'])==sorted(expected.get('conditions',[]),key=lambda r:r['field'])
            checks['operation']=plan.get('operation')==expected['operation']
            checks['equipment']=plan.get('equipment')==expected.get('equipment') and (not expected.get('equipment') or plan.get('status')==expected['status'])
            if all(checks.values()):
                count=filtered(conn,expected.get('conditions',[]),expected['identity'],expected.get('equipment'),expected.get('status','standard'),count=True)
                checks['exact_count']=f'**{count} fiches' in result['answer']
                checks['sources']=count==0 or expected['operation']=='count' or 'https://www.motoplanete.com/' in result['answer']
        elif case['kind']=='details':
            checks['direct_answer']=result['answer'] is not None and result['route'] in ['details','comparison']
            from bikefinder_rag.catalog.enriched import folded
            normalized=lambda models:[{k:folded(v) for k,v in m.items()} for m in models]
            checks['identity']=normalized(plan.get('models',[]))==normalized(expected['models']) and plan.get('identity',{}).get('year')==expected['year']
            checks['requested_field']=expected['field'] in plan.get('fields',[]) or 'full' in plan.get('fields',[])
            checks['source_or_ambiguity']='https://www.motoplanete.com/' in (result['answer'] or '') or 'Aucune fiche' in (result['answer'] or '')
        elif case['kind']=='complex':checks['mistral_required']=result['route']=='mistral_required'
        else:checks['clarification']=result['route']=='clarification' or (result['route']=='clarify' and 'Quel millésime' in (result['answer'] or ''))
        return {**case,'passed':all(checks.values()),'checks':checks,'seconds':time.perf_counter()-start,'baseline_direct':baseline_direct,
            'route':result['route'],'answer':result['answer'],'plan':result.get('plan'),'jev_calls':result.get('jev_calls',0),'cached':result.get('cached'),
            'model':result.get('raw',{}).get('model'),'cost':result.get('raw',{}).get('usage',{}).get('cost',0),'jev_answers':result.get('raw',{}).get('answers',{})}
    finally:conn.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--split',choices=['development','heldout','all'],default='all');parser.add_argument('--limit',type=int);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    load_dotenv()
    if args.prepare:
        from bikefinder_rag.db.client import get_connection
        conn=get_connection();build(conn);conn.close()
    questions=json.loads((OUT/'questions.json').read_text());selected=[q for q in questions if args.split=='all' or q['split']==args.split]
    if args.limit:selected=selected[:args.limit]
    from bikefinder_rag.agent.jev_router import PROTOCOL,MODEL
    metadata={'protocol':PROTOCOL,'model':MODEL,'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['src/bikefinder_rag/agent/jev_router.py','src/bikefinder_rag/catalog/measures.py','scripts/evaluate_jev_routing.py']}}
    results=[];args.out.parent.mkdir(parents=True,exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(evaluate,q) for q in selected]
        for future in as_completed(futures):
            results.append(future.result());args.out.write_text(json.dumps({**metadata,'questions_sha256':hashlib.sha256((OUT/'questions.json').read_bytes()).hexdigest(),'results':results},ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'completed':len(results),'total':len(selected),'passed':sum(r['passed'] for r in results),'last':results[-1]['id'],'route':results[-1]['route']}),flush=True)

if __name__=='__main__':main()

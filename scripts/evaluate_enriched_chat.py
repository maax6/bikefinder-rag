#!/usr/bin/env python3
"""Live local catalog/chat checks; persist measured results, not estimated latency."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from dotenv import load_dotenv

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();load_dotenv()
    from bikefinder_rag.db.client import get_connection
    from bikefinder_rag.catalog.enriched import search_technical,filter_catalog
    from bikefinder_rag.agent.loop import run_agent
    conn=get_connection();db=sqlite3.connect('file:'+str(args.source)+'?mode=ro',uri=True)
    result={'source_objects':db.execute('SELECT count(*) FROM objects').fetchone()[0], 'chat':[], 'sql':[]}
    try:
        preserved=rows=autonomy=0
        with conn.cursor() as cur:
            for id,raw,sha in db.execute('SELECT id,record,source_sha256 FROM objects'):
                cur.execute('SELECT record,source_sha256 FROM technical_fiches WHERE id=%s',[id]);stored=cur.fetchone()
                original=json.loads(raw)
                assert stored is not None and stored[0]==original and stored[1]==sha
                assert hashlib.sha256(raw.encode()).hexdigest()==sha
                preserved+=1;rows+=len(original['spec_rows'])
                autonomy+=any('autonomie' in (r['label']+' '+r['value']).lower() for r in original['spec_rows'])
        result['conservation']={'objects_exact':preserved,'spec_rows':rows,'autonomy_fiches':autonomy}
        for year in [1871,1950,2000,2010,2025,2027]:
            start=time.perf_counter();count=filter_catalog(conn,min_year=year,max_year=year,count_only=True)[0]['matching_motorcycles']
            expected=db.execute('SELECT count(*) FROM objects WHERE year=?',[year]).fetchone()[0]
            result['sql'].append({'year':year,'count':count,'expected':expected,'passed':count==expected,'seconds':time.perf_counter()-start})
        questions=[
            ("Quelles motos ont l'ABS en 2000 ?",['2 fiches','motoplanete.com']),
            ("Combien de motos de 2025 ont l'ABS de série ?",['fiches']),
            ("Quelles motos de 2025 ont l'ABS en option ?",['0 fiches']),
            ("Quelle est l'autonomie de la BMW R 1150 GS de 2000 ?",['440','calcul','non vérifi','motoplanete.com']),
            ("Donne l'ABS et l'autonomie de la CFMoto 800 MT Explore de 2025, avec la source.",['380','ABS','calcul','non vérifi','motoplanete.com']),
            ("Donne l'autonomie de la Ducati Desmo450 Sm de 2026.",['aucune fiche']),
            ("Compare l'autonomie documentée de la BMW R 1150 GS de 2000 et de la CFMoto 800 MT Explore de 2025. Explique les limites de cette comparaison.",['440','380','calcul','non vérifi','motoplanete.com']),
        ]
        for question,required in questions:
            start=time.perf_counter();answer,history=run_agent(conn,None,question,[],provider='ollama');seconds=time.perf_counter()-start
            checks={s:s.casefold() in answer.casefold() for s in required}
            calls=[call['function'] for m in history for call in m.get('tool_calls',[])]
            if 'Desmo450' in question:
                checks['requested_year_not_substituted']=bool(calls) and all(call['arguments'].get('year')==2026 for call in calls if call['name'] in ['get_catalog_details','get_bike_details','search_technical'])
            tools=[{'name':m.get('name'),'content':m.get('content')} for m in history if m.get('role')=='tool']
            result['chat'].append({'question':question,'answer':answer,'seconds':seconds,'checks':checks,'passed':all(checks.values()),'tool_calls':calls,'tool_results':tools})
            args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'question':question,'seconds':round(seconds,3),'passed':all(checks.values())}),flush=True)
        # Real BGE-M3 encoding and persistent vector cache, scoped to a single fiche.
        for run in range(2):
            start=time.perf_counter();passages=search_technical(conn,'autonomie calculée mais non vérifiée','R 1150 GS',2000,'BMW',3)
            checks=bool(passages) and all(p['year']==2000 and p['model']=='R 1150 GS' for p in passages)
            result.setdefault('bge',[]).append({'run':run,'seconds':time.perf_counter()-start,'passed':checks,'passages':passages})
            print(json.dumps({'bge_run':run,'seconds':round(time.perf_counter()-start,3),'passed':checks}),flush=True)
        result['all_checks_passed']=all(r['passed'] for name in ['sql','chat','bge'] for r in result[name])
        args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    finally:
        db.close();conn.close()

if __name__=='__main__':
    main()

#!/usr/bin/env python3
"""Replay independently authored free dialogue turns through the actual Gradio API.

Routing is inspected separately; API latency excludes this inspection. Model
route counts are reported independently from human/agent answer-quality review.
No expected verdict is inferred from successful transport alone.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from dotenv import load_dotenv
from gradio_client import Client

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--questions',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--url',default='http://127.0.0.1:7860/')
    parser.add_argument('--api-first',action='store_true',help='Measure the real API before separately inspecting its route; useful for new unseen questions.')
    args=parser.parse_args();load_dotenv(ROOT/'.env')
    from bikefinder_rag.agent.jev_router import route_question,PROTOCOL
    from bikefinder_rag.db.client import get_connection
    cases=json.loads(args.questions.read_text())['cases'];results=[]
    metadata={'protocol':PROTOCOL,'questions_sha256':hashlib.sha256(args.questions.read_bytes()).hexdigest(),
              'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['src/bikefinder_rag/agent/jev_router.py','src/bikefinder_rag/agent/query_language.py','src/bikefinder_rag/catalog/comparisons.py','src/bikefinder_rag/catalog/measures.py','src/bikefinder_rag/catalog/category_evidence.py','src/bikefinder_rag/catalog/unit_restatements.py','src/bikefinder_rag/catalog/source_counts.py','src/bikefinder_rag/catalog/source_equipment_answers.py','src/bikefinder_rag/catalog/supplemental_sources.py','src/bikefinder_rag/agent/loop.py','src/bikefinder_rag/app.py','src/bikefinder_rag/ui.py']}}
    for case in cases:
        client=Client(args.url,verbose=False);visible=[];history=[];conn=get_connection()
        try:
            for index,turn in enumerate(case['turns']):
                if not args.api_first:
                    start=time.perf_counter();routing=route_question(conn,turn['question'],history);route_seconds=time.perf_counter()-start
                start=time.perf_counter();visible=client.predict(turn['question'],visible,'',api_name='/chat');api_seconds=time.perf_counter()-start
                if args.api_first:
                    start=time.perf_counter();routing=route_question(conn,turn['question'],history);route_seconds=time.perf_counter()-start
                content=visible[-1]['content'];answer=content if isinstance(content,str) else '\n'.join(block.get('text','') for block in content)
                history.extend([{'role':'user','content':turn['question']},{'role':'assistant','content':answer,'_catalog_plan':routing.get('plan'),'_catalog_pending':routing.get('pending')}])
                results.append({'id':case['id'],'turn':index,**turn,'seconds':api_seconds,'route_seconds':route_seconds,'answer':answer,'routing':routing,
                    'consistent_with_direct_router':routing['answer'] is None or answer==routing['answer']})
                args.out.parent.mkdir(parents=True,exist_ok=True)
                args.out.write_text(json.dumps({**metadata,'routes':dict(Counter(r['routing']['route'] for r in results)),'results':results},ensure_ascii=False,indent=2)+'\n')
                print(json.dumps({'completed':len(results),'id':case['id'],'turn':index,'route':routing['route'],'api_seconds':api_seconds}),flush=True)
        finally:conn.close()


if __name__=='__main__':main()

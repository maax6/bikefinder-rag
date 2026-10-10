#!/usr/bin/env python3
"""Compare current tool-calling loop and hybrid routing on the same frozen SQL corpus."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.request

from dotenv import dotenv_values
from hybrid_poc_retrieval import DEFAULT_DB, DEFAULT_OUT, retrieve, sql_filter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
ROUTES = {
    'sql_list': 'List or count catalog motorcycles matching explicit year and brand or equipment filters. Do not answer with a vector top-k.',
    'passage': 'Retrieve the documented technical characteristic of one named motorcycle and explicit model year.',
    'complex': 'Explain tradeoffs or compare two or more motorcycles. This needs a synthesized answer.',
}


def records():
    return json.loads((DEFAULT_OUT / 'dataset.json').read_text())['records']


def prepare():
    corpus = records()
    queries = []
    targets = [('Hauteur de selle', 'Châssis'), ('Puissance', 'Moteur'), ('Fourche', 'Train avant'), ('Frein arrière', 'Train arrière'), ('Transmission', 'Transmission'), ('ABS', 'Équipement de série')]
    for i, (topic, section) in enumerate(targets):
        pool = [r for r in corpus if any(p['section'] == section for p in r['technical_sections'])]
        for k in [0, 1]:
            r = pool[min(len(pool)-1, 20 + i*29 + k*200)]
            queries.append({'id': f'passage-{i}-{k}', 'question': f"Que documente la fiche de la {r['name']}, millésime {r['year']}, à propos de {topic.lower()} ? Cite le texte et la source, ou indique inconnu.", 'expected_route': 'passage', 'expected_object_ids': [r['id']], 'expected_section': section})
    for year in [2000, 2004, 2008, 2010]:
        queries.append({'id': f'abs-{year}', 'question': f"Liste toutes les motos du catalogue de {year} avec ABS de série, avec leurs sources. Ne confonds pas option et série.", 'expected_route': 'sql_list', 'equipment': 'ABS', 'status': 'standard'})
    for brand, year in [('Honda', 2000), ('BMW', 2008)]:
        queries.append({'id': f'brand-{brand}-{year}', 'question': f'Liste les motos {brand} de {year} du catalogue avec leurs sources.', 'expected_route': 'sql_list'})
    for year in [2000, 2008]:
        chosen = [r for r in corpus if r['year'] == year][:2]
        queries.append({'id': f'complex-{year}', 'question': f"Compare la {chosen[0]['name']} et la {chosen[1]['name']}, toutes deux du millésime {year} : explique les compromis de suspension et de freinage uniquement à partir des fiches, avec sources.", 'expected_route': 'complex', 'expected_object_ids': [r['id'] for r in chosen]})
    for i, topic in enumerate(['Comment le mouvement du moteur arrive-t-il à la roue arrière ?', 'Quel dispositif absorbe les irrégularités sous la roue avant ?', 'Comment le moteur évacue-t-il la chaleur ?', 'Quel dispositif ralentit la roue arrière ?']):
        r = corpus[100+i*60]
        queries.append({'id': f'semantic-{i}', 'question': f"Pour la {r['name']}, millésime {r['year']}, {topic} Réponds uniquement à partir de la fiche et cite la source.", 'expected_route': 'passage', 'expected_object_ids': [r['id']], 'expected_section': ['Transmission','Train avant','Moteur','Train arrière'][i]})
    (DEFAULT_OUT / 'queries.json').write_text(json.dumps(queries, ensure_ascii=False, indent=2)+'\n')
    return queries


def entities(question):
    # Share the production policy: a displacement such as Vulcan 2000 is no date.
    from bikefinder_rag.agent.loop import _numeric_user_years
    years = sorted(_numeric_user_years(question))
    corpus = records()
    ids = [r['id'] for r in corpus if r['name'].casefold() in question.casefold()]
    brands = [b for b in set(r['brand'] for r in corpus) if b.casefold() in question.casefold()]
    filters = {}
    if len(years) == 1:
        filters['year'] = years[0]
    if ids:
        filters['object_ids'] = ids
    elif len(brands) == 1:
        filters['brand'] = brands[0]
    return filters


def route(question):
    key = dotenv_values(ROOT / '.env').get('OPENROUTER_API_KEY')
    body = {'model': 'typesafe/jev-1.13', 'state': {'question': question}, 'questions': {'route': {'type': 'choice', 'instructions': 'Which operation is needed to answer this question about a motorcycle technical catalog?', 'criteria': ROUTES}}}
    req = urllib.request.Request('https://openrouter.ai/api/alpha/decisions', data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def raw_rows(filters):
    hits = sql_filter(**filters)
    with closing(sqlite3.connect(f'{DEFAULT_DB.resolve().as_uri()}?mode=ro', uri=True)) as c:
        return [json.loads(c.execute('SELECT raw_json FROM records WHERE id=?', (r['id'],)).fetchone()[0]) for r in hits]


def legacy(resume=False):
    from bikefinder_rag.agent import loop
    from bikefinder_rag.agent.tools import FILTER_SPECS_SCHEMA, GET_BIKE_DETAILS_SCHEMA, _validate_technical_arguments, _technical_specs
    queries = json.loads((DEFAULT_OUT / 'queries.json').read_text())
    # Resumption is explicit and only for the same frozen question protocol.
    result_file = DEFAULT_OUT/'legacy-query-results.json'
    if resume:
        frozen=json.loads((DEFAULT_OUT/'benchmark-protocol.json').read_text())
        if frozen['file_sha256']['queries.json']!=hashlib.sha256((DEFAULT_OUT/'queries.json').read_bytes()).hexdigest():
            raise ValueError('Cannot resume with changed questions')
    output = json.loads(result_file.read_text()) if resume and result_file.exists() else []
    completed={r['id'] for r in output}
    original_execute, original_post = loop.execute_tool, loop.requests.post
    def normalized(text):
        return re.sub(r'[^a-z0-9]', '', text.casefold())
    for query in queries:
        if query['id'] in completed:
            continue
        calls, http = [], []
        def adapter(conn, name, args, **kwargs):
            schema = FILTER_SPECS_SCHEMA if name == 'filter_specs' else GET_BIKE_DETAILS_SCHEMA
            if name not in ['filter_specs', 'get_bike_details'] or set(args)-set(schema['input_schema']['properties']):
                result = [{'error': 'Unsupported tool or argument; no query executed.'}]
            elif _validate_technical_arguments(schema['input_schema'], args):
                result = [{'error': 'Invalid arguments; no query executed.'}]
            else:
                with closing(sqlite3.connect(f'{DEFAULT_DB.resolve().as_uri()}?mode=ro', uri=True)) as c:
                    all_records = [json.loads(r[0]) for r in c.execute('SELECT raw_json FROM records')]
                selected = [r for r in all_records if not args.get('brand') or normalized(args['brand']) in normalized(r['brand'])]
                if name == 'get_bike_details':
                    exact = [r for r in selected if normalized(args['model']) in [normalized(r['model']), normalized(r['brand']+' '+r['model'])] and r['year']==args['year']]
                    selected = exact or [r for r in selected if r['year']==args['year'] and all(w.casefold() in r['name'].casefold() for w in args['model'].split())]
                    selected = selected[:3]
                else:
                    selected = [r for r in selected if r['year'] >= args.get('min_year', 0) and r['year'] <= args.get('max_year', 9999)]
                    unsupported = set(args)-{'brand','min_year','max_year','count_only','limit','order_by'}
                    if unsupported or args.get('order_by', '-year').lstrip('-')!='year':
                        result = [{'error':'The frozen adapter does not normalize numerical/category filters; no query executed.'}]
                        calls.append({'name':name,'arguments':args,'results':result}); return result
                    selected.sort(key=lambda r:(r['year'],r['brand'],r['model']),reverse=not str(args.get('order_by','-year')).startswith('year'))
                    if args.get('count_only'):
                        result=[{'matching_motorcycles':len(selected)}]
                        calls.append({'name':name,'arguments':args,'results':result});return result
                    selected=selected[:min(args.get('limit',10),20)]
                result=[]
                for r in selected:
                    specs = dict(r['raw_specs'])
                    specs.update({p['section']:p['text'] for p in r['technical_sections']})
                    row={'id':r['id'],'brand':r['brand'],'model':r['model'],'year':r['year'],'url':r['url'],'raw_specs':specs,'source':'Frozen technical source; market applicability unknown'}
                    if name=='filter_specs':
                        # The production list tool exposes measures, not the
                        # entire sheet. Identity-only fixtures need no missing
                        # numerical normalization of this new source corpus.
                        _technical_specs(row,measures_only=True)
                    result.append(row)
            calls.append({'name':name,'arguments':args,'results':result});return result
        def post(*args, **kwargs):
            response=original_post(*args,**kwargs)
            payload=response.json()
            http.append({k:payload.get(k) for k in ['model','total_duration','load_duration','prompt_eval_count','eval_count']})
            return response
        loop.execute_tool, loop.requests.post = adapter, post
        start=time.perf_counter()
        try:
            answer,history=loop._run_agent_ollama(None,query['question'],None)
            result={'id':query['id'],'answer':answer,'tool_calls':calls,'http_calls':http,'seconds':time.perf_counter()-start}
        except Exception as exc:
            result={'id':query['id'],'error_type':type(exc).__name__,'seconds':time.perf_counter()-start}
        output.append(result)
        (DEFAULT_OUT/'legacy-query-results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'id':query['id'],'seconds':round(result['seconds'],2),'llm_calls':len(http),'tools':len(calls)}),flush=True)
    loop.execute_tool, loop.requests.post=original_execute,original_post


def known_section(question):
    text=question.casefold()
    for term,section in [('hauteur de selle','Châssis'),('puissance','Moteur'),('fourche','Train avant'),('frein arrière','Train arrière'),('transmission','Transmission')]:
        if term in text:
            return section
    return None


def evidence_gate(question, passages):
    key=dotenv_values(ROOT / '.env').get('OPENROUTER_API_KEY')
    state={'question':question,'passages':passages}
    questions={f'p{i}':{'type':'noul','instructions':f'Does passages[{i}] contain explicit source information that directly answers the question? A merely related topic is not enough.'} for i in range(len(passages))}
    req=urllib.request.Request('https://openrouter.ai/api/alpha/decisions', data=json.dumps({'model':'typesafe/jev-1.13','state':state,'questions':questions}).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=60) as response:raw=json.load(response)
    kept=[p for i,p in enumerate(passages) if raw['answers'][f'p{i}']['noul']>=.8]
    return kept,raw


def synthesize(question, filters, sections=None):
    """System 2 sees the full scoped source when evidence selection abstains."""
    context=[{'identity':r['identity'],'url':r['url'],'sections':[p for p in r['technical_sections'] if sections is None or p['section'] in sections]} for r in raw_rows(filters)]
    body={'model':'mistral-small3.2:latest','stream':False,'options':{'temperature':0,'num_ctx':4096,'num_predict':400},'messages':[{'role':'system','content':'Answer in French using only the supplied motorcycle passages, preserve differences and cite source URLs. Unknown facts remain unknown.'},{'role':'user','content':question+'\n'+json.dumps(context,ensure_ascii=False)}]}
    req=urllib.request.Request('http://127.0.0.1:11434/api/chat',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=180) as response:raw=json.load(response)
    return raw['message']['content'],{k:raw.get(k) for k in ['model','total_duration','load_duration','prompt_eval_count','eval_count','done_reason']}


def hybrid():
    import numpy as np
    queries=json.loads((DEFAULT_OUT/'queries.json').read_text())
    vectors=np.load(DEFAULT_OUT/'query-vectors.npy')
    metadata=json.loads((DEFAULT_OUT/'query-vectors-metadata.json').read_text())
    digest=hashlib.sha256((DEFAULT_OUT/'queries.json').read_bytes()).hexdigest()
    if metadata['queries_file_sha256']!=digest or metadata['ids']!=[q['id'] for q in queries] or len(vectors)!=len(queries):
        raise ValueError('Query vectors do not match the frozen question set')
    output=[]
    for i,query in enumerate(queries):
        start=time.perf_counter(); routing=route(query['question']); chosen=routing['answers']['route']['choice']; confidence=routing['answers']['route']['confidence']; filters=entities(query['question']);llm_calls=0; http=[]
        if chosen=='sql_list':
            if re.search(r'\bABS\b',query['question'],re.I):
                filters.update(equipment='ABS',status='standard',provider='cascade')
            results=sql_filter(**filters)
            answer={'count':len(results),'records':results,'scope':'Frozen source catalog only; unknown market; explicit series status'}
        elif chosen=='passage':
            if not filters.get('object_ids'):
                results=[];answer={'unknown':'Exact source identity not resolved; no broader vector search executed.'}
            elif known_section(query['question']):
                section=known_section(query['question'])
                results=[{'object_id':r['id'],'section':p['section'],'text':p['text'],'source_url':r['url']} for r in raw_rows(filters) for p in r['technical_sections'] if p['section']==section]
                answer={'passages':results,'path':'sql_section'}
            else:
                candidates=retrieve(query['question'],filters,topk=3,query_vector=vectors[i])
                results,gate=evidence_gate(query['question'],candidates) if candidates else ([],None)
                answer={'passages':results,'candidates':candidates,'gate_raw':gate,'path':'bge_jev_evidence'}
                if not results:
                    answer['synthesis'],trace=synthesize(query['question'],filters)
                    answer['fallback']='no_accepted_evidence'
                    http.append(trace);llm_calls=1
        else:
            answer,trace=synthesize(query['question'],filters,sections=['Train avant','Train arrière'])
            http.append(trace)
            llm_calls=1
        output.append({'id':query['id'],'route':chosen,'confidence':confidence,'routing_raw':routing,'filters':filters,'answer':answer,'seconds':time.perf_counter()-start,'llm_calls':llm_calls,'http_calls':http,'route_correct':chosen==query['expected_route']})
        (DEFAULT_OUT/'hybrid-query-results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'id':query['id'],'route':chosen,'seconds':round(output[-1]['seconds'],3),'llm_calls':llm_calls}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('stage',choices=['prepare','legacy','hybrid']);parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    if args.stage=='legacy':legacy(resume=args.resume)
    else:{'prepare':prepare,'hybrid':hybrid}[args.stage]()

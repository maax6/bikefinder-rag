#!/usr/bin/env python3
"""Two isolated enrichment passes over an immutable prepare_hybrid_poc snapshot.

Commands: --pass pass1|pass2 --action jev|mistral|finalize|report.
Only frozen files are read; the live crawl is never opened by this program.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import time

import evaluate_hybrid_poc as model
import equipment_enrichment_policy as policy

ROOT = Path(__file__).resolve().parents[1]


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def configure(out, name):
    destination = out / name
    destination.mkdir(exist_ok=True)
    model.OUT = destination
    if name == 'pass2':
        model.INSTRUCTION, model.CRITERIA = policy.INSTRUCTION, policy.CRITERIA
    return destination


def references(out):
    old = read(ROOT / 'data/technical/hybrid-poc/gold_annotations.json', [])
    new = read(out / 'new-audit-annotations.json', {}).get('annotations', [])
    return [('historical_regressions', old), ('new_source_audit', new)]


def grouped(cases):
    return {model.input_hash(c): c for c in cases}


def run_jev(out, name):
    destination = configure(out, name)
    cases = read(out / 'cases.json')
    selected = cases if name == 'pass1' else [c for c in cases if 'no_technical_mention' not in policy.source_flags(c)]
    write(destination / 'cases.json', selected)
    started = time.monotonic()
    model.run('jev')
    write(destination / 'jev-run-wall-time.json', {'seconds': time.monotonic() - started, 'selected_unique_inputs': len(grouped(selected))})


def fallback_reasons(case, answer, name):
    return model.checks(case, answer) if name == 'pass1' else policy.decision_flags(case, answer, 'jev')


def run_mistral(out, name):
    destination = configure(out, name)
    model.ensure_cache_protocol('mistral')
    cases = read(out / 'cases.json')
    jev = {r['input_hash']: r for r in read(destination / 'jev-classifications.json', [])}
    audit_keys = {r['decision_input_key'] for _, refs in references(out) for r in refs}
    todo = {}
    for digest, case in grouped(cases).items():
        reasons = fallback_reasons(case, jev.get(digest, {}), name)
        audit = case['decision_input_key'] in audit_keys
        needs = model.has_mention(case) and bool(reasons)
        if name == 'pass2' and policy.source_flags(case):
            needs = False  # A second model cannot repair missing or ambiguous evidence.
        if needs or audit:
            todo[digest] = case
    path = destination / 'mistral-classifications.json'
    cache = {r['input_hash']: r for r in read(path, [])}
    started = time.monotonic()
    print(json.dumps({'pass': name, 'provider': 'mistral', 'selected': len(todo), 'cached': len(cache)}), flush=True)
    for digest, case in todo.items():
        if digest in cache and not cache[digest].get('error_type'):
            continue
        result = model.ask(case, 'mistral')
        cache[digest] = result
        write(path, list(cache.values()))
        print(json.dumps({'completed': len(cache), 'selected': len(todo), 'error': result.get('error_type'), 'seconds': result['seconds']}), flush=True)
        if result.get('error_type'):
            raise RuntimeError('Mistral request failed; cache preserved for resume')
    write(destination / 'mistral-run-wall-time.json', {'seconds': time.monotonic() - started, 'selected_unique_inputs': len(todo)})


def decide(case, jev, local, name):
    digest = model.input_hash(case)
    answer = jev.get(digest, {})
    if name == 'pass1':
        reasons = model.checks(case, answer)
        if not model.has_mention(case):
            status, stage = 'unknown', 'code_no_mention'
        elif reasons:
            fallback = local.get(digest, {})
            status, stage = fallback.get('status', 'unknown'), 'mistral_fallback'
            if not fallback or fallback.get('error_type'):
                reasons.append('missing_local_result')
        else:
            status, stage = answer['status'], 'jev'
    else:
        reasons = policy.source_flags(case)
        if reasons:
            status = 'unknown'
            stage = 'code_no_mention' if reasons == ['no_technical_mention'] else 'source_review'
        elif policy.literal_availability(case):
            status, stage = policy.literal_availability(case), 'code_literal_evidence'
            reasons = ['explicit_source_fact; model uncertainty does not remove the original fact']
        else:
            reasons = policy.decision_flags(case, answer, 'jev')
            if not reasons:
                status, stage = answer['status'], 'jev'
            else:
                fallback = local.get(digest, {})
                local_reasons = policy.decision_flags(case, fallback, 'mistral')
                if local_reasons:
                    reasons += ['mistral:' + r for r in local_reasons]
                    status, stage = 'unknown', 'source_review'
                else:
                    status, stage = fallback['status'], 'mistral_fallback'
    if status not in policy.CRITERIA:
        status, stage = 'unknown', 'source_review'
    return {'case_id': case['id'], 'object_id': case['object_id'], 'equipment': case['equipment'],
            'status': status, 'stage': stage, 'reasons': reasons, 'market': None,
            'source_url': case['source_url'], 'passages': case['passages'], 'input_hash': digest}


def finalize(out, name):
    destination = configure(out, name)
    cases = read(out / 'cases.json')
    jev = {r['input_hash']: r for r in read(destination / 'jev-classifications.json', [])}
    local = {r['input_hash']: r for r in read(destination / 'mistral-classifications.json', [])}
    decisions = [decide(c, jev, local, name) for c in cases]
    write(destination / 'decisions.json', decisions)
    write(destination / 'pipeline-protocol.json', {
        'dataset_sha256': hashlib.sha256((out / 'dataset.json').read_bytes()).hexdigest(),
        'cases_sha256': hashlib.sha256((out / 'cases.json').read_bytes()).hexdigest(),
        'policy_sha256': hashlib.sha256((ROOT / 'scripts/equipment_enrichment_policy.py').read_bytes()).hexdigest(),
        'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'model_protocols': {provider: read(destination / f'{provider}-cache-protocol.json') for provider in ['jev','mistral']},
        'mistral_resolved_model': read(out / 'mistral-resolved-model.json'),
        'note': 'Model evaluations include diagnostic/audit calls; final route is replayed from saved outputs. Source uncertainty is never repaired by a model.',
    })
    if name == 'pass2':
        dataset = read(out / 'dataset.json')
        overlay = {}
        for d in decisions:
            overlay.setdefault(d['object_id'], {})[d['equipment']] = d
        db_path = destination / 'catalogue.enriched.sqlite3'
        conn = sqlite3.connect(db_path)
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS objects(id TEXT PRIMARY KEY,url TEXT,brand TEXT,model TEXT,year INTEGER,source_sha256 TEXT,record TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS equipment(object_id TEXT,equipment TEXT,status TEXT,stage TEXT,decision TEXT,PRIMARY KEY(object_id,equipment))')
            conn.execute('DELETE FROM objects');conn.execute('DELETE FROM equipment')
            for record in dataset['records']:
                raw = json.dumps(record, ensure_ascii=False, sort_keys=True)
                conn.execute('INSERT INTO objects VALUES(?,?,?,?,?,?,?)', (record['id'],record['url'],record['brand'],record['model'],record['year'],hashlib.sha256(raw.encode()).hexdigest(),raw))
                equipment = dict(overlay.get(record['id'], {}))
                if 'ABS' not in equipment:
                    equipment['ABS'] = {'object_id': record['id'], 'equipment': 'ABS', 'status': 'unknown', 'stage': 'code_no_mention', 'market': None, 'source_url': record['url'], 'reasons': ['no_target_evidence'], 'passages': []}
                for term, decision in equipment.items():
                    conn.execute('INSERT INTO equipment VALUES(?,?,?,?,?)', (record['id'],term,decision['status'],decision['stage'],json.dumps(decision,ensure_ascii=False)))
        conn.close()
    print(json.dumps({'pass': name,'decisions':len(decisions),'stages':dict(Counter(d['stage'] for d in decisions))}), flush=True)


def score(refs, cases, predictions):
    by_key = {c['decision_input_key']: c for c in cases}
    matched = []
    for ref in refs:
        case = by_key.get(ref['decision_input_key'])
        if not case:
            continue
        predicted = predictions.get(model.input_hash(case), 'unknown')
        matched.append({'case_id':case['id'],'equipment':case['equipment'],'expected':ref['status'],'predicted':predicted,'correct':predicted==ref['status']})
    return {'available':len(matched),'references':len(refs),'correct':sum(x['correct'] for x in matched),'mismatches':[x for x in matched if not x['correct']]}


def report(out):
    cases = read(out / 'cases.json')
    dataset = read(out / 'dataset.json')
    result = {'objects':len(dataset['records']),'equipment_cases':len(cases),'unique_inputs':len(grouped(cases)),
              'method_limit':'Source conformity on targeted agent annotations; not manufacturer truth or representative accuracy.', 'passes':{}}
    for name in ['pass1','pass2']:
        destination = out / name
        jev = read(destination / 'jev-classifications.json', [])
        local = read(destination / 'mistral-classifications.json', [])
        decisions = read(destination / 'decisions.json', [])
        stats = {'jev_calls':len(jev),'mistral_calls':len(local),'jev_errors':sum(bool(r.get('error_type')) for r in jev),'mistral_errors':sum(bool(r.get('error_type')) for r in local),
                 'stages':dict(Counter(d['stage'] for d in decisions)),'statuses':dict(Counter(d['status'] for d in decisions)),
                 'jev_cost_usd':sum(r.get('raw',{}).get('usage',{}).get('cost',0) or 0 for r in jev),'audit':{}}
        stats['unique_final_routes'] = dict(Counter({d['input_hash']:d['stage'] for d in decisions}.values()))
        stats['latency_seconds'] = {}
        for provider, rows in [('jev',jev),('mistral',local)]:
            durations = sorted(r['seconds'] for r in rows if not r.get('error_type'))
            stats['latency_seconds'][provider] = {'median':statistics.median(durations) if durations else None,
                'p95':durations[min(len(durations)-1,int(len(durations)*.95))] if durations else None,
                'run':read(destination / f'{provider}-run-wall-time.json')}
        for subset, refs in references(out):
            stats['audit'][subset] = {
                'jev':score(refs,cases,{r['input_hash']:r.get('status','unknown') for r in jev}),
                'mistral':score(refs,cases,{r['input_hash']:r.get('status','unknown') for r in local}),
                'cascade':score(refs,cases,{d['input_hash']:d['status'] for d in decisions}),
            }
        result['passes'][name] = stats
    write(out / 'summary.json', result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--pass', dest='name', choices=['pass1','pass2'], default='pass2')
    parser.add_argument('--action', choices=['jev','mistral','finalize','report'], required=True)
    args = parser.parse_args()
    if args.action == 'report':
        report(args.out)
    else:
        {'jev':run_jev,'mistral':run_mistral,'finalize':finalize}[args.action](args.out,args.name)

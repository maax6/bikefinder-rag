#!/usr/bin/env python3
"""Small frozen evidence-classification POC, isolated from the crawl database."""
import argparse
import json
import os
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data/technical/jev-poc'
LABELS = ['standard', 'optional', 'explicitly_absent', 'unknown']
INSTRUCTIONS = '''Classify the requested motorcycle equipment using ONLY the supplied source excerpt for this model/year. Return standard, optional, explicitly_absent or unknown. Explicit wording in the text overrides section headings: 'en option' under 'Équipement de série' means optional. A clear equipment listing in 'Équipement de série' supports standard unless the text qualifies it. A price 'avec ABS' alone identifies a priced variant, not standard or optional equipment for the whole model: unknown. No mention means unknown, never absent. Do not use outside motorcycle knowledge. The market remains unknown unless technical equipment applicability explicitly specifies a country; a French price does not establish technical applicability.'''


def key(variable="TYPESAFE_API_KEY"):
    value = os.getenv(variable)
    if value:
        return value
    for file in [ROOT / '.env', Path('/Users/m4ks/github/jevtest/.env')]:
        if file.exists():
            for line in file.read_text().splitlines():
                if line.strip().startswith(variable + '='):
                    return line.split('=', 1)[1].strip().strip('\"\'') or None
    return None


def run(provider):
    cases = json.loads((OUT / 'cases.json').read_text())
    rows = []
    client = None
    if provider == 'openrouter' and not key('OPENROUTER_API_KEY'):
        raise SystemExit('Jev/OpenRouter non exécuté : OPENROUTER_API_KEY manquante.')
    if provider == 'jev':
        if not key():
            raise SystemExit('Jev non exécuté : TYPESAFE_API_KEY manquante.')
        from typesafe_sdk import Choice, TypeSafeClient, RetryPolicy
        client = TypeSafeClient(api_key=key(), model='jev-latest', timeout=45, retry=RetryPolicy(max_retries=0))
    try:
        for case in cases:
            state = {k: case[k] for k in ['name', 'year', 'equipment', 'section', 'text']}
            start = time.perf_counter()
            result = {'id': case['id'], 'provider': provider}
            try:
                if provider == 'openrouter':
                    questions = {
                        'status': {'type': 'choice', 'instructions': INSTRUCTIONS, 'criteria': {label: None for label in LABELS}},
                        'market': {'type': 'choice', 'instructions': INSTRUCTIONS + ' Is France explicitly established as the technical equipment market?', 'criteria': {'unknown': None, 'France': None}}}
                    body = {'model': 'typesafe/jev-1.13', 'state': state, 'questions': questions}
                    request = urllib.request.Request('https://openrouter.ai/api/alpha/decisions', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key('OPENROUTER_API_KEY')})
                    with urllib.request.urlopen(request, timeout=45) as response:
                        raw = json.load(response)
                    prediction = {name: raw['answers'][name]['choice'] for name in ['status', 'market']}
                    if prediction['status'] not in LABELS or prediction['market'] not in ['unknown', 'France']:
                        raise ValueError('Invalid decision labels')
                elif client:
                    response = client.system_one(state=state, questions={
                        'status': Choice(instructions=INSTRUCTIONS, criteria={label: None for label in LABELS}),
                        'market': Choice(instructions=INSTRUCTIONS + ' Is France explicitly established as the technical equipment market?', criteria={'unknown': None, 'France': None})})
                    raw = response.model_dump(mode='json')
                    prediction = {'status': response.choices['status'].choice, 'market': response.choices['market'].choice}
                else:
                    schema = {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': LABELS}, 'market': {'type': 'string', 'enum': ['unknown', 'France']}}, 'required': ['status', 'market'], 'additionalProperties': False}
                    body = {'model': 'mistral-small3.2:latest', 'stream': False, 'format': schema, 'keep_alive': '5m', 'options': {'temperature': 0, 'num_ctx': 4096, 'num_predict': 100}, 'messages': [{'role': 'system', 'content': INSTRUCTIONS}, {'role': 'user', 'content': json.dumps(state, ensure_ascii=False)}]}
                    request = urllib.request.Request('http://127.0.0.1:11434/api/chat', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
                    with urllib.request.urlopen(request, timeout=180) as response:
                        raw = json.load(response)
                    prediction = json.loads(raw['message']['content'])
                result.update(prediction=prediction, raw=raw, correct=prediction == case['expected'])
            except Exception as exc:
                # Do not log request headers, keys, or provider error bodies.
                result['error_type'] = type(exc).__name__
            result['seconds'] = round(time.perf_counter() - start, 3)
            rows.append(result)
            (OUT / f'{provider}-results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps({k: v for k, v in result.items() if k != 'raw'}, ensure_ascii=False), flush=True)
            if result.get('error_type'):
                break
    finally:
        if client:
            client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider', choices=['jev', 'openrouter', 'local'])
    run(parser.parse_args().provider)

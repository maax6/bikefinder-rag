"""Freeze the user's additional average-price checks, using raw source rows."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'eval_results/technical/chat-corrections-20261015'
pack = json.loads((OUT / 'questions-final.json').read_text())
with sqlite3.connect(f'file:{ROOT}/data/technical/enrichment-full-20261012/pass2/catalogue.enriched.sqlite3?mode=ro', uri=True) as conn:
    records = {i: json.loads(r) for i, r in conn.execute('select id,record from objects')}


def price(row):
    values = []
    for r in row['spec_rows']:
        if r['section'] == 'Tarifs' and r['label'] == 'France — Version de base':
            match = re.fullmatch(r'\s*([\d\s.,]+)\s*€\s*\*?\s*', r['value'])
            if match:
                value = re.sub(r'\s+', '', match[1]).replace(',', '.')
                values.append(Decimal(value))
    return values[0] if values and len(set(values)) == 1 else None


cases = []
for id, question, selected in [
    ('P01', 'Quel est le prix moyen de catalogue des Yamaha de 2020 ? Utilise les tarifs France de base et indique combien de prix sont connus.',
     [i for i, r in records.items() if r['brand'] == 'Yamaha' and r['year'] == 2020]),
    ('P02', 'Calcule le prix moyen de catalogue de la Honda CB 500 F sur 2020, 2021 et 2022, un tarif France de base par année.',
     [i for i, r in records.items() if r['brand'] == 'Honda' and r['model'] == 'CB 500 F' and r['year'] in (2020, 2021, 2022)])]:
    known = {i: price(records[i]) for i in selected if price(records[i]) is not None}
    expected = {'total_fiches': len(selected), 'known_prices': len(known), 'sum_eur': str(sum(known.values())),
                'mean_eur': str(sum(known.values()) / len(known)),
                'scope': 'France, version de base, prix documentés du catalogue ; ni prix actuels ni annonces d’occasion ; inconnus exclus, pas zéro.'}
    cases.append({'id': id, 'group': 'holdout', 'category': 'prix_moyen', 'turns': [
        {'question': question, 'expected': json.dumps(expected, ensure_ascii=False), 'object_ids': selected}]})
cases.append({'id': 'P03', 'group': 'holdout', 'category': 'limite_prix', 'turns': [{
    'question': 'Quel est le prix moyen actuel en occasion des Yamaha de 2020 ?',
    'expected': 'Signaler l’absence de prix d’annonces actuels ; ne pas leur substituer les prix de catalogue.', 'object_ids': []}]})
pack.update(cases=cases, created_at=datetime.now(timezone.utc).isoformat())
pack['protocol']['extension'] = 'Three average-price checks added after the explicit user request: oublie pas prix moyen. Frozen before their live execution; original and 12-turn packs unchanged.'
path = OUT / 'questions-price.json'
if path.exists():
    raise SystemExit('Refuse overwrite frozen price checks')
path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + '\n')
print(path, hashlib.sha256(path.read_bytes()).hexdigest())
for c in cases:
    print(c['id'], c['turns'][0]['expected'])

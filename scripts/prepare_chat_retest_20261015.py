"""Freeze the unchanged baseline and 12 additional turns before the live retest."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'eval_results/technical/chat-corrections-20261015'
BASE = ROOT / 'eval_results/technical/chat-baseline-20261015/questions-final.json'
DB = ROOT / 'data/technical/enrichment-full-20261012/pass2/catalogue.enriched.sqlite3'
pack = json.loads(BASE.read_text())
with sqlite3.connect(f'file:{DB}?mode=ro', uri=True) as conn:
    records = {i: json.loads(r) for i, r in conn.execute('select id,record from objects')}
    equipment = {}
    for i, e, s, d in conn.execute('select object_id,equipment,status,decision from equipment'):
        equipment.setdefault(i, []).append({'equipment': e, 'status': s, 'decision': json.loads(d)})


def ids(brand, model=None, years=(2022,)):
    return [i for i, r in records.items() if r['brand'] == brand and (model is None or r['model'] == model) and r['year'] in years]


def exact_value(i, unit, label=None):
    values = set()
    for row in records[i]['spec_rows']:
        if label and row['label'] != label:
            continue
        match = re.match(r'^([\d ,]+)\s*' + unit + r'\b', row['value'])
        if match:
            values.add(float(match[1].replace(' ', '').replace(',', '.')))
    return values.pop() if len(values) == 1 else None


def turn(question, expected, object_ids=()):
    return {'question': question, 'expected': expected, 'object_ids': list(object_ids)}


def add(id, category, *turns):
    pack['cases'].append({'id': id, 'group': 'holdout', 'category': category, 'turns': list(turns)})


for id, brand, year, op, unit, label, question in [
    ('H01', 'Honda', 2020, max, 'cc', None, 'Dans les fiches Honda du millésime 2020, trouve la cylindrée maximale et toutes les versions à égalité.'),
    ('H02', 'Kawasaki', 2022, min, 'mm', 'Hauteur de selle', 'Quelle hauteur de selle minimale est documentée chez Kawasaki en 2022 ? Cite tous les ex æquo et la couverture des données.')]:
    population = ids(brand, years=(year,))
    values = {i: exact_value(i, unit, label) for i in population}
    known = {i: v for i, v in values.items() if v is not None}
    winner = op(known.values())
    expected = {'value': winner, 'unit': unit, 'winners': [records[i]['name'] for i, v in known.items() if v == winner], 'documented': len(known), 'total': len(population)}
    add(id, 'agregation', turn(question, json.dumps(expected, ensure_ascii=False), population))

bandit = ids('Suzuki', 'GSF 1200 BANDIT', (2000, 2001))
cb = ids('Honda', 'CB 500 F', (2020, 2021, 2022))
crf = ids('Honda', 'CRF 450 R', (2021,))
benelli = ids('Benelli', '500 Leoncino', (2022,))
add('H03', 'agregation', turn('Pour la Suzuki GSF 1200 Bandit, calcule séparément le poids moyen à sec et tous pleins sur 2000 et 2001, une fiche par millésime.', 'Deux moyennes distinctes : 214 kg à sec et 244 kg tous pleins, chacune 2/2 fiches, deux sources exactes.', bandit))
add('H04', 'agregation', turn('Sur les Honda CB 500 F de 2020, 2021 et 2022, donne le poids moyen sec puis le poids moyen en ordre de marche.', 'Sec : aucune valeur, ne pas calculer zéro. Wet : 189 kg sur 3/3 fiches. Sources et dénominateurs distincts.', cb))
add('H05', 'absence', turn('Calcule la puissance moyenne de la Honda CB 500 F entre les millésimes 1990 et 2022 uniquement, pas les années intermédiaires.', '1990 absent : population incomplète signalée. 2022 = 48 ch ; moyenne sur la seule fiche disponible explicitement partielle, ou clarification sans substitution.', ids('Honda', 'CB 500 F')))
add('H06', 'lecture', turn('La fiche de la Honda CRF 450 R 2021 donne-t-elle une puissance précise ou approximative ? Cite la valeur telle quelle.', 'Reprendre la ligne source avec son approximation, sans la rendre exacte.', crf))
add('H07', 'clarification',
    turn('Quel réservoir possède la Benelli 500 Leoncino ?', 'Demander le millésime et conserver le modèle, sans choisir une année.'),
    turn('2022.', 'Même Benelli 500 Leoncino 2022, réservoir 12,70 litres, source exacte.', benelli))
triumph = ids('Triumph')
add('H08', 'pagination',
    turn('Affiche les trois premières fiches Triumph 2022, dans un ordre stable.', 'Trois fiches Triumph 2022, ordre stable et total visible.', triumph),
    turn('Et les trois suivantes.', 'Trois nouvelles fiches de la même sélection, sans doublon ; positions 4 à 6.', triumph))
add('H09', 'clarification',
    turn('Je voudrais le poids moyen à sec de la Suzuki GSF 1200 Bandit.', 'Clarifier la population de la moyenne, conserver modèle et type de poids.'),
    turn('Les millésimes 2000 et 2001.', 'Moyenne 214 kg à sec, 2/2 fiches, aucune confusion avec 244 kg tous pleins.', bandit))

used = {i for c in pack['cases'] for t in c['turns'] for i in t['object_ids']}
pack['reference_evidence'].update({i: {'identity': records[i]['identity'], 'source_url': records[i]['source_url'],
    'spec_rows': records[i]['spec_rows'], 'technical_sections': records[i].get('technical_sections', []),
    'equipment': equipment.get(i, [])} for i in used if i not in pack['reference_evidence']})
pack['created_at'] = datetime.now(timezone.utc).isoformat()
pack['baseline_sha256'] = hashlib.sha256(BASE.read_bytes()).hexdigest()
pack['protocol']['retest'] = 'Baseline questions and expectations unchanged. Twelve additional turns frozen before live submission; same author, new wording, known task families. No claim of independent validation.'
pack['protocol']['planned'] = '42 baseline turns + 12 additional turns + the same 6 predefined warm repeats = 60 real Gradio submissions.'
OUT.mkdir(parents=True, exist_ok=True)
path = OUT / 'questions-final.json'
if path.exists():
    raise SystemExit('Refuse overwrite frozen retest')
path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + '\n')
print(path, hashlib.sha256(path.read_bytes()).hexdigest())
for c in pack['cases']:
    if c['group'] == 'holdout':
        print(c['id'], [t['expected'] for t in c['turns']])

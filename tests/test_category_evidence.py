"""Cross-source identities and explicit source categories, never AI categories."""
import json
import re
import sqlite3

import pytest

from bikefinder_rag.catalog import category_evidence as categories


@pytest.fixture
def catalog(monkeypatch):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE technical_fiches (id TEXT,brand TEXT,model TEXT,year INTEGER,
                                      source_url TEXT,record TEXT);
        CREATE TABLE motorcycles (brand TEXT,model TEXT,year INTEGER,category TEXT,
                                 url TEXT,category_fr TEXT);
    ''')
    fiches = [
        ('road', 'Honda', 'CB 650 R', 2023),
        ('trail', 'Honda', 'CRF 300 L', 2023),
        ('other-year', 'Honda', 'CB 650 R', 2022),
        ('variant', 'Honda', 'CB 650 R SP', 2023),
        ('unknown', 'Honda', 'CB 750', 2023),
        ('conflict', 'Honda', 'CB 600 F Hornet', 2007),
        ('unspecified', 'Honda', 'Unknown', 2023),
        ('evil-url', 'Honda', 'Suspicious', 2023),
        ('fraction', 'BMW', 'R25/2', 1953),
    ]
    conn.executemany('INSERT INTO technical_fiches VALUES(?,?,?,?,?,?)', [
        (*row, 'https://motoplanete.com/' + row[0], json.dumps({'spec_rows': []})) for row in fiches])
    bikes = [
        ('HONDA', 'CB-650-R', 2023, 'Naked bike', 'road', 'Sportive'),
        ('Honda', 'CB650R', 2023, 'naked   bike', 'duplicate', 'Trail'),
        ('Honda', 'CRF300L', 2023, 'Enduro/offroad', 'trail', 'Roadster'),
        ('Honda', 'CB600F Hornet', 2007, 'Naked bike', 'hornet-naked', 'Roadster'),
        ('Honda', 'CB 600 F Hornet', 2007, 'Sport', 'hornet-sport', 'Roadster'),
        ('Honda', 'Unknown', 2023, 'Unspecified category', 'unspecified', 'Roadster'),
        ('BMW', 'R252', 1953, 'Naked bike', 'wrong-numeric-variant', 'Roadster'),
    ]
    conn.executemany('INSERT INTO motorcycles VALUES(?,?,?,?,?,?)', [
        (*row[:4], 'https://bikez.com/motorcycles/' + row[4] + '.php', row[5]) for row in bikes])
    conn.execute('INSERT INTO motorcycles VALUES(?,?,?,?,?,?)', (
        'Honda', 'Suspicious', 2023, 'Naked bike', 'https://bikez.com.evil.test/fake', 'Roadster'))

    def sql_rows(db, query, params):
        # SQLite fixtures execute real identity year predicates. Only the
        # PostgreSQL JSON projection is replaced by equivalent fixture decoding.
        query = re.sub(r",COALESCE\(.*? AS motor_rows", ',record AS motor_rows', query)
        rows = [dict(row) for row in db.execute(query.replace('%s', '?'), params)]
        for row in rows:
            if 'motor_rows' in row:
                row['motor_rows'] = json.loads(row['motor_rows'])['spec_rows']
        return rows

    monkeypatch.setattr(categories, '_rows', sql_rows)
    yield conn
    conn.close()


def test_category_uses_exact_identity_and_raw_labels_not_ai(catalog):
    result = categories.source_category_scope(catalog, {'category': 'roadster'})
    assert result['ids'] == ['road']
    assert result['coverage'] == {'scope_objects': 9, 'known_objects': 2, 'matching_objects': 1,
                                  'unknown_objects': 7, 'conflicting_objects': 1}
    assert len(result['proofs']['road']) == 2
    assert {p['category_raw'] for p in result['proofs']['road']} == {'Naked bike', 'naked   bike'}
    assert all(p['source'] == 'bikez' and p['source_identity']['year'] == 2023 for p in result['proofs']['road'])
    assert result['non_exhaustive'] is True
    assert 'tous les roadsters' in result['source_note']


def test_negative_does_not_turn_unknown_or_conflicting_into_absence(catalog):
    result = categories.source_category_scope(catalog, {'category': 'roadster', 'negated': True})
    assert result['ids'] == ['trail']
    assert set(result['unknown_ids']) == {'other-year', 'variant', 'unknown', 'conflict',
                                           'unspecified', 'evil-url', 'fraction'}
    assert result['conflict_ids'] == ['conflict']
    assert 'conflict' not in result['known_ids']


def test_trail_broad_raw_taxonomy_is_explicit(catalog):
    result = categories.source_category_scope(catalog, {'category': 'trail'})
    assert result['ids'] == ['trail']
    assert result['raw_categories'] == ['Enduro/offroad']
    assert 'enduro' in result['source_note'] and 'sans prouver un usage routier' in result['source_note']


def test_year_brand_model_scope_and_typography_remain_exact(catalog):
    result = categories.source_category_scope(catalog, {'category': 'roadster',
                                                       'identity': {'brand': 'HONDA', 'model': 'CB-650-R', 'year': 2023}})
    assert result['ids'] == ['road']
    assert result['coverage']['scope_objects'] == 1
    assert categories.source_category_scope(catalog, {'category': 'roadster', 'identity': {'year': 2022}})['ids'] == []
    assert categories.source_category_scope(catalog, {'category': 'trail', 'identity': {'min_year': 2022, 'max_year': 2023}})['ids'] == ['trail']


def test_name_is_not_sql_code(catalog):
    result = categories.source_category_scope(catalog, {'category': 'roadster',
                                                       'identity': {'brand': "Honda'; DROP TABLE motorcycles; --"}})
    assert result['ids'] == []
    assert catalog.execute('SELECT count(*) FROM motorcycles').fetchone()[0] == 8


def test_numeric_identity_keeps_fractions_and_decimals():
    assert categories.identity_key('BMW', 'R25/2', 1953) != categories.identity_key('BMW', 'R252', 1953)
    assert categories.identity_key('BMW', 'R25.2', 1953) != categories.identity_key('BMW', 'R252', 1953)
    assert categories.identity_key('Honda', 'CB-650-R', 2023) == categories.identity_key('HONDA', 'CB 650 R', 2023)


@pytest.mark.parametrize('criterion', [
    None, [], {}, {'category': []}, {'category': 'scooter'}, {'category': 'roadster', 'negated': 'yes'},
    {'category': 'roadster', 'identity': []}, {'category': 'roadster', 'identity': {'market': 'France'}},
    {'category': 'roadster', 'identity': {'year': '2023'}}, {'category': 'roadster', 'identity': {'year': True}},
    {'category': 'roadster', 'identity': {'model': ''}},
    {'category': 'roadster', 'identity': {'min_year': 2024, 'max_year': 2023}},
])
def test_invalid_requests_fail_before_sql(monkeypatch, criterion):
    monkeypatch.setattr(categories, '_rows', lambda *args: pytest.fail('Invalid input reached SQL'))
    with pytest.raises(ValueError):
        categories.source_category_scope(None, criterion)


def test_electric_propulsion_and_starter_are_different(catalog):
    specs = {
        'ev': [{'section': 'Moteur', 'label': '', 'value': 'Électrique longitudinal'}],
        'starter': [{'section': 'Moteur', 'label': 'Système de démarrage', 'value': 'électrique'},
                    {'section': 'Moteur', 'label': '', 'value': 'Bicylindre en ligne, 4 temps'}],
        'petrol': [{'section': 'Moteur', 'label': '', 'value': 'Bicylindre en ligne, 4 temps'},
                   {'section': 'Moteur', 'label': 'Carburant', 'value': 'sans Plomb 95'}],
        'contradictory-source': [{'section': 'Moteur', 'label': '', 'value': 'Électrique en ligne , 4 temps'}],
        'undocumented': [{'section': 'Moteur', 'label': '', 'value': '0 cc'}],
        'non-motor': [{'section': 'Équipements', 'label': '', 'value': 'moteur électrique'}],
    }
    catalog.execute('DELETE FROM technical_fiches')
    catalog.executemany('INSERT INTO technical_fiches VALUES(?,?,?,?,?,?)', [
        (key, 'Fixture', key, 2024, 'https://motoplanete.com/' + key,
         json.dumps({'spec_rows': rows})) for key, rows in specs.items()])
    positive = categories.source_category_scope(catalog, {'category': 'electrique'})
    assert positive['ids'] == ['ev']
    assert positive['proofs']['ev'][0]['spec_rows'][0]['value'] == 'Électrique longitudinal'
    negative = categories.source_category_scope(catalog, {'category': 'electrique', 'negated': True})
    assert negative['ids'] == ['petrol']
    assert negative['conflict_ids'] == ['contradictory-source']
    assert set(negative['unknown_ids']) == {'contradictory-source', 'undocumented', 'non-motor', 'starter'}


@pytest.mark.parametrize(('model', 'specs'), [
    ('Sorcerer Hybrid', [{'section': 'Moteur', 'label': '', 'value': 'Bicylindre en ligne, 4 temps'}]),
    ('Fixture', [{'section': 'Moteur', 'label': '', 'value': 'Bicylindre en ligne, 4 temps'},
                 {'section': 'Moteur', 'label': '', 'value': 'Hybride'}]),
    ('Fixture', [{'section': 'Moteur', 'label': '', 'value': 'Bicylindre en ligne, 4 temps'},
                 {'section': 'Moteur', 'label': 'Carburant', 'value': 'essence et électricité'}]),
    ('Fixture', [{'section': 'Moteur', 'label': '', 'value': 'Bicylindre en ligne, 4 temps'},
                 {'section': 'Moteur', 'label': '', 'value': 'Injection Ø 36 mm + Batterie Li-ion 48V'}]),
    ('Fixture', [{'section': 'Moteur', 'label': 'Carburant', 'value': 'sans Plomb 95'},
                 {'section': 'Moteur', 'label': 'Motorisation', 'value': 'hybride parallèle'}]),
])
def test_hybrid_evidence_never_becomes_an_electric_absence(catalog, model, specs):
    catalog.execute('DELETE FROM technical_fiches')
    catalog.execute('INSERT INTO technical_fiches VALUES(?,?,?,?,?,?)', (
        'hybrid', 'Fixture', model, 2024, 'https://motoplanete.com/hybrid', json.dumps({'spec_rows': specs})))
    for negated in (False, True):
        result = categories.source_category_scope(catalog, {'category': 'electrique', 'negated': negated})
        assert result['ids'] == []
        assert result['known_ids'] == []
        assert result['unknown_ids'] == ['hybrid']
        # Mixed propulsion is legitimate; it is not contradictory evidence.
        assert result['conflict_ids'] == []


def test_four_stroke_alone_does_not_prove_absence_of_electric_drive(catalog):
    catalog.execute('DELETE FROM technical_fiches')
    catalog.execute('INSERT INTO technical_fiches VALUES(?,?,?,?,?,?)', (
        'thermal-looking', 'Fixture', 'Twin', 2024, 'https://motoplanete.com/twin',
        json.dumps({'spec_rows': [{'section': 'Moteur', 'label': '', 'value': 'Bicylindre en ligne, 4 temps'}]})))
    result = categories.source_category_scope(catalog, {'category': 'electrique', 'negated': True})
    assert result['ids'] == [] and result['unknown_ids'] == ['thermal-looking']


@pytest.mark.parametrize('specs', [
    [{'section': 'Moteur', 'label': '', 'value': 'Électrique'},
     {'section': 'Moteur', 'label': '', 'value': 'Batterie 14,4 kWh'}],
    [{'section': 'Moteur', 'label': 'Carburant', 'value': 'électricité'}],
])
def test_battery_in_an_explicit_electric_motor_remains_positive_evidence(catalog, specs):
    catalog.execute('DELETE FROM technical_fiches')
    catalog.execute('INSERT INTO technical_fiches VALUES(?,?,?,?,?,?)', (
        'ev', 'Fixture', 'EV', 2024, 'https://motoplanete.com/ev', json.dumps({'spec_rows': specs})))
    assert categories.source_category_scope(catalog, {'category': 'electrique'})['ids'] == ['ev']
    assert categories.source_category_scope(catalog, {'category': 'electrique', 'negated': True})['ids'] == []


def test_starter_battery_does_not_disqualify_explicit_thermal_fuel(catalog):
    catalog.execute('DELETE FROM technical_fiches')
    catalog.execute('INSERT INTO technical_fiches VALUES(?,?,?,?,?,?)', (
        'petrol', 'Fixture', 'Twin', 2024, 'https://motoplanete.com/petrol',
        json.dumps({'spec_rows': [{'section': 'Moteur', 'label': 'Carburant', 'value': 'essence'},
                                 {'section': 'Moteur', 'label': 'Système de démarrage', 'value': 'batterie / électrique'}]})))
    result = categories.source_category_scope(catalog, {'category': 'electrique', 'negated': True})
    assert result['ids'] == ['petrol']
    assert result['proofs']['petrol'][0]['spec_rows'] == [{'section': 'Moteur', 'label': 'Carburant', 'value': 'essence'}]


@pytest.mark.parametrize(('question', 'expected'), [
    ('Montre-moi les roadsters de 2020 avec ABS.', [('roadster', False)]),
    ('Je veux un trail et pas des sportives.', [('trail', False), ('sportive', True)]),
    ('Les routières, hors roadsters, de moins de 9000 euros.', [('routiere', False), ('roadster', True)]),
    ('Quelles motos non électriques entre 2020 et 2023 ?', [('electrique', True)]),
    ('Une moto à moteur électrique.', [('electrique', False)]),
    ('Ça coûte moins de 9000 balles ?', []),
    ('Triumph Roadster 2023, combien de chevaux ?', []),
    ('La Honda avec démarrage électrique.', []),
    ('Pas forcément sportive, plutôt légère.', []),
])
def test_literal_category_request_parser(question, expected):
    assert [(x['category'], x['negated']) for x in categories.categories_from_text(question)] == expected


def test_model_name_can_be_protected():
    question = 'Compare la Suzuki Trail 125 avec des roadsters.'
    start = question.index('Suzuki')
    end = question.index(' avec')
    parsed = categories.categories_from_text(question, protected_spans=[(start, end)])
    assert [(x['category'], x['negated']) for x in parsed] == [('roadster', False)]


def test_small_parser_keeps_one_constraint_and_rejects_ambiguous_combinations():
    assert categories.parse_category('Des motos électriques avec ABS.') == {'category': 'electrique', 'negated': False}
    assert categories.parse_category('Pas des trails.') == {'category': 'trail', 'negated': True}
    assert categories.parse_category('Les roadsters ou des trails.') is None
    assert categories.parse_category('Une machine pas chère.') is None

"""Compound counts must retain clauses and quote only current source rows."""
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from bikefinder_rag.catalog import source_counts as counts


@pytest.fixture(autouse=True)
def isolate_csv_exports(monkeypatch, tmp_path):
    monkeypatch.setattr(counts, 'EXPORT_DIRECTORY', tmp_path / 'chat-exports')


FIRST = ('Combien de fiches de 2018 à 2024 inclus, de 500 à 800 cm³, '
         'selle <=820 mm, ABS explicitement de série, excluant BMW, Yamaha et Honda ? Compte et liste.')
SECOND = ('Liste les Ducati/Triumph/KTM de 2010 à 2020, transmission secondaire par chaîne, '
          'réservoir au moins 15 litres, boîte à 6 rapports, sans les versions S ni R comme mots séparés du modèle.')
THIRD = ('Compte les motos de 1990 à 2009 : 2 disques de frein avant, secondaire par chaîne, '
         'empattement <1450 mm, cylindrée <1000 cc, hors Honda/Kawasaki/Suzuki/Yamaha, '
         'triées par empattement croissant.')
NATURAL_FIRST = ('Dans ton catalogue, combien d’entrées de 2018 à 2024 inclus ont une cylindrée entre 500 et 800 cm³ inclus, '
                 'une hauteur de selle de 820 mm maximum et l’ABS explicitement de série ? Exclue BMW, Yamaha et Honda. '
                 'Liste les modèles, millésimes et variantes retenus, et compte chaque entrée une seule fois.')
NATURAL_SECOND = ('Combien de fiches Ducati, Triumph ou KTM de 2010 à 2020 inclus ont une transmission finale par chaîne, '
                  'un réservoir d’au moins 15 litres et une boîte à 6 rapports ? Écarte les variantes dont le nom contient '
                  'S ou R comme mot séparé. Donne-moi la liste avec le total, et précise ce que tu ne peux pas trancher faute de données.')
NATURAL_THIRD = ('Dans les fiches de 1990 à 2009 inclus, combien ont deux disques à l’avant, une transmission finale par chaîne '
                 'et un empattement inférieur à 1 450 mm ? Exclue les cylindrées de 1 000 cm³ ou plus et les marques japonaises '
                 'Honda, Kawasaki, Suzuki et Yamaha. Liste les résultats par empattement croissant, avec modèle, année et variante.')


def spec(section, label, value):
    return {'section': section, 'label': label, 'value': value}


def fiche(id='one', model='Example', year=2020, brand='Triumph', **changes):
    values = {
        'displacement': '650 cc (Alésage * course : 80 x 64 mm)',
        'seat': '810 mm', 'wheelbase': '1 400 mm', 'tank': '15,50 litres',
        'gears': 'boîte à 6 rapports', 'secondary': 'Secondaire par chaîne',
        'front': '2 disques Ø 300 mm, étrier 4 pistons', 'abs': 'ABS de série',
    }
    values.update(changes)
    rows = [spec('Moteur', '', values['displacement']),
            spec('Châssis', 'Hauteur de selle', values['seat']),
            spec('Châssis', 'Empattement', values['wheelbase']),
            spec('Châssis', 'Réservoir', values['tank']),
            spec('Transmission', '', values['gears']),
            spec('Transmission', '', values['secondary']),
            spec('Train avant', 'Freinage', values['front']),
            spec('Équipement de série', 'Assistance au freinage', values['abs'])]
    return {'id': id, 'brand': brand, 'model': model, 'year': year,
            'source_url': 'https://example.org/' + id,
            'source_sha256': 'current-sha-' + id, 'record': {'spec_rows': rows}}


def fake_sources(monkeypatch, rows):
    def read(conn, query, params):
        chosen = [row for row in rows if params[0] <= row['year'] <= params[1]]
        offset = 2
        if 'lower(f.brand) = ANY' in query and 'NOT (lower(f.brand)' not in query:
            chosen = [row for row in chosen if row['brand'].lower() in params[offset]]
            offset += 1
        if 'NOT (lower(f.brand)' in query:
            chosen = [row for row in chosen if row['brand'].lower() not in params[offset]]
        return chosen
    mocked = Mock(side_effect=read)
    monkeypatch.setattr(counts, '_rows', mocked)
    return mocked


def test_first_range_retains_four_clauses_and_brand_exclusions():
    plan = counts.parse_source_count(FIRST)
    assert 'blocked_reason' not in plan
    assert (plan['min_year'], plan['max_year']) == (2018, 2024)
    assert plan['include_brands'] == []
    assert plan['exclude_brands'] == ['BMW', 'Honda', 'Yamaha']
    assert plan['conditions'] == [
        {'field': 'displacement_ccm', 'op': '>=', 'value': 500},
        {'field': 'displacement_ccm', 'op': '<=', 'value': 800},
        {'field': 'seat_height_mm', 'op': '<=', 'value': 820},
        {'field': 'abs_standard', 'op': '=', 'value': 1},
    ]


def test_second_request_keeps_brand_union_and_variant_word_exclusions():
    plan = counts.parse_source_count(SECOND)
    assert 'blocked_reason' not in plan
    assert plan['include_brands'] == ['Ducati', 'KTM', 'Triumph']
    assert plan['exclude_variant_words'] == ['R', 'S']
    assert {c['field'] for c in plan['conditions']} == {'tank_l', 'gears', 'secondary'}


def test_third_request_preserves_strict_bounds_and_sort():
    plan = counts.parse_source_count(THIRD)
    assert 'blocked_reason' not in plan
    assert plan['order_by'] == 'wheelbase_mm'
    assert {'field': 'wheelbase_mm', 'op': '<', 'value': 1450} in plan['conditions']
    assert {'field': 'front_discs', 'op': '=', 'value': 2} in plan['conditions']
    assert plan['exclude_brands'] == ['Honda', 'Kawasaki', 'Suzuki', 'Yamaha']


@pytest.mark.parametrize('extra', [
    'et A2', 'vendues en France', 'roadsters', 'moins de 180 kg',
    'et 100 chevaux', 'et confortables', 'mais pas un réservoir de 15 litres',
    'ou cylindrée > 1200 cc', 'autonomie minimum 300 km',
    'sans ABS de série', 'prix inférieur à 10000 euros',
    'fiables pour voyager', 'équipées de DCT', 'sauf Aprilia',
    'avec selle <=82 cm', 'et empattement <=140 cm',
])
def test_unknown_or_union_clause_never_runs_partial_query(monkeypatch, extra):
    read = Mock()
    monkeypatch.setattr(counts, '_rows', read)
    result = counts.try_source_count(None, FIRST + ' ' + extra)
    assert result['route'] == 'clarification'
    assert 'Aucun compte partiel' in result['answer']
    read.assert_not_called()


@pytest.mark.parametrize('question', [
    'Une MT07 2020 fait combien de chevaux ?',
    'Combien de roadsters Yamaha en 2020 ?',
    'Liste les motos avec ABS', 'Quelle est la selle de cette moto ?',
    'Combien de motos 2018–2024 avec puissance > 100 ch ?',
])
def test_outside_closed_compound_grammar_defers(question):
    assert counts.parse_source_count(question) is None


@pytest.mark.parametrize('question', [
    FIRST.replace('2018 à 2024', '2024 à 2018'),
    FIRST.replace('500 à 800', '800 à 500'),
    FIRST + ' et cylindrée >800 cc',
    SECOND + ' et réservoir <15 litres',
])
def test_contradictory_bounds_do_not_execute(monkeypatch, question):
    read = Mock()
    monkeypatch.setattr(counts, '_rows', read)
    result = counts.try_source_count(None, question)
    assert result['route'] == 'clarification'
    read.assert_not_called()


def test_source_projection_quotes_rows_not_projection_table():
    row = fiche()
    projected = counts.project_source(row['record'])
    assert projected['displacement_ccm'].values == (650,)
    assert projected['tank_l'].values == (15.5,)
    assert projected['wheelbase_mm'].values == (1400,)
    assert projected['gears'].values == (6,)
    assert projected['front_discs'].values == (2,)
    assert projected['abs_standard'].rows == (row['record']['spec_rows'][-1],)


def test_count_scopes_identity_year_and_every_source_constraint(monkeypatch):
    rows = [fiche('valid'), fiche('pre-year', year=2017), fiche('brand', brand='Honda'),
            fiche('large', displacement='801 cc'), fiche('small', displacement='499 cc'),
            fiche('high', seat='821 mm'), fiche('optional', abs='ABS en option'),
            fiche('unknown', abs='non communiqué'), fiche('lower-inclusive', displacement='500 cc'),
            fiche('upper-inclusive', displacement='800 cc', seat='820 mm')]
    read = fake_sources(monkeypatch, rows)
    result = counts.try_source_count(None, FIRST)
    assert result['route'] == 'count'
    assert result['plan']['total'] == 3
    assert result['plan']['unresolved_source_fiches'] == 1
    assert '15,50 litres' not in result['answer']  # not a requested field
    assert '650 cc (Alésage * course : 80 x 64 mm)' in result['answer']
    query, params = read.call_args.args[1:]
    assert 'technical_measures' not in query and 'UPDATE' not in query
    assert '>= %s' in query and '<= %s' in query
    assert params == [2018, 2024, ['bmw', 'honda', 'yamaha']]
    assert all(source['source_sha256'].startswith('current-sha-') for source in result['plan']['shown_sources'])


def test_variant_words_do_not_exclude_rs_r1_or_super_names(monkeypatch):
    rows = [fiche('base', model='Monster 1200', brand='Ducati'),
            fiche('s', model='Monster 1200 S', brand='Ducati'),
            fiche('r', model='Street Triple R', brand='Triumph'),
            fiche('rs', model='Street Triple RS', brand='Triumph'),
            fiche('r1', model='Example R1', brand='KTM'),
            fiche('super', model='Super Duke', brand='KTM'),
            fiche('lowtank', tank='14,99 litres', brand='Ducati'),
            fiche('five', gears='boîte à 5 rapports', brand='Ducati'),
            fiche('primary', secondary='Primaire par chaîne', brand='Ducati'),
            fiche('belt', secondary='Secondaire par courroie', brand='Ducati')]
    fake_sources(monkeypatch, rows)
    result = counts.try_source_count(None, SECOND)
    assert result['plan']['total'] == 4
    assert 'Street Triple RS' in result['answer'] and 'Example R1' in result['answer']
    assert result['plan']['unresolved_source_fiches'] == 1


def test_discs_are_counted_in_front_not_rear_and_strict_sort(monkeypatch):
    rows = [fiche('short', year=2000, wheelbase='1 300 mm', brand='Ducati'),
            fiche('long', year=2000, wheelbase='1 440 mm', brand='Aprilia'),
            fiche('boundary', year=2000, wheelbase='1 450 mm', brand='Ducati'),
            fiche('motor-boundary', year=2000, displacement='1 000 cc', brand='Ducati'),
            fiche('one-front', year=2000, front='1 disque Ø 300 mm', brand='Ducati')]
    rows[-1]['record']['spec_rows'].append(spec('Train arrière', 'Freinage', '2 disques'))
    fake_sources(monkeypatch, rows)
    result = counts.try_source_count(None, THIRD)
    assert result['plan']['total'] == 2
    assert [source['id'] for source in result['plan']['shown_sources']] == ['short', 'long']
    assert 'Tri par empattement croissant' in result['answer']


def test_adjustable_height_is_not_collapsed_to_low_setting(monkeypatch):
    rows = [fiche('fully-low'), fiche('crossing'), fiche('fully-high')]
    for row, limits in zip(rows, ('785 mm et 810 mm', '810 mm et 830 mm', '830 mm et 850 mm')):
        row['record']['spec_rows'][1] = spec('Châssis', '', 'Hauteur de selle réglable entre ' + limits)
    fake_sources(monkeypatch, rows)
    result = counts.try_source_count(None, FIRST)
    assert result['plan']['total'] == 1 and result['plan']['unresolved_source_fiches'] == 1
    assert '785 mm et 810 mm' in result['answer']
    assert 'toute la plage' in result['answer']


def test_conflicting_source_values_not_arbitrarily_selected(monkeypatch):
    row = fiche()
    row['record']['spec_rows'].append(spec('Châssis', 'Hauteur de selle', '840 mm'))
    row['record']['spec_rows'].append(spec('Équipement en option', 'Freinage', 'ABS'))
    assert 'seat_height_mm' not in counts.project_source(row['record'])
    assert 'abs_standard' not in counts.project_source(row['record'])
    fake_sources(monkeypatch, [row])
    result = counts.try_source_count(None, FIRST)
    assert result['plan']['total'] == 0 and result['plan']['unresolved_source_fiches'] == 1


def test_missing_or_wrong_section_never_becomes_source_fact(monkeypatch):
    row = fiche(abs='ABS')
    row['record']['spec_rows'][-1]['section'] = 'Moteur'
    row['record']['spec_rows'][1]['section'] = 'Train avant'
    fake_sources(monkeypatch, [row])
    result = counts.try_source_count(None, FIRST)
    assert result['plan']['total'] == 0 and result['plan']['unresolved_source_fiches'] == 1


def test_total_kept_when_display_limited_and_duplicate_id_counted_once(monkeypatch):
    rows = [fiche(str(index)) for index in range(25)]
    rows += [deepcopy(rows[0])]
    fake_sources(monkeypatch, rows)
    result = counts.try_source_count(None, FIRST)
    assert result['plan']['total'] == 25
    assert result['answer'].count('[Fiche](') == 20
    assert '20 sur 25' in result['answer']
    assert len(result['plan']['shown_sources']) == 20
    export = result['plan']['export']
    with Path(export['path']).open(encoding='utf-8-sig', newline='') as stream:
        full = list(csv.DictReader(stream))
    assert len(full) == 25 and len({row['id'] for row in full}) == 25
    assert set(row['source_url'] for row in full) == {'https://example.org/' + str(index) for index in range(25)}
    assert 'Liste complète sourcée — 25 fiches, CSV' in result['answer']
    assert export['url'].startswith('/gradio_api/file=data/technical/chat-exports/')
    assert Path(export['path']).name == hashlib.sha256(Path(export['path']).read_bytes()).hexdigest() + '.csv'
    assert json.loads(full[0]['abs_standard_preuves'])[0]['section'] == 'Équipement de série'


def test_punctuation_and_operator_synonyms_are_not_fixed_phrases():
    query = ('Affiche le nombre de modèles 2018–2024 ayant cylindrée entre 500 et 800 cc, '
             'hauteur de selle au plus 820 millimètres et ABS standard, sans Honda ni BMW ni Yamaha.')
    plan = counts.parse_source_count(query)
    assert 'blocked_reason' not in plan
    assert plan['exclude_brands'] == ['BMW', 'Honda', 'Yamaha']
    assert plan['conditions'] == counts.parse_source_count(FIRST)['conditions']


@pytest.mark.parametrize('natural, original', [(NATURAL_FIRST, FIRST), (NATURAL_SECOND, SECOND), (NATURAL_THIRD, THIRD)])
def test_free_forms_produce_same_complete_filters(natural, original):
    actual, expected = counts.parse_source_count(natural), counts.parse_source_count(original)
    assert 'blocked_reason' not in actual
    for key in ('min_year', 'max_year', 'include_brands', 'exclude_brands', 'exclude_variant_words', 'order_by'):
        assert actual[key] == expected[key]
    assert sorted(actual['conditions'], key=lambda c: (c['field'], c['op'])) == sorted(expected['conditions'], key=lambda c: (c['field'], c['op']))


@pytest.mark.parametrize('phrase, field, operator, value', [
    ('Écarte les réservoirs de 15 litres ou moins', 'tank_l', '>', 15),
    ('Exclue les empattements de 1450 mm et plus', 'wheelbase_mm', '<', 1450),
    ('hauteur de selle de 820 mm au maximum', 'seat_height_mm', '<=', 820),
    ('réservoir d’au moins quinze litres', 'tank_l', '>=', 15),
])
def test_closed_complement_and_postfix_operators(phrase, field, operator, value):
    plan = counts.parse_source_count('Compte les fiches de 2018 à 2024, transmission finale par chaîne, ' + phrase)
    assert 'blocked_reason' not in plan
    assert {'field': field, 'op': operator, 'value': value} in plan['conditions']


@pytest.mark.parametrize('suffix', [
    'Et les marques japonaises BMW et Honda',
    'et les marques Honda et Suzuki',
    'sans toutes les marques japonaises',
    'ou transmission finale par cardan',
    'et précise ABS standard faute de données',
])
def test_unproved_brand_or_reporting_qualifiers_not_silently_masked(monkeypatch, suffix):
    read = Mock()
    monkeypatch.setattr(counts, '_rows', read)
    result = counts.try_source_count(None, FIRST + ' ' + suffix)
    assert result['route'] == 'clarification'
    read.assert_not_called()


def test_numeric_exclusion_does_not_cross_sentence_to_exclude_brands(monkeypatch):
    question = ('Compte les fiches de 1990 à 2009, transmission finale par chaîne. '
                'Exclue les cylindrées de 1000 cc ou plus. Et les marques Honda et Yamaha.')
    read = Mock()
    monkeypatch.setattr(counts, '_rows', read)
    assert counts.try_source_count(None, question)['route'] == 'clarification'
    read.assert_not_called()


@pytest.mark.parametrize('value', [
    'boîte à 6 rapports , manuelle', 'boîte à 6 rapports , avec shifter',
    'boîte à 6 rapports , manuelle + shifter',
    'boîte à 6 rapports , manuelle - shifter de série',
    'boîte à 6 rapports , manuelle - shifter en option',
    'boîte à 6 rapports , manuelle / shifter en option',
])
def test_gear_count_accepts_compatible_annotations_and_keeps_whole_proof(value):
    row = fiche(gears=value)
    result = counts.project_source(row['record'])['gears']
    assert result.values == (6,)
    assert result.rows[0]['value'] == value


@pytest.mark.parametrize('value', [
    'boîte à 6 rapports ou 5 rapports', 'boîte à 6 rapports , manuelle / 5 rapports',
    'boîte à 6 rapports , manuelle / peut-être automatique',
    'boîte à 6 rapports , non défini', 'boîte à 6 rapports selon version',
])
def test_gear_count_refuses_alternative_or_unknown_suffix(value):
    assert 'gears' not in counts.project_source(fiche(gears=value)['record'])


def test_multiple_gear_counts_conflict_even_with_compatible_annotation():
    row = fiche(gears='boîte à 6 rapports , manuelle')
    row['record']['spec_rows'].append(spec('Transmission', '', 'boîte à 5 rapports , manuelle'))
    assert 'gears' not in counts.project_source(row['record'])


def test_abs_en_option_in_standard_section_is_not_counted_as_standard(monkeypatch):
    row = fiche(abs='ABS en option')
    assert counts.project_source(row['record'])['abs_standard'].values == (0,)
    fake_sources(monkeypatch, [row])
    result = counts.try_source_count(None, FIRST)
    assert result['plan']['total'] == 0
    with Path(result['plan']['export']['path']).open(encoding='utf-8-sig', newline='') as stream:
        assert list(csv.DictReader(stream)) == []


def test_csv_reused_by_content_and_contains_no_full_record(monkeypatch):
    row = fiche()
    row['record']['private_test_marker'] = 'DO_NOT_EXPORT_ENTIRE_RECORD'
    row['record']['spec_rows'].append(spec('Commentaires', '', 'DO_NOT_EXPORT_UNREQUESTED_ROW'))
    fake_sources(monkeypatch, [row])
    first = counts.try_source_count(None, FIRST)
    second = counts.try_source_count(None, FIRST)
    assert first['plan']['export'] == second['plan']['export']
    assert len(list(counts.EXPORT_DIRECTORY.glob('*.csv'))) == 1
    assert not list(counts.EXPORT_DIRECTORY.glob('*.tmp'))
    text = Path(first['plan']['export']['path']).read_text(encoding='utf-8-sig')
    assert 'DO_NOT_EXPORT' not in text
    assert 'current-sha-one' in text and 'https://example.org/one' in text


def test_csv_does_not_execute_source_name_as_spreadsheet_formula(monkeypatch):
    fake_sources(monkeypatch, [fiche(model='=HYPERLINK("example.org")')])
    result = counts.try_source_count(None, FIRST)
    with Path(result['plan']['export']['path']).open(encoding='utf-8-sig', newline='') as stream:
        record = next(csv.DictReader(stream))
    assert record['modele'].startswith("'=")

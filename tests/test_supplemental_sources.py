"""Supplemental facts keep exact identity, raw wording and independent source."""
import json

import pytest

from bikefinder_rag.catalog import supplemental_sources as sources


Z750 = {'brand': 'Kawasaki', 'model': 'Z 750', 'year': 2004}
RS660 = {'brand': 'Aprilia', 'model': 'RS 660', 'year': 2021}
GROUND = {**Z750, 'url': 'https://bikez.com/motorcycles/kawasaki_z_750_2004.php',
          'raw_specs': {'Model name': 'Kawasaki Z 750', 'Year of manufacture': '2004',
                        'Ground clearance': '165 mm (6.5 inches)'}}
COMMENT = ('Six-axis inertial platform, APRC package containing ATC (traction control),\r\n'
           'AWC (wheelie control), AEB (engine braking), AEM (engine maps) and ACC\r\n'
           '(cruise control). 5 Riding modes (Road and Track, 3 fixed and 2 customisable).')
CRUISE = {**RS660, 'url': 'https://bikez.com/motorcycles/aprilia_rs_660_2021.php',
          'raw_specs': {'Motorcycle name': 'Aprilia RS 660', 'Year model': '2021', 'Comments': COMMENT}}


def test_exact_ground_clearance_preserves_source_units_and_url():
    result = sources.extract_supplemental_rows(Z750, [GROUND], 'ground_clearance')
    assert len(result) == 1
    assert result[0]['label'] == 'Ground clearance'
    assert result[0]['value'] == '165 mm (6.5 inches)'
    assert result[0]['source_url'] == GROUND['url']
    assert result[0]['source_identity'] == Z750
    assert result[0]['source'] == 'bikez'


def test_acc_is_expanded_in_the_raw_row_but_fitment_remains_unknown():
    result = sources.extract_supplemental_rows(RS660, [CRUISE], 'cruise_control')
    assert len(result) == 1
    assert result[0]['label'] == 'Comments' and result[0]['value'] == COMMENT
    assert result[0]['equipment_status'] == 'unknown'
    assert result[0]['source_url'] == CRUISE['url']
    assert result[0]['source_identity'] == RS660
    assert 'série/option' in result[0]['qualifier']


@pytest.mark.parametrize('identity', [
    {**Z750, 'model': 'Z750 S'}, {**Z750, 'model': 'Z 750 R'},
    {**Z750, 'model': '750 ZR-7 N'}, {**Z750, 'year': 2005},
    {**Z750, 'brand': 'Suzuki'},
])
def test_near_name_or_year_is_not_a_bridge(identity):
    assert sources.extract_supplemental_rows(identity, [GROUND], 'ground_clearance') == []


@pytest.mark.parametrize('identity', [
    {**RS660, 'model': 'RS 660 35kW'}, {**RS660, 'model': 'RS 660 Trofeo'},
    {**RS660, 'model': 'Tuono 660'}, {**RS660, 'year': 2022},
])
def test_rs660_variants_are_never_folded_into_the_standard_model(identity):
    assert sources.extract_supplemental_rows(identity, [CRUISE], 'cruise_control') == []


def test_typography_is_normalized_without_fuzzy_identity():
    assert len(sources.extract_supplemental_rows({'brand': 'KAWASAKI', 'model': 'Z-750', 'year': 2004},
                                               [GROUND], 'ground_clearance')) == 1


@pytest.mark.parametrize('specs', [{}, {'Ground clearance': 'N/A'}, {'Ground clearance': 'unknown'},
                                  {'Trail': '165 mm'}, {'Seat height': '165 mm'}])
def test_unknown_or_other_dimension_is_not_ground_clearance(specs):
    assert sources.extract_supplemental_rows(Z750, [{**GROUND, 'raw_specs': specs}], 'ground_clearance') == []


@pytest.mark.parametrize('specs', [
    {'Comments': 'APRC: ATC, AWC, AEB, AEM and ACC.'},
    {'Comments': 'Adaptive chassis control (ACC).'}, {'Cruise control': 'unknown'},
    {'Ask questions': 'Join the cruise control discussion group.'},
    {'Motorcycle name': 'Aprilia RS 660 cruise control'},
])
def test_acc_alone_boilerplate_and_unknown_fitment_are_not_evidence(specs):
    assert sources.extract_supplemental_rows(RS660, [{**CRUISE, 'raw_specs': specs}], 'cruise_control') == []


def test_named_label_is_raw_evidence_without_a_standard_status_inference():
    result = sources.extract_supplemental_rows(RS660, [{**CRUISE, 'raw_specs': {'Cruise control': 'Yes'}}], 'cruise_control')
    assert result[0]['value'] == 'Yes' and result[0]['equipment_status'] == 'unknown'


@pytest.mark.parametrize(('identity', 'base', 'field', 'label', 'different_value'), [
    (Z750, GROUND, 'ground_clearance', 'Ground clearance', '170 mm (6.7 inches)'),
    (RS660, CRUISE, 'cruise_control', 'Comments', 'Cruise control not available.'),
])
def test_conflicting_raw_values_are_not_arbitrarily_selected(identity, base, field, label, different_value):
    other = {**base, 'url': base['url'].replace('.php', '_duplicate.php'), 'raw_specs': {label: different_value}}
    assert sources.extract_supplemental_rows(identity, [base, other], field) == []


def test_identical_source_duplicates_are_deduplicated_and_missing_is_not_conflicting():
    result = sources.extract_supplemental_rows(Z750, [GROUND, GROUND, {**GROUND, 'raw_specs': {}}], 'ground_clearance')
    assert len(result) == 1


@pytest.mark.parametrize('change', [
    {'url': 'https://bikez.com.evil.test/motorcycles/kawasaki_z_750_2004.php'},
    {'url': 'https://bikez.com/models/kawasaki_z_750_2004.php'},
    {'url': 'https://bikez.com/motorcycles/kawasaki_z_750_2005.php'},
    {'raw_specs': {'Ground clearance': '165 mm', 'Model name': 'Kawasaki Z 750 S'}},
    {'raw_specs': {'Ground clearance': '165 mm', 'Year model': '2005'}},
    {'raw_specs': 'not JSON'},
])
def test_provenance_or_raw_identity_mismatch_is_rejected(change):
    assert sources.extract_supplemental_rows(Z750, [{**GROUND, **change}], 'ground_clearance') == []


@pytest.mark.parametrize('identity', [None, {}, {**Z750, 'year': '2004'}, {**Z750, 'year': True}, {**Z750, 'model': ''}])
def test_incomplete_identity_never_expands_to_a_family(identity):
    assert sources.extract_supplemental_rows(identity, [GROUND], 'ground_clearance') == []


@pytest.mark.parametrize('field', ['power', 'equipment', [], None])
def test_scope_is_limited_to_two_characteristics(field):
    with pytest.raises(ValueError):
        sources.extract_supplemental_rows(Z750, [GROUND], field)


def test_stored_json_and_bound_year_read_wrapper(monkeypatch):
    captured = []
    def rows(conn, sql, params):
        captured.append((sql, params))
        return [{**GROUND, 'raw_specs': json.dumps(GROUND['raw_specs'])}]
    monkeypatch.setattr(sources, '_rows', rows)
    result = sources.get_supplemental_rows(None, Z750, 'ground_clearance')
    assert result[0]['value'] == '165 mm (6.5 inches)'
    assert captured == [('SELECT brand,model,year,url,raw_specs FROM motorcycles WHERE year=%s', [2004])]

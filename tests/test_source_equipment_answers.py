from copy import deepcopy

import pytest

from bikefinder_rag.catalog.source_equipment_answers import abs_source_answer, source_equipment_answer


def record(value, section='Équipement de série', label='Assistance au freinage'):
    return {'spec_rows': [{'section': section, 'label': label, 'value': value}]}


def test_dotted_abs_disconnectable_keeps_presence_and_qualification():
    result = abs_source_answer(record('A.B.S. disconnectable'))
    assert 'présence documentée' in result and 'de série selon' in result
    assert 'A.B.S. disconnectable' in result and 'Assistance au freinage' in result
    assert 'inconnu' not in result and 'absence' not in result


def test_bare_abs_has_no_invented_inclusion_outside_series_section():
    result = abs_source_answer(record('ABS déconnectable', section='Assistance'))
    assert 'présence documentée' in result and 'statut série / option non précisé' in result
    assert 'de série selon' not in result


@pytest.mark.parametrize('value', ['ABS non déconnectable', 'A.B.S. désactivable', 'ABS en curvas'])
def test_feature_qualifier_is_not_equipment_absence(value):
    result = abs_source_answer(record(value))
    assert 'présence documentée' in result and 'absence explicitement' not in result


@pytest.mark.parametrize('value', ['ABS de série', 'ABS standard', 'ABS d’origine'])
def test_explicit_standard_status_without_standard_heading(value):
    assert 'de série selon' in abs_source_answer(record(value, section='Assistance'))


@pytest.mark.parametrize('value', ['ABS en option', 'A.B.S. optionnel'])
def test_inline_option_never_becomes_series_from_heading(value):
    result = abs_source_answer(record(value))
    assert 'en option selon' in result and 'de série selon' not in result


def test_option_heading_with_bare_abs_is_explicit_optional():
    assert 'en option selon' in abs_source_answer(record('ABS', section='Équipement en option'))


@pytest.mark.parametrize('value', ['sans ABS', 'pas d’ABS', 'ABS absent', 'ABS non disponible', 'non équipé d’ABS'])
def test_explicit_absence_not_invented_presence(value):
    result = abs_source_answer(record(value))
    assert 'absence explicitement documentée' in result
    assert 'présence documentée' not in result


def test_abs_label_with_negative_value_is_absence():
    assert 'absence explicitement' in abs_source_answer(record('Non', label='ABS'))


@pytest.mark.parametrize('rows', [
    [record('ABS')['spec_rows'][0], record('ABS en option')['spec_rows'][0]],
    [record('sans ABS')['spec_rows'][0], record('ABS', section='Assistance')['spec_rows'][0]],
    [record('ABS de série ou en option')['spec_rows'][0]],
])
def test_conflicting_rows_or_statuses_are_not_arbitrarily_resolved(rows):
    result = abs_source_answer({'spec_rows': rows})
    assert 'mentions contradictoires' in result and 'statut non tranchés' in result
    for row in rows:
        assert row['value'] in result


@pytest.mark.parametrize('value', ['ABS de série ; shifter en option', 'ABS de série, shifter en option'])
def test_shifter_option_is_not_borrowed_for_abs_status(value):
    result = abs_source_answer(record(value))
    assert 'de série selon' in result and 'mentions contradictoires' not in result
    assert value in result


@pytest.mark.parametrize('raw', [
    {'spec_rows': []}, record('non communiqué'),
    record('absorption variable'), record('ABS', section='Moteur', label='Modèle'),
    record('version ABS', section='Tarifs', label='France'),
])
def test_no_relevant_literal_equipment_proof_defers(raw):
    assert abs_source_answer(raw) is None


def test_helper_is_pure_deduplicates_proofs_and_accepts_catalogue_row():
    raw = record('A.B.S. disconnectable')
    raw['spec_rows'] += deepcopy(raw['spec_rows'])
    before = deepcopy(raw)
    result = abs_source_answer({'record': raw})
    assert raw == before and result.count('A.B.S. disconnectable') == 1
    assert result == source_equipment_answer(raw, 'A.B.S.')
    assert source_equipment_answer(raw, 'DCT') is None


@pytest.mark.parametrize('value', ['', 'NC', 'N.C.', 'non communiqué', '-', 'inconnu', 'ABS non documenté'])
def test_abs_attribute_heading_with_unknown_value_does_not_prove_presence(value):
    assert abs_source_answer(record(value, label='ABS')) is None


@pytest.mark.parametrize('section', ['Électronique', 'Châssis', 'Autres caractéristiques'])
def test_explicit_abs_standard_statement_is_not_ignored_in_other_section(section):
    result = abs_source_answer(record('ABS de série', section=section, label='Conduite'))
    assert 'de série selon' in result and section in result


def test_qualified_abs_label_in_other_section_is_also_explicit():
    assert 'de série selon' in abs_source_answer(record('De série', section='Châssis', label='ABS'))

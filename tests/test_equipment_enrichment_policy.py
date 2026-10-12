import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from equipment_enrichment_policy import decision_flags, literal_engine_fitment, source_flags


def case(text, equipment='ABS', section='Équipement de série'):
    return {'equipment': equipment, 'passages': [{'text': text, 'section': section}]}


@pytest.mark.parametrize('equipment', ['ABS', 'CBS', 'TCS'])
def test_optional_group_requires_review_even_when_model_is_certain(equipment):
    c = case('Dual CBS - ABS - TCS en option', equipment)
    assert 'ambiguous_optional_group' in source_flags(c)
    assert 'ambiguous_optional_group' in decision_flags(c, {'status': 'optional', 'confidence': 1}, 'jev')


def test_separate_clauses_do_not_make_cbs_optional():
    c = case('CBS de série - ABS en option', 'CBS')
    assert decision_flags(c, {'status': 'standard', 'confidence': 1}, 'jev') == []
    assert 'option_without_literal_proof' in decision_flags(c, {'status': 'optional'}, 'mistral')
    c['equipment'] = 'ABS'
    assert decision_flags(c, {'status': 'optional', 'confidence': 1}, 'jev') == []


def test_local_fallback_cannot_override_source_uncertainty():
    assert 'ambiguous_optional_group' in decision_flags(case('ABS/CBS en option'), {'status': 'standard'}, 'mistral')


def test_absence_needs_literal_proof_for_both_models():
    c = case('ABS déconnectable sur demande')
    assert decision_flags(c, {'status': 'standard'}, 'mistral') == []
    assert 'absence_without_literal_proof' in decision_flags(c, {'status': 'explicitly_absent'}, 'mistral')


def test_optional_heading_is_overridden_and_source_typo_is_not_corrected():
    assert 'optional_conflict' in decision_flags(case('ABS en option'), {'status': 'standard'}, 'mistral')
    assert 'no_technical_mention' in source_flags(case('ASB en option'))


def test_price_only_and_generic_scope_stay_unresolved():
    assert 'no_technical_mention' in source_flags(case('France — avec ABS : 9000 €', section='Tarifs'))
    assert 'generic_equipment_scope' in source_flags(case('Freinage : combiné', equipment='Freinage'))


def test_source_truncation_and_true_explicit_absence_are_distinguished():
    c = case("Injection Ride by Wire avec sélectio", 'ride by wire', 'Moteur')
    assert literal_engine_fitment(c) == 'standard'
    assert 'truncated_source' not in source_flags(c)
    assert literal_engine_fitment(case('Injection Ride by Wir avec sélectio', 'ride by wire', 'Moteur')) is None
    assert literal_engine_fitment(case('Injection Ride by Wire en option', 'ride by wire', 'Moteur')) is None
    assert decision_flags(case('sans ABS'), {'status': 'explicitly_absent'}, 'mistral') == []


def test_seat_height_context_does_not_conflict_with_equipment_listing():
    c = case('Selle réglable', 'Selle réglable')
    c['passages'].append({'section': 'Châssis', 'text': 'Hauteur de selle réglable entre 810 mm et 830 mm'})
    assert decision_flags(c, {'status': 'standard', 'confidence': 1}, 'jev') == []


def test_source_alias_and_explicit_option_heading_are_preserved():
    assert source_flags(case('Reverse gear', 'marche arrière', 'Transmission')) == []
    assert decision_flags(case('Bluetooth', 'Bluetooth', 'Équipement en option'), {'status': 'optional'}, 'mistral') == []


def test_contradictory_target_clauses_cannot_be_accepted_by_a_model():
    assert 'contradictory_fitment' in source_flags(case('ABS de série ; ABS en option selon version'))


def test_unqualified_engine_mention_does_not_prove_standard_fitment():
    assert 'standard_without_fitment_proof' in decision_flags(case('ABS calibration', section='Moteur'), {'status': 'standard'}, 'mistral')

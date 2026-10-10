"""Proof controls for the isolated classification benchmark."""
import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('hybrid_eval', Path(__file__).parents[1] / 'scripts/evaluate_hybrid_poc.py')
eval_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(eval_module)


def case(text, section='Équipement de série', equipment='ABS'):
    return {'equipment': equipment, 'passages': [{'section': section, 'text': text}]}


def test_high_confidence_does_not_override_optional_text():
    assert 'option_conflict' in eval_module.checks(case('ABS en option'), {'status': 'standard', 'confidence': 1})


def test_silence_never_becomes_explicit_absence():
    data = case('Deux disques Ø 320 mm', 'Train avant')
    assert eval_module.rules_decision(data) == 'unknown'
    assert 'no_evidence' in eval_module.checks(data, {'status': 'explicitly_absent', 'confidence': 1})


def test_abs_is_not_matched_inside_another_word():
    assert not eval_module.has_mention(case('Réservoir absent', 'Châssis'))


def test_equipped_price_cannot_establish_fitment_status():
    data = case('France — avec ABS : 9499 euros', 'Tarifs')
    assert eval_module.rules_decision(data) == 'unknown'
    assert 'price_only' in eval_module.checks(data, {'status': 'standard', 'confidence': 1})


def test_conflicting_explicit_qualifiers_require_review():
    data = case('ABS de série ; ABS en option selon version')
    assert eval_module.rules_decision(data) == 'unknown'


def test_source_identity_does_not_change_semantic_cache_key():
    a = case('ABS en option')
    b = dict(a, identity={'brand': 'Honda', 'year': 2000})
    assert eval_module.input_hash(a) == eval_module.input_hash(b)


def test_parser_equipment_aliases_remain_valid_evidence():
    assert eval_module.has_mention(case('Centrale inertielle', equipment='IMU'))
    assert eval_module.has_mention(case('Surveillance de la pression des pneus', equipment='TPMS'))
    assert eval_module.has_mention(case('Reverse gear', 'Transmission', equipment='marche arrière'))


def test_changed_prompt_cannot_reuse_classification_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_module, 'OUT', tmp_path)
    eval_module.ensure_cache_protocol('jev')
    monkeypatch.setattr(eval_module, 'INSTRUCTION', 'A different interpretation policy')
    with pytest.raises(ValueError, match='different model or prompt'):
        eval_module.ensure_cache_protocol('jev')


def test_existing_untracked_cache_requires_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_module, 'OUT', tmp_path)
    (tmp_path / 'jev-classifications.json').write_text(json.dumps([{'status': 'standard'}]))
    with pytest.raises(ValueError, match='no frozen prompt provenance'):
        eval_module.ensure_cache_protocol('jev')

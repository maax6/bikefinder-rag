from scripts.eval_constraints import classify_matches


def test_missing_spec_is_not_a_satisfied_constraint():
    result = classify_matches([{"weight_kg": None}], {"max_weight_kg": 130})
    assert result["status"] == "unverifiable"
    assert result["missing_fields"] == ["weight_kg"]


def test_unknown_variant_does_not_vindicate_a_known_violation():
    result = classify_matches([{"weight_kg": 180}, {"weight_kg": None}], {"max_weight_kg": 130})
    assert result["status"] == "unverifiable"


def test_one_fully_compliant_variant_is_enough():
    result = classify_matches([{"weight_kg": 180}, {"weight_kg": 120}], {"max_weight_kg": 130})
    assert result["status"] == "satisfied"


def test_known_violation_remains_violated_even_with_another_unknown_field():
    result = classify_matches([{"weight_kg": 180, "displacement_ccm": None}],
                              {"max_weight_kg": 130, "max_displacement_ccm": 600})
    assert result["status"] == "violated"


def test_missing_category_is_unverifiable_not_false_failure():
    assert classify_matches([{"category": None}], {"category": "naked"})["status"] == "unverifiable"

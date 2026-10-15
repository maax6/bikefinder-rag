"""A net gain must not hide a newly incomplete or partially degraded question."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def confirmation(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("fusion_confirmation", scripts / "validate_bge_fusion.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inputs():
    cohort = dict(net_complete_gain=5, cases_with_lost_required_groups=[], first_hit_wins=1,
                  first_hit_losses=0, one_sided_paired_exact_p=.03125)
    paired = {key: dict(cohort) for key in ["fresh", "regression"]}
    summaries = {key: [dict(median_seconds=.04), dict(median_seconds=.042)] for key in paired}
    return paired, summaries, {"sources": True, "deterministic": True}


def test_aggregate_gain_cannot_hide_lost_evidence_in_one_old_case(confirmation):
    paired, summaries, integrity = inputs()
    assert confirmation.promotion(paired, summaries, integrity)["eligible_for_chat_integration"]
    paired["regression"]["cases_with_lost_required_groups"] = ["old"]
    decision = confirmation.promotion(paired, summaries, integrity)
    assert not decision["eligible_for_chat_integration"]
    assert "no_required_group_loss" in decision["failed_checks"]


def test_partially_incomplete_question_still_counts_a_lost_required_group(confirmation):
    case = dict(id="q", question="Compare three sources", required_groups=[["a"], ["b"], ["c"]],
                gold_passages=[dict(id=i, grade=2) for i in "abc"])
    rows = {("q", "current_rrf40"): dict(ranking=[dict(id=i) for i in ["a", "b", "x"]]),
            ("q", "weighted_rrf80"): dict(ranking=[dict(id=i) for i in ["a", "x", "y"]])}
    result = confirmation.paired_analysis([case], rows)
    assert result["net_complete_gain"] == 0
    assert result["cases_with_lost_required_groups"] == ["q"]
    assert result["details"][0]["lost_required_groups"] == [["b"]]


@pytest.mark.parametrize("failure", ["too_small", "first_hit", "latency", "integrity"])
def test_promotion_requires_more_than_positive_completeness(confirmation, failure):
    paired, summaries, integrity = inputs()
    if failure == "too_small":
        paired["fresh"].update(net_complete_gain=1, one_sided_paired_exact_p=.5)
    elif failure == "first_hit":
        paired["fresh"]["first_hit_losses"] = 2
    elif failure == "latency":
        summaries["fresh"][1]["median_seconds"] = .080
    else:
        integrity["sources"] = False
    assert not confirmation.promotion(paired, summaries, integrity)["eligible_for_chat_integration"]


def test_explicit_unknown_colour_is_partial_source_evidence_not_known_colour(confirmation):
    fiche = [dict(id="a", object_id="o", brand="B", model="M", year=2024,
                  section="Coloris", original_text="Coloris : non défini", source_url="https://example.com",
                  source_sha256="source")]
    case = confirmation.make_case("q", "Quelles teintes ?", [fiche], ["colours"], "single_section")
    assert case["answerability"] == "partial"
    assert case["required_groups"] == [["a"]]
    assert any("unknown" in limit for limit in case["expected_limits"])

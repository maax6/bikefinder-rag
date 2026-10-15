"""The authorized total ceiling includes output and uncertain API requests."""
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("mistral_jev_comparison", Path(__file__).resolve().parents[1] / "scripts/compare_mistral_jev.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_output_reservation_blocks_request_before_network():
    budget = module.Spending(.5, lambda: None)
    with pytest.raises(RuntimeError, match="not sent"):
        budget.reserve("model", {}, 0, .001, 501)
    assert budget.records == []


def test_missing_usage_retains_whole_reservation_and_valid_cost_releases_it():
    budget = module.Spending(.5, lambda: None)
    record = budget.reserve("model", {}, 1e-6, .001, 100)
    initial = budget.debit
    budget.settle(record, {})
    assert budget.debit == initial
    budget.settle(record, {"usage": {"cost": .01}})
    assert budget.debit == .01


def test_cost_exceeding_reservation_stops_instead_of_hiding_it():
    budget = module.Spending(.5, lambda: None)
    record = budget.reserve("model", {}, 1e-6, 0, 0)
    with pytest.raises(RuntimeError, match="stop all further"):
        budget.settle(record, {"usage": {"cost": .4}})
    assert budget.debit == .4
    assert record["status"] == "reservation_violation"
    with pytest.raises(RuntimeError, match="stopped all further"):
        budget.reserve("model", {}, 0, 0, 0)

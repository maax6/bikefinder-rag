"""Transport-level input spending bounds, independent of answer success."""
from copy import deepcopy

import pytest
import requests

from scripts.screen_sql_rag_models import BudgetedOpenRouterAdapter, InputBudget, input_rate_ceiling, least_supported_effort


PRICES = {"prompt": "0.0000001", "completion": "0.0000005",
          "input_cache_read": "0.00000001", "input_cache_write": "0.000000125",
          "input_cache_write_1h": "0.0000002",
          "overrides": [{"min_prompt_tokens": 100000, "prompt": "0.0000005",
                         "completion": "0.0000025", "input_cache_write_1h": "0.000001"}]}


class Response:
    def __init__(self, value, status=200):
        self.value, self.status_code = value, status

    def json(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class Transport:
    def __init__(self, reply):
        self.reply, self.sent = reply, []

    def post(self, url, **kwargs):
        self.sent.append((url, deepcopy(kwargs)))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def raw(usage=None):
    return {"id": "generation-test", "model": "openai/gpt-6-luna", "provider": "example",
            "usage": usage or {}, "choices": [{"message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}]}


def adapter(reply, *, maximum=2, prices=PRICES, on_update=None):
    budget = InputBudget(maximum, on_update=on_update)
    transport = Transport(reply)
    instance = BudgetedOpenRouterAdapter("openai/gpt-6-luna", key="test", session=transport,
                                         pricing=prices, budget=budget)
    return instance, budget, transport


def post(instance, payload=None):
    return instance._post("https://openrouter.ai/api/v1/chat/completions",
                          payload or {"messages": [{"role": "user", "content": "Question à moto"}]},
                          {"Authorization": "Bearer test"}, 3)


def test_budget_blocks_before_any_http_request():
    instance, budget, transport = adapter(Response(raw()), maximum=0.000001)
    with pytest.raises(RuntimeError, match="request not sent"):
        post(instance)
    assert not transport.sent
    assert budget.debit == 0
    assert budget.blocked_requests == 1


def test_reserves_all_unicode_history_and_schemas_then_uses_actual_tokens_with_cache_ceiling():
    usage = {"prompt_tokens": 100, "completion_tokens": 12, "cost": .000017,
             "prompt_tokens_details": {"cached_tokens": 50, "cache_write_tokens": 10},
             "cost_details": {"upstream_inference_prompt_cost": .000011,
                              "upstream_inference_completions_cost": .000006}}
    instance, budget, transport = adapter(Response(raw(usage)))
    instance.complete([{"role": "system", "content": "Règles"}, {"role": "user", "content": "Quel modèle ?"}], 3)
    record = budget.records[0]
    assert record["payload_utf8_bytes"] > 1000  # Whole seven-function wire contract.
    assert record["prompt_token_upper_bound"] == 2 * record["payload_utf8_bytes"] + 4096
    assert record["known_input_at_list_usd"] == pytest.approx(100e-7)
    assert record["input_debit_usd"] == pytest.approx(100 * 1e-6)  # Worst declared tier plus cache write multiplier.
    assert record["output_cost_at_list_usd"] == pytest.approx(12 * 5e-7)
    assert record["reported_total_cost_usd"] == .000017
    assert record["provider_reported_input_cost_usd"] == .000011
    assert record["raw_usage"] == usage
    assert record["uncertain"] is False
    assert transport.sent[0][1]["json"]["provider"]["max_price"] == {"prompt": .5, "completion": 2.5, "request": 0}
    assert "Authorization" not in str(record)


def test_timeout_keeps_reservation_and_blocks_next_request():
    # Minimal payload: about 4,300 ceiling tokens at the ordinary 1e-7 rate.
    prices = {"prompt": "0.0000001", "completion": "0.0000005"}
    instance, budget, transport = adapter(requests.Timeout(), maximum=.0012, prices=prices)
    with pytest.raises(requests.Timeout):
        post(instance)
    reserved = budget.records[0]["input_reservation_usd"]
    assert budget.debit == reserved > 0
    assert budget.summary()["uncertain_requests"] == 1
    with pytest.raises(RuntimeError, match="request not sent"):
        post(instance)
    assert len(transport.sent) == 1


def test_missing_input_usage_preserves_reservation_and_actual_combined_cost():
    instance, budget, _ = adapter(Response(raw({"completion_tokens": 10, "cost": .00001})))
    post(instance)
    record = budget.records[0]
    assert record["status"] == "response_without_input_usage"
    assert record["input_debit_usd"] == record["input_reservation_usd"]
    assert record["uncertain"] is True
    assert budget.summary()["actual_reported_total_cost_usd"] == .00001


@pytest.mark.parametrize("status,unbilled", [(401, True), (403, True), (404, False), (500, False)])
def test_auth_rejection_releases_but_uncertain_upstream_failure_keeps_reserve(status, unbilled):
    instance, budget, _ = adapter(Response({"ignored": "sensitive provider error body"}, status=status))
    with pytest.raises(RuntimeError, match=f"HTTP {status}") as error:
        post(instance)
    assert "sensitive" not in str(error.value)
    assert budget.records[0]["uncertain"] is not unbilled
    assert (budget.debit == 0) is unbilled


def test_output_cost_is_recorded_without_consuming_input_only_budget():
    prices = {"prompt": "0.0000001", "completion": "0.00001"}
    instance, budget, _ = adapter(Response(raw({"prompt_tokens": 100, "completion_tokens": 1200, "cost": .01201})),
                                   prices=prices, maximum=.0012)
    post(instance)
    assert budget.debit == pytest.approx(.00002)
    assert budget.summary()["output_cost_at_list_usd"] == pytest.approx(.012)
    assert budget.summary()["actual_reported_total_cost_usd"] > budget.maximum
    assert budget.exhausted is False


def test_pending_reserve_is_checkpointed_before_transport_settles():
    states = []
    instance, budget, _ = adapter(Response(raw({"prompt_tokens": 100})))
    budget.on_update = lambda: states.append(deepcopy(budget.records))
    post(instance)
    assert states[0][0]["status"] == "pending"
    assert states[0][0]["input_debit_usd"] == states[0][0]["input_reservation_usd"]
    assert states[-1][0]["status"] == "response_received"


def test_long_prompt_tier_and_cache_write_prices_are_included():
    assert input_rate_ceiling(PRICES, 99999) == 2e-7
    assert input_rate_ceiling(PRICES, 100000) == 1e-6
    instance, budget, _ = adapter(Response(raw({"prompt_tokens": 100000})))
    post(instance, {"messages": [{"role": "user", "content": "x" * 60000}]})
    assert budget.debit == pytest.approx(.1)
    assert budget.records[0]["known_input_at_list_usd"] == pytest.approx(.05)


@pytest.mark.parametrize("invalid", [None, -1, float("nan"), float("inf"), True, 1.5])
def test_invalid_token_usage_keeps_reserve(invalid):
    instance, budget, _ = adapter(Response(raw({"prompt_tokens": invalid})))
    post(instance)
    assert budget.records[0]["uncertain"] is True
    assert budget.debit == budget.records[0]["input_reservation_usd"]


def test_unexpected_token_count_stops_further_paid_work_flag():
    instance, budget, _ = adapter(Response(raw({"prompt_tokens": 99999})))
    post(instance)
    assert budget.reservation_violation is True
    assert budget.records[0]["reservation_violation"] is True


def test_successful_input_usage_can_be_counted_when_actual_combined_bill_missing():
    instance, budget, _ = adapter(Response(raw({"prompt_tokens": 100, "completion_tokens": 50})))
    post(instance)
    assert budget.records[0]["uncertain"] is False
    assert budget.summary()["reported_total_costs_missing"] == 1


def test_invalid_json_preserves_unknown_inference_charge():
    instance, budget, _ = adapter(Response(ValueError("provider-secret")))
    with pytest.raises(RuntimeError, match="invalid JSON") as error:
        post(instance)
    assert "provider-secret" not in str(error.value)
    assert budget.debit == budget.records[0]["input_reservation_usd"]


def test_mandatory_reasoning_uses_supported_minimum_while_optional_remains_disabled():
    assert least_supported_effort({"reasoning": {"mandatory": True, "supported_efforts": ["high", "medium", "low"]}}) == "low"
    assert least_supported_effort({"reasoning": {"mandatory": True, "supported_efforts": ["high", "minimal", "low"]}}) == "minimal"
    assert least_supported_effort({"reasoning": {"mandatory": False, "supported_efforts": ["high", "low"]}}) == "none"
    assert least_supported_effort({}) == "none"
    with pytest.raises(ValueError, match="Mandatory"):
        least_supported_effort({"reasoning": {"mandatory": True}})


def test_prior_unknown_request_keeps_reserve_under_same_global_cap():
    instance, old_budget, _ = adapter(requests.Timeout(), prices={"prompt": "0.0000001", "completion": "0.0000005"})
    with pytest.raises(requests.Timeout):
        post(instance)
    old_records = deepcopy(old_budget.records)
    next_budget = InputBudget(old_budget.debit + .00001, prior_records=old_records)
    next_transport = Transport(Response(raw({"prompt_tokens": 100})))
    next_adapter = BudgetedOpenRouterAdapter("openai/gpt-6-luna", key="test", session=next_transport,
                                             pricing=PRICES, budget=next_budget)
    with pytest.raises(RuntimeError, match="request not sent"):
        post(next_adapter)
    assert not next_transport.sent
    assert next_budget.debit == old_budget.debit
    assert next_budget.summary("prior_run")["uncertain_requests"] == 1
    assert next_budget.summary("current_run")["requests_started"] == 0
    assert old_records[0]["phase"] == "current_run"  # Input fixture is immutable.


def test_carry_keeps_phase_costs_distinct_and_reindexes_new_requests():
    instance, old_budget, _ = adapter(Response(raw({"prompt_tokens": 100, "cost": .00003})))
    post(instance)
    next_budget = InputBudget(2, prior_records=old_budget.records)
    next_adapter = BudgetedOpenRouterAdapter("openai/gpt-6-luna", key="test", session=Transport(Response(raw({"prompt_tokens": 200, "cost": .00005}))),
                                             pricing=PRICES, budget=next_budget)
    post(next_adapter)
    assert [r["request_index"] for r in next_budget.records] == [1, 2]
    assert [r["phase"] for r in next_budget.records] == ["prior_run", "current_run"]
    assert next_budget.summary("prior_run")["actual_reported_total_cost_usd"] == .00003
    assert next_budget.summary("current_run")["actual_reported_total_cost_usd"] == .00005
    assert next_budget.summary()["actual_reported_total_cost_usd"] == .00008


def test_error_metadata_helps_diagnosis_without_retaining_provider_body_or_secret():
    instance, budget, _ = adapter(Response({"error": {"code": 429, "message": "Limit exceeded Bearer test sk-or-v1-secret", "metadata": {"secret": "test"}}}, status=429))
    with pytest.raises(RuntimeError):
        post(instance)
    error = budget.records[0]["error_metadata"]
    assert error["code"] == "429"
    assert "Limit exceeded" in error["message"]
    assert "sk-or" not in error["message"]
    assert "test" not in error["message"]
    assert "metadata" not in error


def test_keyboard_interrupt_leaves_pending_request_reserved_for_next_run():
    class InterruptedTransport:
        def post(self, *args, **kwargs):
            raise KeyboardInterrupt

    budget = InputBudget(2)
    instance = BudgetedOpenRouterAdapter("openai/gpt-6-luna", key="test", session=InterruptedTransport(), pricing=PRICES, budget=budget)
    with pytest.raises(KeyboardInterrupt):
        post(instance)
    assert budget.records[0]["status"] == "pending"
    assert budget.records[0]["input_debit_usd"] == budget.records[0]["input_reservation_usd"]
    assert budget.records[0]["uncertain"] is True

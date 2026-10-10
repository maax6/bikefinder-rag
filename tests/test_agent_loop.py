"""Ollama transport checks with isolated config imports and mocked HTTP."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests


LOOP_PATH = Path(__file__).resolve().parents[1] / "src/bikefinder_rag/agent/loop.py"


def load_loop(monkeypatch, timeout=None, budget="6000"):
    if timeout is None:
        monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", timeout)
    if budget is None:
        monkeypatch.delenv("OLLAMA_TURN_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("OLLAMA_TURN_TIMEOUT_SECONDS", budget)
    # Avoid reloading the shared module or reading the repository's .env.
    spec = importlib.util.spec_from_file_location("isolated_agent_loop", LOOP_PATH)
    loop = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loop)
    return loop


@pytest.mark.parametrize("configured,expected", [(None, 300), ("600", 600), ("0.5", 0.5)])
def test_ollama_success_uses_default_or_configured_timeout(monkeypatch, configured, expected):
    loop = load_loop(monkeypatch, configured)
    response = Mock()
    response.json.return_value = {"message": {"role": "assistant", "content": "A local answer"}}
    post = Mock(return_value=response)
    monkeypatch.setattr(loop.requests, "post", post)

    answer, history = loop._run_agent_ollama(None, "Question", None)

    assert answer == "A local answer"
    assert history[-1] == {"role": "assistant", "content": answer}
    assert post.call_args.kwargs["timeout"] == expected
    assert post.call_args.kwargs["json"]["options"] == {"temperature": 0, "num_ctx": 16384}


@pytest.mark.parametrize("configured", ["0", "-1", "invalid", "nan", "inf"])
def test_ollama_timeout_rejects_invalid_configuration(monkeypatch, configured):
    with pytest.raises(ValueError, match="OLLAMA_TIMEOUT_SECONDS must be a positive finite number"):
        load_loop(monkeypatch, configured)


def test_ollama_read_timeout_reports_slow_generation_without_a_final_answer(monkeypatch):
    loop = load_loop(monkeypatch, "420")
    response = Mock()
    response.json.return_value = {"message": {
        "role": "assistant", "content": "", "tool_calls": [{
            "function": {"name": "filter_specs", "arguments": {"min_year": 1950, "max_year": 1959}},
        }],
    }}
    post = Mock(side_effect=[response, requests.ReadTimeout()])
    monkeypatch.setattr(loop.requests, "post", post)
    monkeypatch.setattr(loop, "execute_tool", Mock(return_value=[{"model": "A motorcycle", "year": 1955}]))

    answer, history = loop._run_agent_ollama(None, "Motos des années 1950 ?", None)

    assert "420-second read timeout" in answer
    assert "generation may be too slow" in answer
    assert "OLLAMA_TIMEOUT_SECONDS" in answer
    assert "is it running" not in answer
    assert history[-1]["role"] == "tool"
    assert post.call_count == 2


def test_ollama_connection_failure_keeps_the_unreachable_server_message(monkeypatch):
    loop = load_loop(monkeypatch)
    monkeypatch.setattr(loop.requests, "post", Mock(side_effect=requests.ConnectionError()))

    answer, history = loop._run_agent_ollama(None, "Question", None)

    assert "Could not reach the local Ollama server (ConnectionError)" in answer
    assert history == [{"role": "user", "content": "Question"}]


class Clock:
    seconds = 1000.0

    def monotonic(self):
        return self.seconds

    def advance(self, seconds):
        self.seconds += seconds


def simulated_http(monkeypatch, loop, messages, seconds_per_request):
    clock = Clock()
    monkeypatch.setattr(loop.time, "monotonic", clock.monotonic)
    responses = iter(messages)
    calls = []

    def post(url, *, json, timeout):
        spent = min(seconds_per_request, timeout)
        clock.advance(spent)
        calls.append(timeout)
        if timeout < seconds_per_request:
            raise requests.ReadTimeout()
        response = Mock()
        response.json.return_value = {"message": next(responses)}
        return response

    monkeypatch.setattr(loop.requests, "post", post)
    return clock, calls


def tool_message(*names):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": name, "arguments": {}}} for name in names
    ]}


def test_successive_requests_share_one_turn_budget(monkeypatch):
    loop = load_loop(monkeypatch, "300", "300")
    clock, calls = simulated_http(monkeypatch, loop, [
        tool_message("filter_specs"), tool_message("get_bike_details"),
        {"role": "assistant", "content": "Final fixture answer"},
    ], seconds_per_request=110)
    tools = Mock(return_value=[{"model": "Fixture bike"}])
    monkeypatch.setattr(loop, "execute_tool", tools)

    answer, history = loop._run_agent_ollama(None, "Quelles motos de 2000 avaient l'ABS ?", None)

    assert clock.seconds - 1000 == 300
    assert calls == [300, 190, 80]
    assert tools.call_count == 2
    assert "300-second budget" in answer
    assert "OLLAMA_TURN_TIMEOUT_SECONDS" in answer
    assert history[-1]["role"] == "tool"
    assert not any(message.get("content") == "Final fixture answer" for message in history)


def test_tool_overrun_stops_before_the_next_tool_or_request(monkeypatch):
    loop = load_loop(monkeypatch, "300", "180")
    clock, calls = simulated_http(monkeypatch, loop, [
        tool_message("filter_specs", "get_bike_details"),
    ], seconds_per_request=10)
    executed = []

    def execute(conn, name, arguments):
        executed.append(name)
        clock.advance(190)  # Cooperative checks cannot interrupt this tool.
        return [{"model": "Fixture bike"}]

    monkeypatch.setattr(loop, "execute_tool", execute)

    answer, history = loop._run_agent_ollama(None, "Question", None)

    assert clock.seconds - 1000 == 200
    assert calls == [180]
    assert executed == ["filter_specs"]
    assert "180-second budget" in answer
    assert history[-1] == {"role": "tool", "content": "[{'model': 'Fixture bike'}]"}


def test_final_answer_within_the_turn_budget_succeeds(monkeypatch):
    loop = load_loop(monkeypatch, "300", "180")
    clock, calls = simulated_http(monkeypatch, loop, [
        tool_message("filter_specs"), {"role": "assistant", "content": "A local answer"},
    ], seconds_per_request=20)
    monkeypatch.setattr(loop, "execute_tool", Mock(return_value=[]))

    answer, history = loop._run_agent_ollama(None, "Question", None)

    assert answer == "A local answer"
    assert clock.seconds - 1000 == 40
    assert calls == [180, 160]
    assert history[-1] == {"role": "assistant", "content": answer}


def test_response_arriving_after_the_budget_is_not_a_final_answer(monkeypatch):
    loop = load_loop(monkeypatch, "300", "180")
    clock = Clock()
    monkeypatch.setattr(loop.time, "monotonic", clock.monotonic)

    def post(*args, **kwargs):
        clock.advance(190)  # Read timeouts are not a hard total deadline.
        response = Mock()
        response.json.return_value = {"message": {"role": "assistant", "content": "Late answer"}}
        return response

    monkeypatch.setattr(loop.requests, "post", post)

    answer, history = loop._run_agent_ollama(None, "Question", None)

    assert "180-second budget" in answer
    assert history == [{"role": "user", "content": "Question"}]


@pytest.mark.parametrize("configured,expected", [(None, 180), ("60", 60), ("0.5", 0.5)])
def test_ollama_turn_budget_default_and_configuration(monkeypatch, configured, expected):
    loop = load_loop(monkeypatch, "300", configured)
    _, calls = simulated_http(monkeypatch, loop, [
        {"role": "assistant", "content": "A local answer"},
    ], seconds_per_request=0)

    answer, _ = loop._run_agent_ollama(None, "Question", None)

    assert loop.OLLAMA_TURN_TIMEOUT_SECONDS == expected
    assert calls == [expected]
    assert answer == "A local answer"


@pytest.mark.parametrize("configured", ["0", "-1", "invalid", "nan", "inf"])
def test_ollama_turn_budget_rejects_invalid_configuration(monkeypatch, configured):
    with pytest.raises(ValueError, match="OLLAMA_TURN_TIMEOUT_SECONDS must be a positive finite number"):
        load_loop(monkeypatch, "300", configured)

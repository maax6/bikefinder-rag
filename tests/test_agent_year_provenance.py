"""Year provenance at the agent boundary; HTTP and SDK responses are fixtures."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


LOOP_PATH = Path(__file__).resolve().parents[1] / "src/bikefinder_rag/agent/loop.py"
QUESTION = "Quelle est la puissance de la Suzuki GSF 1200 N Bandit ?"


@pytest.fixture
def loop(monkeypatch):
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("OLLAMA_TURN_TIMEOUT_SECONDS", "180")
    spec = importlib.util.spec_from_file_location("year_provenance_loop", LOOP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def detail_call(year=2000, model="GSF 1200 N Bandit"):
    return {"id": "sheet", "function": {"name": "get_bike_details", "arguments": {"model": model, "year": year}}}


def ollama_response(*calls, final=None):
    response = Mock()
    response.json.return_value = {"message": {
        "role": "assistant", "content": final or "", **({"tool_calls": list(calls)} if calls else {}),
    }}
    return response


@pytest.mark.parametrize("provider", ["ollama", "openrouter", "anthropic"])
def test_fabricated_year_clarifies_before_sql_and_keeps_a_complete_safe_turn(loop, monkeypatch, provider):
    previous = [{"role": "user", "content": "Bonjour"}, {"role": "assistant", "content": "Bonjour."}]
    original = deepcopy(previous)
    conn = SimpleNamespace(cursor=Mock(side_effect=AssertionError("SQL must not run")))
    call = detail_call()
    client = None
    if provider == "anthropic":
        client = Mock()
        client.messages.create.return_value = SimpleNamespace(stop_reason="tool_use", content=[
            SimpleNamespace(type="tool_use", name="get_bike_details", input=call["function"]["arguments"], id="sheet"),
        ])
        request = client.messages.create
    else:
        response = ollama_response(call)
        if provider == "openrouter":
            call["function"]["arguments"] = json.dumps(call["function"]["arguments"])
            response.json.return_value = {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call]}}]}
        request = Mock(return_value=response)
        monkeypatch.setattr(loop.requests, "post", request)

    answer, history = loop.run_agent(conn, client, QUESTION, previous, provider=provider, api_key="fixture")

    assert "millésime" in answer and "Aucune année" in answer
    assert history[:-1] == [*previous, {"role": "user", "content": QUESTION}]
    assert history[-1]["role"] == "assistant" and not history[-1].get("tool_calls")
    if provider == "anthropic":
        assert history[-1]["content"] == [{"type": "text", "text": answer}]
    else:
        assert history[-1]["content"] == answer
    conn.cursor.assert_not_called()
    assert request.call_count == 1
    assert previous == original


def test_missing_year_then_numeric_reply_then_same_year_followup(loop, monkeypatch):
    post = Mock(side_effect=[
        ollama_response(detail_call()),
        ollama_response(detail_call()), ollama_response(final="Fixture power answer"),
        ollama_response(detail_call()), ollama_response(final="Fixture dry weight answer"),
    ])
    monkeypatch.setattr(loop.requests, "post", post)
    execute = Mock(return_value=[{"model": "GSF 1200 N Bandit", "year": 2000, "url": "https://catalog.example/2000"}])
    monkeypatch.setattr(loop, "execute_tool", execute)

    clarification, history = loop.run_agent(None, None, QUESTION, provider="ollama")
    execute.assert_not_called()
    power, history = loop.run_agent(None, None, "2000", history, provider="ollama")
    weight, history = loop.run_agent(None, None, "Et son poids sec au même millésime ?", history, provider="ollama")

    assert "millésime" in clarification
    assert power == "Fixture power answer" and weight == "Fixture dry weight answer"
    assert [call.args[2]["year"] for call in execute.call_args_list] == [2000, 2000]
    assert post.call_args_list[1].kwargs["json"]["messages"][1:3] == [
        {"role": "user", "content": QUESTION}, {"role": "assistant", "content": clarification},
    ]
    assert [message["content"] for message in history if message["role"] == "user"] == [
        QUESTION, "2000", "Et son poids sec au même millésime ?",
    ]


@pytest.mark.parametrize("question,model,year", [
    (QUESTION, "GSF 1200 N Bandit", 1200),
    ("Puissance de la Honda VTX 1800 ?", "VTX 1800", 1800),
    ("Puissance de la Honda VTX 1800 ?", "VTX1800", 1800),
    ("Puissance de la Kawasaki Vulcan 2000 ?", "Vulcan 2000", 2000),
    ("Puissance de la Kawasaki Vulcan 2000 ?", "Vulcan", 2000),
    ("Fiche technique Bandit 2000 ?", "Bandit", 2000),
    ("Honda de 2000 cc ?", "Honda", 2000),
    ("Honda, budget de 2000 euros ?", "Honda", 2000),
    ("Honda, budget de 2000 ?", "Honda", 2000),
    ("Honda à 2000 € ?", "Honda", 2000),
    ("Honda de 2000.5 ?", "Honda", 2000),
    ("Honda en 2000,5 ?", "Honda", 2000),
    ("Honda, année -2000 ?", "Honda", 2000),
    ("Puissance Bandit de deux mille ?", "Bandit", 2000),
])
def test_model_codes_units_prices_and_written_years_do_not_authorize_an_invented_year(loop, monkeypatch, question, model, year):
    conn = SimpleNamespace(cursor=Mock(side_effect=AssertionError("SQL must not run")))
    post = Mock(return_value=ollama_response(detail_call(year, model)))
    monkeypatch.setattr(loop.requests, "post", post)

    answer, history = loop.run_agent(conn, None, question, provider="ollama")

    assert "millésime" in answer
    assert [message["role"] for message in history] == ["user", "assistant"]
    conn.cursor.assert_not_called()
    assert post.call_count == 1


@pytest.mark.parametrize("question,model,year", [
    ("Puissance Vulcan 2000 de 2004 ?", "Vulcan 2000", 2004),
    ("Puissance VTX 1800, millésime 2004 ?", "VTX 1800", 2004),
    ("Fiche de la Bandit, année 1750 ?", "Bandit", 1750),
    ("Puissance de la Bandit de 2000.", "Bandit", 2000),
    ("Bandit en 2000, avec sa source ?", "Bandit", 2000),
    ("Bandit in 2000, with its source?", "Bandit", 2000),
])
def test_explicit_year_survives_numeric_model_identity(loop, monkeypatch, question, model, year):
    post = Mock(side_effect=[ollama_response(detail_call(year, model)), ollama_response(final="Fixture answer")])
    monkeypatch.setattr(loop.requests, "post", post)
    execute = Mock(return_value=[])
    monkeypatch.setattr(loop, "execute_tool", execute)

    answer, _ = loop.run_agent(None, None, question, provider="ollama")

    assert answer == "Fixture answer"
    execute.assert_called_once_with(None, "get_bike_details", {"model": model, "year": year})


def test_current_user_year_overrides_older_year_and_batch_is_checked_before_any_tool(loop, monkeypatch):
    previous = [{"role": "user", "content": "Bandit en 2000 ?"}, {"role": "assistant", "content": "Fixture old answer"}]
    post = Mock(return_value=ollama_response(
        {"function": {"name": "filter_specs", "arguments": {"min_year": 2004, "max_year": 2004}}},
        detail_call(2000),
    ))
    monkeypatch.setattr(loop.requests, "post", post)
    conn = SimpleNamespace(cursor=Mock(side_effect=AssertionError("No tool in a rejected batch should reach SQL")))

    answer, history = loop.run_agent(conn, None, "Et pour le millésime 2004 ?", previous, provider="ollama")

    assert "2004" in answer
    assert history == [*previous, {"role": "user", "content": "Et pour le millésime 2004 ?"},
                       {"role": "assistant", "content": answer}]
    conn.cursor.assert_not_called()


def test_assistant_and_anthropic_tool_results_do_not_establish_user_year(loop, monkeypatch):
    previous = [
        {"role": "user", "content": QUESTION},
        {"role": "assistant", "content": "Voici un exemple de 2000."},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "old", "content": "2000"}]},
    ]
    monkeypatch.setattr(loop.requests, "post", Mock(return_value=ollama_response(detail_call())))
    conn = SimpleNamespace(cursor=Mock(side_effect=AssertionError("SQL must not run")))

    answer, _ = loop.run_agent(conn, None, "Et le poids sec ?", previous, provider="ollama")

    assert "Aucune année" in answer
    conn.cursor.assert_not_called()


def test_current_explicit_range_endpoints_can_each_retrieve_a_sheet(loop, monkeypatch):
    monkeypatch.setattr(loop.requests, "post", Mock(side_effect=[
        ollama_response(detail_call(2000, "Bandit"), detail_call(2001, "Bandit")),
        ollama_response(final="Fixture two-year comparison"),
    ]))
    execute = Mock(return_value=[])
    monkeypatch.setattr(loop, "execute_tool", execute)

    answer, _ = loop.run_agent(None, None, "Compare la Bandit de 2000-2001.", provider="ollama")

    assert answer == "Fixture two-year comparison"
    assert [call.args[2]["year"] for call in execute.call_args_list] == [2000, 2001]


def test_multiple_previous_user_years_require_clarification_for_same_year_followup(loop, monkeypatch):
    previous = [{"role": "user", "content": "Compare la Bandit de 2000-2001."},
                {"role": "assistant", "content": "Fixture two-year comparison"}]
    monkeypatch.setattr(loop.requests, "post", Mock(return_value=ollama_response(detail_call(2000, "Bandit"))))
    conn = SimpleNamespace(cursor=Mock(side_effect=AssertionError("Ambiguous prior year must not reach SQL")))

    answer, history = loop.run_agent(conn, None, "Et son couple au même millésime ?", previous, provider="ollama")

    assert "Plusieurs millésimes" in answer
    assert history[-1] == {"role": "assistant", "content": answer}
    conn.cursor.assert_not_called()


def test_prior_numeric_model_identity_does_not_establish_a_year_for_a_different_model(loop, monkeypatch):
    previous = [{"role": "user", "content": "Quelle est la puissance de la Honda VTX 1800 ?"},
                {"role": "assistant", "content": "Fixture previous answer"}]
    monkeypatch.setattr(loop.requests, "post", Mock(return_value=ollama_response(detail_call(1800))))
    conn = SimpleNamespace(cursor=Mock(side_effect=AssertionError("A prior model number is not a year")))

    answer, history = loop.run_agent(conn, None, QUESTION, previous, provider="ollama")

    assert "Aucune année" in answer
    assert history == [*previous, {"role": "user", "content": QUESTION}, {"role": "assistant", "content": answer}]
    conn.cursor.assert_not_called()


def test_batch_cannot_swap_numeric_model_identities_into_each_others_years(loop, monkeypatch):
    monkeypatch.setattr(loop.requests, "post", Mock(return_value=ollama_response(
        detail_call(2000, "VTX 1800"), detail_call(1800, "Vulcan 2000"),
    )))
    conn = SimpleNamespace(cursor=Mock(side_effect=AssertionError("Neither model number establishes a year")))
    question = "Compare la Honda VTX 1800 et la Kawasaki Vulcan 2000."

    answer, history = loop.run_agent(conn, None, question, provider="ollama")

    assert "Aucune année" in answer
    assert history == [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    conn.cursor.assert_not_called()


def test_rejected_later_tool_round_discards_current_traces_but_keeps_the_question(loop, monkeypatch):
    filter_call = {"function": {"name": "filter_specs", "arguments": {"brand": "Suzuki"}}}
    post = Mock(side_effect=[ollama_response(filter_call), ollama_response(detail_call())])
    monkeypatch.setattr(loop.requests, "post", post)
    execute = Mock(return_value=[{"model": "Bandit", "year": 2000}])
    monkeypatch.setattr(loop, "execute_tool", execute)

    answer, history = loop.run_agent(None, None, QUESTION, provider="ollama")

    assert history == [{"role": "user", "content": QUESTION}, {"role": "assistant", "content": answer}]
    assert "Aucune année" in answer
    execute.assert_called_once_with(None, "filter_specs", {"brand": "Suzuki"})

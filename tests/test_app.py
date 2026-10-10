"""Local startup and UI compatibility checks, without a database or model."""

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


SRC_DIR = Path(__file__).resolve().parents[1] / "src"


@pytest.mark.parametrize(
    ("config", "expected_backend", "expected_model"),
    [
        (None, "ollama", "mistral-small3.2"),
        ("AGENT_BACKEND=ollama\nOLLAMA_MODEL=local-config-test\n", "ollama", "local-config-test"),
        ("AGENT_BACKEND=anthropic\n", "anthropic", "mistral-small3.2"),
    ],
)
def test_app_loads_dotenv_before_runtime_import(tmp_path, config, expected_backend, expected_model):
    if config is not None:
        (tmp_path / ".env").write_text(config, encoding="utf-8")
    env = os.environ.copy()
    for name in ("AGENT_BACKEND", "OLLAMA_MODEL", "PYTHON_DOTENV_DISABLED"):
        env.pop(name, None)
    env.update({
        "PYTHONPATH": str(SRC_DIR),
        "GRADIO_ANALYTICS_ENABLED": "False",
        "HF_HUB_OFFLINE": "1",
    })
    # -c makes python-dotenv look in this isolated directory. No repository
    # .env is read, and importing the UI does not launch a server or model.
    result = subprocess.run(
        [sys.executable, "-c",
         "import json; from bikefinder_rag import app; "
         "print(json.dumps([app.BACKEND, app.OLLAMA_MODEL]))"],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=True, timeout=30,
    )
    assert json.loads(result.stdout.strip()) == [expected_backend, expected_model]


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("AGENT_BACKEND", "ollama")
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with patch("dotenv.load_dotenv", return_value=False):
        return importlib.import_module("bikefinder_rag.app")


def test_local_ui_exposes_technical_year_questions_and_catalogue_limits(app):
    components = app.demo.get_config_file()["components"]
    visible = [component for component in components if component["props"].get("visible", True)]
    descriptions = " ".join(
        component["props"].get("value", "")
        for component in visible if component["type"] == "markdown"
    )
    assert "POC local" in descriptions
    assert app.OLLAMA_MODEL in descriptions
    assert f"{app.OLLAMA_TURN_TIMEOUT_SECONDS:g} s" in descriptions
    assert "millésime" in descriptions
    assert "couverture" in descriptions and "partielle" in descriptions
    assert "inconnue" in descriptions
    assert "poids sec" in descriptions and "poids tous pleins" in descriptions
    assert "date de lancement" in descriptions

    questions = next(
        component["props"]["samples"]
        for component in visible if component["type"] == "dataset"
    )
    assert len(questions) == 2
    assert all("2000" in question[0] and "sources" in question[0] for question in questions)
    assert any("fiche technique" in question[0].lower() for question in questions)
    assert any("compare" in question[0].lower() and "tableau" in question[0] for question in questions)
    user_text = descriptions + " ".join(question[0] for question in questions) + app.msg.placeholder
    assert not any(term in user_text.lower() for term in ("owner", "avis", "réputation", "prix"))


def test_local_chat_returns_gradio_messages_and_closes_connection(app, monkeypatch):
    monkeypatch.setattr(app, "BACKEND", "ollama")
    conn = SimpleNamespace(close=Mock())
    monkeypatch.setattr(app, "get_connection", Mock(return_value=conn))
    old_agent_history = [{"role": "user", "content": "Earlier question"},
                         {"role": "assistant", "content": "Earlier answer"}]
    new_agent_history = [*old_agent_history, {"role": "assistant", "content": "A local answer"}]
    agent = Mock(return_value=("A local answer", new_agent_history))
    monkeypatch.setattr(app, "run_agent", agent)
    old_chat_history = [{"role": "assistant", "content": "Earlier answer"}]

    messages, agent_history = app.chat("Question", old_chat_history, "", old_agent_history)

    assert messages == [
        *old_chat_history,
        {"role": "user", "content": "Question"},
        {"role": "assistant", "content": "A local answer"},
    ]
    assert len(old_chat_history) == 1
    assert agent_history is new_agent_history
    agent.assert_called_once_with(conn, None, "Question", old_agent_history, provider=None, api_key=None)
    conn.close.assert_called_once_with()
    assert app.chatbot.postprocess(messages) is not None


@pytest.fixture
def local_runtime(app, monkeypatch):
    loop = importlib.import_module("bikefinder_rag.agent.loop")
    monkeypatch.setattr(app, "BACKEND", "ollama")
    monkeypatch.setattr(loop, "BACKEND", "ollama")
    monkeypatch.setattr(loop, "OLLAMA_TIMEOUT_SECONDS", 120)
    monkeypatch.setattr(loop, "OLLAMA_TURN_TIMEOUT_SECONDS", 180)
    conn = SimpleNamespace(close=Mock())
    monkeypatch.setattr(app, "get_connection", Mock(return_value=conn))
    execute = Mock(return_value=[{"model": "Sportster", "year": 1959}])
    monkeypatch.setattr(loop, "execute_tool", execute)
    return app, loop, conn, execute


def ollama_response(message):
    response = Mock()
    response.json.return_value = {"message": message}
    return response


@pytest.mark.parametrize("failure", ["before-tool", "after-tool", "connection"])
def test_failed_local_turn_preserves_completed_state_and_retry_uses_one_question(local_runtime, monkeypatch, failure):
    import requests

    app, loop, conn, execute = local_runtime
    previous_state = [{"role": "user", "content": "Earlier question"},
                      {"role": "assistant", "content": "Earlier answer"}]
    question = "Quelles motos custom des annees 1950 ?"
    tool_message = {"role": "assistant", "content": "", "tool_calls": [{
        "function": {"name": "filter_specs", "arguments": {"min_year": 1950, "max_year": 1959}}
    }]}
    responses = [ollama_response(tool_message)] if failure == "after-tool" else []
    error = requests.ConnectionError() if failure == "connection" else requests.ReadTimeout()
    responses.extend([error, ollama_response({"role": "assistant", "content": "A completed retry"})])
    post = Mock(side_effect=responses)
    monkeypatch.setattr(loop.requests, "post", post)

    visible, failed_state = app.chat(question, [], "", previous_state)
    assert failed_state is previous_state
    assert visible[-1]["role"] == "assistant"  # UI error remains visible
    assert "timeout" in visible[-1]["content"] or "Could not reach" in visible[-1]["content"]
    assert app.chatbot.postprocess(visible) is not None

    visible, succeeded_state = app.chat("retry", visible, "", failed_state)
    retry_payload = post.call_args.kwargs["json"]["messages"]
    assert sum(m.get("role") == "user" and m.get("content") == question for m in retry_payload) == 1
    assert not any(m.get("role") == "tool" or m.get("tool_calls") for m in retry_payload)
    assert retry_payload[-1] == {"role": "user", "content": question}
    assert visible[-2] == {"role": "user", "content": "retry"}
    assert visible[-1]["content"] == "A completed retry"
    assert succeeded_state[-1] == {"role": "assistant", "content": "A completed retry"}
    assert conn.close.call_count == 2
    assert execute.call_count == (1 if failure == "after-tool" else 0)


def test_local_retry_cleans_a_legacy_incomplete_state(local_runtime, monkeypatch):
    app, loop, _, _ = local_runtime
    question = "What is the fuel capacity of the Suzuki GSF 1200 Bandit?"
    completed = [{"role": "user", "content": "Earlier question"},
                 {"role": "assistant", "content": "Earlier answer"}]
    incomplete = completed + [{"role": "user", "content": question},
                               {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_bike_details"}}]},
                               {"role": "tool", "content": "Old results from the failed attempt"}]
    visible = [{"role": "user", "content": question},
               {"role": "assistant", "content": "Read timeout"},
               {"role": "user", "content": "retry"},
               {"role": "assistant", "content": "Read timeout"}]
    post = Mock(return_value=ollama_response({"role": "assistant", "content": "20 litres"}))
    monkeypatch.setattr(loop.requests, "post", post)

    _, state = app.chat("réessaie", visible, "", incomplete)
    payload = post.call_args.kwargs["json"]["messages"]
    assert payload[1:] == completed + [{"role": "user", "content": question}]
    assert state == completed + [{"role": "user", "content": question},
                                  {"role": "assistant", "content": "20 litres"}]
    assert len(incomplete) == 5  # input state is not mutated


def test_local_retry_without_an_earlier_question_skips_backend(app, monkeypatch):
    monkeypatch.setattr(app, "BACKEND", "ollama")
    conn = Mock(side_effect=AssertionError("No database needed"))
    monkeypatch.setattr(app, "get_connection", conn)
    old_state = []
    visible, state = app.chat("retry", [], "", old_state)
    assert state is old_state
    assert "earlier question" in visible[-1]["content"]
    conn.assert_not_called()


def test_local_state_drops_failed_turns_before_a_later_completed_turn(app, monkeypatch):
    monkeypatch.setattr(app, "BACKEND", "ollama")
    failed = [{"role": "user", "content": "Failed question"},
              {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "filter_specs"}}]},
              {"role": "tool", "content": "Old unfinished results"}]
    completed = [{"role": "user", "content": "Successful question"},
                 {"role": "assistant", "content": "A successful answer"}]
    conn = SimpleNamespace(close=Mock())
    monkeypatch.setattr(app, "get_connection", Mock(return_value=conn))
    agent = Mock(return_value=("New answer", completed + [{"role": "user", "content": "New question"},
                                                          {"role": "assistant", "content": "New answer"}]))
    monkeypatch.setattr(app, "run_agent", agent)
    app.chat("New question", [], "", failed + completed)
    assert agent.call_args.args[3] == completed


def test_completed_local_tool_turn_keeps_its_grounding(local_runtime, monkeypatch):
    app, loop, _, execute = local_runtime
    tool_message = {"role": "assistant", "content": "", "tool_calls": [{
        "function": {"name": "filter_specs", "arguments": {"min_year": 1950, "max_year": 1959}}
    }]}
    post = Mock(side_effect=[ollama_response(tool_message),
                             ollama_response({"role": "assistant", "content": "A grounded answer"})])
    monkeypatch.setattr(loop.requests, "post", post)
    _, state = app.chat("Motos des annees 1950 ?", [], "", [])
    assert [message["role"] for message in state] == ["user", "assistant", "tool", "assistant"]
    assert state[2]["content"] == "[{'model': 'Sportster', 'year': 1959}]"
    assert state[-1]["content"] == "A grounded answer"
    execute.assert_called_once()


@pytest.mark.parametrize("failure_text", [
    "I hit my tool-call limit for this question without reaching a final answer — try rephrasing or narrowing the question.",
    "The local Ollama turn exceeded its 180-second budget — generation stopped.",
    "",
])
def test_nonfinal_limit_or_empty_answer_does_not_enter_local_state(app, monkeypatch, failure_text):
    monkeypatch.setattr(app, "BACKEND", "ollama")
    previous = [{"role": "user", "content": "Earlier"}, {"role": "assistant", "content": "Done"}]
    incomplete = previous + [{"role": "user", "content": "New question"},
                             {"role": "tool", "content": "Unfinished tool results"}]
    conn = SimpleNamespace(close=Mock())
    monkeypatch.setattr(app, "get_connection", Mock(return_value=conn))
    monkeypatch.setattr(app, "run_agent", Mock(return_value=(failure_text, incomplete)))
    visible, state = app.chat("New question", [], "", previous)
    assert state is previous
    assert visible[-1]["content"]
    assert all(message["content"] != failure_text for message in state)


def test_remote_retry_routing_and_state_remain_unchanged(app, monkeypatch):
    monkeypatch.setattr(app, "BACKEND", "anthropic")
    previous = [{"role": "user", "content": "Earlier"}]
    updated = previous + [{"role": "assistant", "content": "Remote answer"}]
    conn = SimpleNamespace(close=Mock())
    monkeypatch.setattr(app, "get_connection", Mock(return_value=conn))
    agent = Mock(return_value=("Remote answer", updated))
    monkeypatch.setattr(app, "run_agent", agent)
    _, state = app.chat("retry", [{"role": "user", "content": "Substantive question"}], "sk-or-example", previous)
    agent.assert_called_once_with(conn, None, "retry", previous, provider="openrouter", api_key="sk-or-example")
    assert state is updated


def test_remote_chat_without_key_returns_valid_messages_without_database(app, monkeypatch):
    monkeypatch.setattr(app, "BACKEND", "anthropic")
    conn_factory = Mock(side_effect=AssertionError("No database needed for a missing key"))
    agent = Mock(side_effect=AssertionError("No model needed for a missing key"))
    monkeypatch.setattr(app, "get_connection", conn_factory)
    monkeypatch.setattr(app, "run_agent", agent)
    old_agent_history = []

    messages, agent_history = app.chat("Question", [], "  ", old_agent_history)

    assert messages[0] == {"role": "user", "content": "Question"}
    assert messages[1]["role"] == "assistant"
    assert "API key" in messages[1]["content"]
    assert agent_history is old_agent_history
    conn_factory.assert_not_called()
    agent.assert_not_called()
    assert app.chatbot.postprocess(messages) is not None

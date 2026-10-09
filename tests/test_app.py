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


def test_local_chat_returns_gradio_messages_and_closes_connection(app, monkeypatch):
    monkeypatch.setattr(app, "BACKEND", "ollama")
    conn = SimpleNamespace(close=Mock())
    monkeypatch.setattr(app, "get_connection", Mock(return_value=conn))
    old_agent_history = [{"role": "user", "content": "Earlier question"}]
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

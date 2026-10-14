"""Public chat compatibility and Gradio 6 presentation startup regressions."""

from unittest.mock import Mock
from pathlib import Path

import gradio as gr

from bikefinder_rag import app
from bikefinder_rag.ui import CSS, THEME


def test_public_chat_endpoint_keeps_inputs_and_both_submission_triggers():
    config = app.demo.get_config_file()
    endpoint = next(dep for dep in config["dependencies"] if dep["api_name"] == "chat")
    assert endpoint["inputs"] == [app.msg._id, app.chatbot._id, app.api_key_input._id, app.agent_state._id]
    assert endpoint["outputs"] == [app.chatbot._id, app.agent_state._id]
    assert set(map(tuple, endpoint["targets"])) == {(app.msg._id, "submit"), (app.send._id, "click")}


def test_new_conversation_clears_visible_and_hidden_context_and_cancels_pending_submission():
    config = app.demo.get_config_file()
    reset = next(dep for dep in config["dependencies"] if dep["api_name"] == "clear_conversation")
    assert reset["outputs"] == [app.chatbot._id, app.agent_state._id, app.msg._id]
    assert set(map(tuple, reset["targets"])) == {(app.reset._id, "click"), (app.chatbot._id, "clear")}
    chat = next(dep for dep in config["dependencies"] if dep["api_name"] == "chat")
    draft = next(dep for dep in config["dependencies"] if dep["trigger_after"] == chat["id"])
    cancellation = next(dep for dep in config["dependencies"] if dep["cancels"])
    assert set(cancellation["cancels"]) == {chat["id"], draft["id"]}
    assert reset["api_visibility"] == "private"


def test_custom_theme_supports_gradio_startup_comparison_without_external_fonts():
    # launch() compares the serialised theme with built-ins when quiet=False.
    # Raw string fonts crash Font.__eq__ during that real startup path.
    for builtin in (gr.themes.Base(), gr.themes.Default(), gr.themes.Soft(), gr.themes.Monochrome()):
        assert THEME.to_dict() != builtin.to_dict()
    assert all(font.stylesheet()["url"] is None for font in [*THEME._font, *THEME._font_mono])


def test_launcher_applies_gradio6_styles_and_preserves_caller_options(monkeypatch):
    monkeypatch.setenv("GRADIO_HOST", "127.0.0.1")
    launch = Mock(return_value="launched")
    monkeypatch.setattr(app.demo, "launch", launch)
    assert app.launch_chatbot(server_port=7899, quiet=True) == "launched"
    assert launch.call_args.kwargs == {
        "server_name": "127.0.0.1", "server_port": 7899, "quiet": True,
        "theme": THEME, "css": CSS, "footer_links": [],
        "allowed_paths": [str(Path(app.__file__).resolve().parents[2] / "data/technical/chat-exports")],
    }


def test_launcher_serves_exports_and_preserves_explicit_allowed_paths(monkeypatch):
    launch = Mock()
    monkeypatch.setattr(app.demo, "launch", launch)
    app.launch_chatbot(allowed_paths=["/private/tmp/explicit-public-output"])
    paths = launch.call_args.kwargs["allowed_paths"]
    root = Path(app.__file__).resolve().parents[2]
    assert paths == ["/private/tmp/explicit-public-output", str(root / "data/technical/chat-exports")]
    assert str(root) not in paths
    assert str(root / ".env") not in paths

"""Gradio UI for the local proof of concept, using Ollama by default.

Optional Anthropic/OpenRouter backends use a visitor-provided API key.
"""

import os
import re
import unicodedata

from dotenv import load_dotenv

load_dotenv()

import gradio as gr

from bikefinder_rag.agent.loop import BACKEND, OLLAMA_MODEL, TURN_LIMIT_MESSAGE, run_agent
from bikefinder_rag.db.client import get_connection


def _is_retry(message: str) -> bool:
    text = unicodedata.normalize("NFKD", message).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z\s]", "", text)
    return " ".join(text.split()) in {
        "retry", "try again", "retry please", "retente", "reessaie", "reessaye",
        "essaie encore", "reessaie stp", "retente stp",
    }


def _is_final_local_message(message: dict) -> bool:
    return (isinstance(message, dict) and message.get("role") == "assistant"
            and not message.get("tool_calls") and isinstance(message.get("content"), str)
            and bool(message["content"].strip()) and message["content"] != TURN_LIMIT_MESSAGE)


def _completed_local_history(history: list) -> list:
    """Discard incomplete attempts, including legacy ones before later turns."""
    completed, pending = [], []
    for message in history:
        if isinstance(message, dict) and message.get("role") == "user":
            pending = [message]
        elif pending:
            pending.append(message)
            if _is_final_local_message(message):
                completed.extend(pending)
                pending = []
    return history if completed == history else completed


def _previous_question(chat_history: list) -> str | None:
    for message in reversed(chat_history):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip() and not _is_retry(content):
            return content
    return None


def chat(message: str, chat_history: list, api_key: str, agent_history: list):
    api_key = (api_key or "").strip()
    if BACKEND != "ollama" and not api_key:
        chat_history = chat_history + [
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": "Please enter your API key above first — Anthropic "
                           "(console.anthropic.com) or OpenRouter (openrouter.ai/keys).",
            },
        ]
        return chat_history, agent_history

    provider = None
    if BACKEND != "ollama":
        provider = "openrouter" if api_key.startswith("sk-or-") else "anthropic"

    question = message
    previous_state = agent_history
    if BACKEND == "ollama":
        previous_state = _completed_local_history(agent_history)
        if _is_retry(message):
            question = _previous_question(chat_history)
            if question is None:
                return chat_history + [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": "There is no earlier question to retry. Ask your question first."},
                ], previous_state

    conn = get_connection()
    try:
        final_text, updated_history = run_agent(
            conn, None, question, previous_state, provider=provider, api_key=api_key or None
        )
    finally:
        conn.close()

    if BACKEND == "ollama" and not (
        isinstance(updated_history, list) and updated_history
        and _is_final_local_message(updated_history[-1])
        and updated_history[-1]["content"] == final_text
    ):
        # The UI keeps its error bubble; the model only sees completed turns.
        updated_history = previous_state
        if not isinstance(final_text, str) or not final_text.strip():
            final_text = "The local model did not produce a final answer. Please retry."

    chat_history = chat_history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": final_text},
    ]
    return chat_history, updated_history


with gr.Blocks(title="Bikefinder RAG") as demo:
    if BACKEND == "ollama":
        gr.Markdown(
            "# 🏍️ Bikefinder RAG (local proof of concept)\n"
            "Ask about motorcycle specs and owner reviews, scraped from bikez.com. "
            f"Running on a local Ollama model (`{OLLAMA_MODEL}`) — "
            "no API key needed, but expect slower responses."
        )
        api_key_input = gr.Textbox(visible=False)
    else:
        gr.Markdown(
            "# 🏍️ Bikefinder RAG\n"
            "Ask about motorcycle specs and owner reviews, scraped from bikez.com. "
            "Bring your own [Anthropic](https://console.anthropic.com/) or "
            "[OpenRouter](https://openrouter.ai/keys) API key — detected by its "
            "prefix, used only for your session and never stored."
        )
        api_key_input = gr.Textbox(
            label="API key (Anthropic or OpenRouter)",
            type="password",
            placeholder="sk-ant-... or sk-or-...",
        )
    chatbot = gr.Chatbot(label="Chat")
    msg = gr.Textbox(label="Your question", placeholder="A light naked bike under 600cc, and what do owners say about it?")
    agent_state = gr.State([])

    msg.submit(
        chat,
        inputs=[msg, chatbot, api_key_input, agent_state],
        outputs=[chatbot, agent_state],
    ).then(lambda: "", None, msg)


if __name__ == "__main__":
    demo.launch(server_name=os.environ.get("GRADIO_HOST", "127.0.0.1"))

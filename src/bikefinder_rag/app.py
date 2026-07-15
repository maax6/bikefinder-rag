"""Gradio chat UI. Visitors provide their own API key — Anthropic
(sk-ant-...) or OpenRouter (sk-or-...), routed by prefix — kept only in
their browser session's Gradio State, never written to disk, so this demo
can be hosted for free on Hugging Face Spaces without the owner paying
for every visitor's API usage."""

import os

import gradio as gr
from dotenv import load_dotenv

from bikefinder_rag.agent.loop import BACKEND, OLLAMA_MODEL, run_agent
from bikefinder_rag.db.client import get_connection

load_dotenv()


def chat(message: str, chat_history: list, api_key: str, agent_history: list):
    api_key = (api_key or "").strip()
    if BACKEND != "ollama" and not api_key:
        chat_history = chat_history + [
            (message, "Please enter your API key above first — Anthropic "
                      "(console.anthropic.com) or OpenRouter (openrouter.ai/keys).")
        ]
        return chat_history, agent_history

    provider = None
    if BACKEND != "ollama":
        provider = "openrouter" if api_key.startswith("sk-or-") else "anthropic"

    conn = get_connection()
    try:
        final_text, updated_history = run_agent(
            conn, None, message, agent_history, provider=provider, api_key=api_key or None
        )
    finally:
        conn.close()

    chat_history = chat_history + [(message, final_text)]
    return chat_history, updated_history


with gr.Blocks(title="Bikefinder RAG") as demo:
    if BACKEND == "ollama":
        gr.Markdown(
            "# 🏍️ Bikefinder RAG (local model)\n"
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

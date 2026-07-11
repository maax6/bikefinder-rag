#!/usr/bin/env python3
"""Talk to the agent directly from the terminal, no Gradio needed.

Uses AGENT_BACKEND from .env (defaults to "anthropic"; set to "ollama" to
use a local model instead). Run:

    PYTHONPATH=src .venv/bin/python scripts/chat_cli.py
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
load_dotenv()

from bikefinder_rag.agent.loop import BACKEND, run_agent
from bikefinder_rag.db.client import get_connection


def main() -> None:
    client = None
    if BACKEND != "ollama":
        from anthropic import Anthropic

        client = Anthropic()

    print(f"Backend: {BACKEND}. Type 'quit' to exit.\n")

    conn = get_connection()
    history: list[dict] = []
    try:
        while True:
            try:
                user_message = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_message:
                continue
            if user_message.lower() in {"quit", "exit"}:
                break

            answer, history = run_agent(conn, client, user_message, history)
            print(f"agent> {answer}\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

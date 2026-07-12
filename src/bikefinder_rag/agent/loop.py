"""Agentic RAG loop: raw Anthropic tool-use, no agent framework.

The loop is intentionally explicit (not hidden behind LangChain/LlamaIndex)
so the whole tool-call round-trip is visible and easy to reason about.

Two backends are supported, picked via the AGENT_BACKEND env var:
- "anthropic" (default): the hosted Gradio demo path, visitor's own key.
- "ollama": local models (e.g. Mistral Small) for free/offline dev and
  testing, via Ollama's OpenAI-style function-calling API.
"""

import json
import os

import requests
from anthropic import Anthropic

from bikefinder_rag.agent.tools import TOOLS, execute_tool

BACKEND = os.environ.get("AGENT_BACKEND", "anthropic")
MODEL = "claude-sonnet-5"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral-small")

# Ollama's tool-calling API takes OpenAI-style function schemas
# ({"type": "function", "function": {...}}), not Anthropic's
# {"name", "input_schema"} — convert once at import time.
OLLAMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }
    for tool in TOOLS
]

SYSTEM_PROMPT = """You are a motorcycle expert assistant backed by a database \
scraped from bikez.com (specs) and its owner discussion forums (reviews).

You have two tools:
- filter_specs: precise structured filtering (displacement, weight, power, \
seat height, category, brand, year, price).
- search_reviews: semantic search over real owner comments, for qualitative \
questions (known issues, ride impressions, comparisons).

Use both when a question needs it (e.g. "a light beginner naked bike under \
600cc, and what do owners say about reliability" needs filter_specs first, \
then search_reviews scoped to the results).

Important honesty constraints:
- MSRP is only populated for a minority of entries (bikez.com has no price \
field at all; this project falls back to a separately-sourced, partial \
MSRP). If a price-filtered query returns nothing, say the price data is \
sparse — do not imply the motorcycle doesn't exist or is out of budget.
- Review coverage is real but uneven: most motorcycles have zero forum \
comments (bikez.com's discussion activity varies a lot by model). If \
search_reviews returns nothing, say there's no owner discussion on record \
for that model rather than inventing an opinion.
- Forum comments belong to a model FAMILY, not a specific model-year: \
bikez.com shares one forum across every generation of a model, so a comment \
returned for a family covering 1970-2023 may be about any of those years. \
Attribute opinions to the family ("owners of the CB 250 line") and mention \
the comment's own posted_at date when it matters; never present a comment \
as being about one specific model-year.
- Never state a spec number that didn't come from a tool result.

Answer in the language the user asked in."""


def _tool_results_to_content(tool_use_id: str, results: list[dict]) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": str(results) if results else "No matching rows.",
    }


def run_agent(conn, client: Anthropic | None, user_message: str, history: list[dict] | None = None) -> tuple[str, list[dict]]:
    """Run one user turn through the agent loop.

    Returns (final_text, updated_history) so a caller (e.g. Gradio) can
    keep the conversation going across turns. `client` is ignored when
    AGENT_BACKEND=ollama (no Anthropic client needed for that path).
    """
    if BACKEND == "ollama":
        return _run_agent_ollama(conn, user_message, history)
    return _run_agent_anthropic(conn, client, user_message, history)


def _run_agent_anthropic(conn, client: Anthropic, user_message: str, history: list[dict] | None) -> tuple[str, list[dict]]:
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            final_text = "".join(block.text for block in response.content if block.type == "text")
            return final_text, messages

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            results = execute_tool(conn, block.name, block.input)
            tool_results.append(_tool_results_to_content(block.id, results))

        messages.append({"role": "user", "content": tool_results})


def _run_agent_ollama(conn, user_message: str, history: list[dict] | None) -> tuple[str, list[dict]]:
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})

    while True:
        response = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
                "tools": OLLAMA_TOOLS,
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        message = response.json()["message"]
        messages.append(message)

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return message.get("content", ""), messages

        for call in tool_calls:
            name = call["function"]["name"]
            arguments = call["function"]["arguments"]
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            results = execute_tool(conn, name, arguments)
            messages.append({
                "role": "tool",
                "content": str(results) if results else "No matching rows.",
            })

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

import anthropic
import requests
from anthropic import Anthropic

from bikefinder_rag.agent.tools import TOOLS, execute_tool

BACKEND = os.environ.get("AGENT_BACKEND", "anthropic")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral-small3.2")

# Hard cap on tool-call round-trips per user turn: a model stuck re-calling
# tools would otherwise loop forever on the visitor's API key.
MAX_TOOL_TURNS = 8

TURN_LIMIT_MESSAGE = (
    "I hit my tool-call limit for this question without reaching a final "
    "answer — try rephrasing or narrowing the question."
)

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

You have three tools:
- filter_specs: precise structured filtering (displacement, weight, power, \
seat height, category, brand, year, price).
- search_reviews: semantic search over real owner comments, for qualitative \
questions (known issues, ride impressions, comparisons).
- get_bike_details: the full factory spec sheet of ONE specific motorcycle \
(fuel capacity, cooling system, transmission, tires, brakes...), for specs \
filter_specs doesn't return.

Use several when a question needs it (e.g. "a light beginner naked bike \
under 600cc, and what do owners say about reliability" needs filter_specs \
first, then search_reviews scoped to the results).

Tool-call examples — follow these argument patterns exactly:
- "Show me custom/cruiser bikes from the 1980s" -> filter_specs \
{"category": "Custom/Cruiser", "min_year": 1980, "max_year": 1989} \
(a decade always sets BOTH min_year and max_year)
- "Quelles motos custom des annees 1950 ?" -> filter_specs \
{"category": "Custom/Cruiser", "min_year": 1950, "max_year": 1959}
- "What's the cheapest bike under 3000 EUR?" -> filter_specs \
{"max_msrp_eur": 3000, "order_by": "msrp_eur", "limit": 5}
- "How many Kawasaki bikes are in the database?" -> filter_specs \
{"brand": "Kawasaki", "count_only": true}
- "...and what do owners say about its reliability?" -> search_reviews \
{"query": "reliability problems breakdowns", "model": "<the bike being discussed>"}
- "What is the fuel capacity of the GSF 1200 Bandit?" -> get_bike_details \
{"model": "GSF 1200 Bandit"}

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

    for _ in range(MAX_TOOL_TURNS):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.AuthenticationError:
            return ("That Anthropic API key was rejected — check it at console.anthropic.com.", messages)
        except anthropic.APIError as exc:
            return (f"The Anthropic API returned an error ({type(exc).__name__}) — please try again.", messages)

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

    return TURN_LIMIT_MESSAGE, messages


def _run_agent_ollama(conn, user_message: str, history: list[dict] | None) -> tuple[str, list[dict]]:
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})

    for _ in range(MAX_TOOL_TURNS):
        try:
            response = requests.post(
                f"{OLLAMA_HOST}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
                    "tools": OLLAMA_TOOLS,
                    "stream": False,
                    # temperature 0: tool arguments shouldn't be sampled with
                    # noise. num_ctx: Ollama's default is small and it
                    # truncates silently — with this system prompt + tool
                    # schemas + spec-table results, the head of the context
                    # (the instructions) would fall off mid-loop.
                    "options": {"temperature": 0, "num_ctx": 16384},
                },
                timeout=120,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return (f"Could not reach the local Ollama server ({type(exc).__name__}) — is it running?", messages)
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

    return TURN_LIMIT_MESSAGE, messages

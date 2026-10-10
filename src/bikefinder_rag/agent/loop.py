"""Explicit agentic RAG loop: local Ollama or optional remote providers.

The loop is intentionally explicit (not hidden behind LangChain/LlamaIndex)
so the whole tool-call round-trip is visible and easy to reason about.

Three backends are supported, picked via the AGENT_BACKEND env var (or
per-call via run_agent's `provider`, which is how the Gradio demo routes
each visitor by the prefix of the key they pasted):
- "ollama" (default): local models (e.g. Mistral Small) for offline dev and
  testing after the initial model download, via Ollama's tool-calling API.
- "anthropic": visitor's own Anthropic key.
- "openrouter": visitor's own OpenRouter key (sk-or-...), OpenAI-style
  chat-completions API — one key, many models (OPENROUTER_MODEL).
"""

import json
import math
import os
import re
import time
import unicodedata

import anthropic
import requests
from anthropic import Anthropic

from bikefinder_rag.agent.tools import TOOLS, execute_tool

BACKEND = os.environ.get("AGENT_BACKEND", "ollama")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "mistral-small3.2")


def _positive_seconds_from_env(name: str, default: str) -> float:
    message = f"{name} must be a positive finite number of seconds."
    try:
        timeout = float(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(message) from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError(message)
    return timeout


OLLAMA_TIMEOUT_SECONDS = _positive_seconds_from_env("OLLAMA_TIMEOUT_SECONDS", "300")
OLLAMA_TURN_TIMEOUT_SECONDS = _positive_seconds_from_env("OLLAMA_TURN_TIMEOUT_SECONDS", "180")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-5")

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

SYSTEM_PROMPT = """You are a technical motorcycle catalog assistant in a local \
proof of concept. Answer only from the technical sheets returned by tools.
Owner opinions and reputation are deferred: do not retrieve them or use them \
as evidence for specifications. If asked, explain that this path covers specs.

You have two tools:
- filter_specs: structured filtering by brand, category, model year, \
displacement, power, torque, weight and seat height; also counts.
- get_bike_details: the original spec sheet for a model and an explicit year, \
including raw labels/units, source URL and collection timestamp.
For ANY characteristic of a named model and year, call get_bike_details, \
including a question asking only for torque or power. filter_specs has NO \
model argument and cannot retrieve a named model's sheet.

Tool-call examples — follow these argument patterns exactly:
- "Quelles Honda en 2000 ?" -> filter_specs \
{"brand": "Honda", "min_year": 2000, "max_year": 2000, "limit": 10}
- "Quelles motos custom des années 1950 ?" -> filter_specs \
{"category": "Custom/Cruiser", "min_year": 1950, "max_year": 1959}
- "Fiche technique de la Suzuki GSF 1200 N Bandit de 2000" -> get_bike_details \
{"brand": "Suzuki", "model": "GSF 1200 N Bandit", "year": 2000}
- "Compare la Bandit N et l'ER-5 Twister en 2000" -> TWO calls: \
get_bike_details {"brand": "Suzuki", "model": "GSF 1200 N Bandit", "year": 2000} and \
get_bike_details {"brand": "Kawasaki", "model": "ER-5 Twister", "year": 2000}.
Then present a table with model/variant, year, displacement, power, torque, \
weight with its original type, and the source of each sheet.

Evidence and scope constraints:
- For one year, set BOTH filter year bounds to that year. A decade also \
needs both bounds. Never substitute another year for an absent sheet.
- Ask for a model year if none is specified or already explicit in the \
conversation. For a comparison use the same year unless the user explicitly \
asks for different years. Never silently pick the newest available entries.
- Keep each returned model/variant separate. If several entries match a \
name, show the ambiguity and ask which one; do not combine their values.
- Cite each sheet's URL near its specifications or in the comparison table. \
Use the original labels, values, units and qualifications in specs. Numeric \
columns come from a legacy parser; power_hp conventions are not validated \
yet. Do not silently relabel HP as metric ch or convert/derive ratios.
- weight_kg mixes dry and wet weights. Report the original dry/wet label \
when available; otherwise say the weight type is undocumented. Do not rank \
mixed types or compute power/weight from the legacy columns.
- Missing values mean "non documenté", never zero, absence of equipment, \
or a value from general knowledge, another model, year or family.
An existing sheet with an unknown characteristic is still an existing sheet: \
cite its URL and mark only that requested characteristic undocumented.
- Answer the fields the user requested. Do not append an unsolicited list of \
other supposedly missing specifications. Before calling a requested field \
undocumented, check every original label in specs: Top speed documents vitesse \
maximale; Front brakes and Rear brakes document freinage; Output, Power output \
and Effect also document puissance. A field outside the numeric columns may \
still be fully documented in specs. Never describe it as absent on that basis.
- Do not call a performance measured unless its sheet documents a test; \
otherwise report it as a catalog specification with measurement status unknown.
- Catalog model year is not a launch date. Market, variant, launch date and \
production period are undocumented unless explicitly stated in the sheet.
Do not equate catalog model year with the actual year of manufacture.
- Category sources can conflict: expose category and category_fr separately \
if inconsistent. Do not treat either label as authoritative by assumption.
- Equipment/color filters are not implemented yet. A missing ABS mention \
does not mean no ABS. A list of selected sheets cannot establish which \
motorcycles in an entire year had an equipment. State this limitation.
Explain that the catalog-wide equipment FILTER is unavailable; individual \
raw sheets may document equipment. Do not claim all equipment data is absent.
- Results are bounded catalog selections, never an exhaustive market list. \
For exact catalog counts use count_only. If a tool reports truncation, ask \
for a narrower model. An error means a search was not executed, not no match.
If an argument is rejected, retry with the supported tool/arguments or report \
the search error. Never turn an error into missing data or a missing sheet.
- A successful get_bike_details call returning no sheet means \
"aucune fiche documentée dans ce catalogue pour ce \
modèle et ce millésime". Never say the motorcycle does not exist or was never \
produced merely because the catalog has no matching row.
- Price, licence eligibility and family recall data are outside these tools. \
Never infer A2 approval or restrictability from power and mixed weight alone.
- Never state a specification that did not come from a tool result.

Answer in the user's language, with concise tables for comparisons."""

SYSTEM_PROMPT += """

Required output for a technical sheet or comparison:
Return ONLY a Markdown table of the requested characteristics and a source row.
Use headers in the user's language (French: Caractéristique, Valeur documentée).
For one sheet use columns Characteristic and Documented value. For a comparison
use one column per exact model/year. Put an unknown value in its table cell only
when that requested characteristic has no evidence in specs. DO NOT append a
missing-data section or any paragraph about other characteristics. Do not add
seat height, brakes, colors or speed unless asked. The table ends at the source
row; include no speculative disclaimer after it.
For an absent sheet, missing year, ambiguous/truncated model, rejected search \
or unsupported filter, use a short clarification or explain the limitation \
instead. A tool error is never proof of an absent sheet.
"""


def _tool_results_to_content(tool_use_id: str, results: list[dict]) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": str(results) if results else "No matching rows.",
    }


def _technical_history(history: list[dict] | None) -> list[dict]:
    """Do not carry review evidence from legacy sessions into technical turns."""
    for message in history or []:
        for call in message.get("tool_calls") or []:
            if call.get("function", {}).get("name") == "search_reviews":
                return []
        # Anthropic histories use content blocks rather than tool_calls.
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                name = block.get("name") if isinstance(block, dict) else getattr(block, "name", None)
                if name == "search_reviews":
                    return []
    return list(history or [])


def _numeric_user_years(text: str, model: str | None = None) -> set[int]:
    """Narrow numeric policy, not natural-language date interpretation.

    Accept 1800..2199 after en/de/in, or as a numeric-only reply; year/année/
    millésime labels also permit positive numbers outside that band. Explicit
    ranges authorize their endpoints only. Ignore bare numbers inside prose,
    written-out dates and the LLM's model argument: a model identity such as
    Vulcan 2000 must never establish a date. Ambiguous shorthand needs a date
    label. Units, prices and numeric prefixes cannot establish dates either.
    """
    def fold(value):
        return "".join(char for char in unicodedata.normalize("NFKD", value).casefold()
                       if not unicodedata.combining(char))

    text = fold(text)
    number = r"[0-9]{1,4}(?!\w|[.,][0-9])"
    endpoints = rf"(?P<first>{number})(?:\s*(?:[-–—]|a|to)\s*(?P<last>{number}))?"
    numeric_reply = re.fullmatch(rf"\s*{endpoints}\s*[.!?,]?\s*", text)
    if numeric_reply:
        values = {int(value) for value in numeric_reply.groups() if value is not None}
        return values if all(1800 <= value <= 2199 for value in values) else set()

    labelled = re.compile(
        rf"\b(?P<label>model[ -]year|year|annee|millesime|en|de|in)\s*"
        rf"(?:(?:de|of)\s*|[:=]\s*)?{endpoints}"
    )
    years = set()
    for match in labelled.finditer(text):
        before, after = text[:match.start()], text[match.end():]
        if re.match(r"\s*(?:ccm?|cm3|kg|kw|hp|ps|ch|n[ .·]?m|rpm|eur|euros?)(?!\w)", after):
            continue
        if re.match(r"\s*[€$£]", after) or re.search(r"[€$£]\s*$", before):
            continue
        if re.search(r"\b(?:budget|prix|price|cost|power|puissance|weight|poids|cylindree|displacement)\s*(?:de|of|[:=])?\s*$", before):
            continue
        values = {int(match.group(key)) for key in ("first", "last") if match.group(key) is not None}
        if match.group("label") in {"en", "de", "in"}:
            values = {value for value in values if 1800 <= value <= 2199}
        years.update(value for value in values if value > 0)
    return years


def _user_text(message: dict) -> str:
    """Ignore tool_result blocks even though Anthropic gives them role=user."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text = []
        for block in content:
            kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            value = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
            if kind == "text" and isinstance(value, str):
                text.append(value)
        return " ".join(text)
    return ""


def _established_user_years(user_message: str, history: list[dict] | None, model: str | None = None) -> tuple[set[int], bool]:
    years = _numeric_user_years(user_message, model)
    if years:
        return years, False
    for message in reversed(history or []):
        if message.get("role") == "user":
            years = _numeric_user_years(_user_text(message), model)
            if years:
                return years, len(years) > 1
    return set(), False


def _tool_arguments(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value


def _detail_year_clarification(calls: list[tuple], user_message: str, history: list[dict] | None) -> str | None:
    """Preflight the whole batch before any tool execution or history append."""
    for name, arguments in calls:
        if name != "get_bike_details" or not isinstance(arguments, dict):
            continue
        year = arguments.get("year")
        # Missing/non-integer years remain the tool validator's responsibility.
        if type(year) is not int:
            continue
        years, ambiguous_history = _established_user_years(user_message, history)
        if ambiguous_history:
            return "Plusieurs millésimes ont été indiqués. Quel millésime souhaitez-vous utiliser pour cette fiche ?"
        if year not in years:
            if years:
                explicit = ", ".join(str(value) for value in sorted(years))
                return (f"J’ai bloqué un millésime différent de celui indiqué ({explicit}). "
                        "Quel millésime souhaitez-vous utiliser pour cette fiche ?")
            return "Quel millésime souhaitez-vous pour cette fiche ? Aucune année n’a été établie dans vos messages."
    return None


def _clarified_turn(messages: list[dict], clarification: str, *, anthropic_blocks=False) -> tuple[str, list[dict]]:
    content = [{"type": "text", "text": clarification}] if anthropic_blocks else clarification
    return clarification, [*messages, {"role": "assistant", "content": content}]


def run_agent(conn, client: Anthropic | None, user_message: str, history: list[dict] | None = None,
              *, provider: str | None = None, api_key: str | None = None) -> tuple[str, list[dict]]:
    """Run one user turn through the agent loop.

    Returns (final_text, updated_history) so a caller (e.g. Gradio) can
    keep the conversation going across turns. `provider` overrides
    AGENT_BACKEND for this call (the demo routes each visitor by their key
    prefix); `client` is only used on the anthropic path and is built from
    `api_key` when absent. The history format is provider-specific, so a
    session that switches provider should start from an empty history.
    """
    history = _technical_history(history)
    backend = provider or BACKEND
    if backend == "ollama":
        return _run_agent_ollama(conn, user_message, history)
    if backend == "openrouter":
        return _run_agent_openrouter(conn, api_key or "", user_message, history)
    if client is None and api_key:
        client = Anthropic(api_key=api_key)
    return _run_agent_anthropic(conn, client, user_message, history)


def _run_agent_anthropic(conn, client: Anthropic, user_message: str, history: list[dict] | None) -> tuple[str, list[dict]]:
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})
    clean_turn = list(messages)

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

        calls = [(block.name, block.input) for block in response.content if block.type == "tool_use"]
        clarification = _detail_year_clarification(calls, user_message, history)
        if clarification:
            return _clarified_turn(clean_turn, clarification, anthropic_blocks=True)
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


def _run_agent_openrouter(conn, api_key: str, user_message: str, history: list[dict] | None) -> tuple[str, list[dict]]:
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})
    clean_turn = list(messages)

    for _ in range(MAX_TOOL_TURNS):
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    # OpenRouter attribution headers (optional, shows in their stats).
                    "HTTP-Referer": "https://github.com/maax6/bikefinder-rag",
                    "X-Title": "Bikefinder RAG",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
                    "tools": OLLAMA_TOOLS,
                },
                timeout=120,
            )
        except requests.RequestException as exc:
            return (f"Could not reach OpenRouter ({type(exc).__name__}) — please try again.", messages)
        if response.status_code in (401, 403):
            return ("That OpenRouter API key was rejected — check it at openrouter.ai/keys.", messages)
        if not response.ok:
            return (f"OpenRouter returned an error (HTTP {response.status_code}) — please try again.", messages)

        message = response.json()["choices"][0]["message"]
        calls = [(call["function"]["name"], _tool_arguments(call["function"].get("arguments") or {}))
                 for call in message.get("tool_calls") or []]
        clarification = _detail_year_clarification(calls, user_message, history)
        if clarification:
            return _clarified_turn(clean_turn, clarification)
        messages.append(message)

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return message.get("content") or "", messages

        for call in tool_calls:
            arguments = _tool_arguments(call["function"].get("arguments") or {})
            results = execute_tool(conn, call["function"]["name"], arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id"),
                "content": str(results) if results else "No matching rows.",
            })

    return TURN_LIMIT_MESSAGE, messages


def _run_agent_ollama(conn, user_message: str, history: list[dict] | None) -> tuple[str, list[dict]]:
    deadline = time.monotonic() + OLLAMA_TURN_TIMEOUT_SECONDS
    messages = list(history or [])
    messages.append({"role": "user", "content": user_message})
    clean_turn = list(messages)
    budget_message = (
        f"The local Ollama turn exhausted its {OLLAMA_TURN_TIMEOUT_SECONDS:g}-second budget "
        "— narrow the question or increase OLLAMA_TURN_TIMEOUT_SECONDS and retry."
    )

    for _ in range(MAX_TOOL_TURNS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return budget_message, messages
        request_timeout = min(OLLAMA_TIMEOUT_SECONDS, remaining)
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
                timeout=request_timeout,
            )
            response.raise_for_status()
        except requests.ReadTimeout:
            if time.monotonic() >= deadline:
                return budget_message, messages
            return (
                f"The local Ollama response exceeded the {request_timeout:g}-second read timeout "
                "— model loading or generation may be too slow. Increase OLLAMA_TIMEOUT_SECONDS and retry.",
                messages,
            )
        except requests.RequestException as exc:
            if time.monotonic() >= deadline:
                return budget_message, messages
            return (f"Could not reach the local Ollama server ({type(exc).__name__}) — is it running?", messages)
        message = response.json()["message"]
        if time.monotonic() >= deadline:
            return budget_message, messages
        calls = [(call["function"]["name"], _tool_arguments(call["function"]["arguments"]))
                 for call in message.get("tool_calls") or []]
        clarification = _detail_year_clarification(calls, user_message, history)
        if clarification:
            return _clarified_turn(clean_turn, clarification)
        messages.append(message)

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return message.get("content", ""), messages

        for call in tool_calls:
            name = call["function"]["name"]
            arguments = _tool_arguments(call["function"]["arguments"])
            if time.monotonic() >= deadline:
                return budget_message, messages
            results = execute_tool(conn, name, arguments)
            messages.append({
                "role": "tool",
                "content": str(results) if results else "No matching rows.",
            })
            # Cooperative limit: an in-progress DB/CPU tool cannot be preempted.
            if time.monotonic() >= deadline:
                return budget_message, messages

    return TURN_LIMIT_MESSAGE, messages

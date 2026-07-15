#!/usr/bin/env python3
"""Score HOW a model calls the tools, separately from how well it writes.

RAGAS (layer 2) judges the final answer; this eval judges the trajectory
that produced it: did the model pick the right tool(s) for each golden
question, with sensible arguments, without hallucinated calls or hitting
the turn limit? Every check is a deterministic predicate over the recorded
tool calls — no LLM judge, so a failure here is unambiguous.

Pairs with eval_retrieval.py (layer 1, retrieval only): a model that fails
RAGAS but passes here writes badly from good data; one that fails here
never gave the retrieval layer a chance.

Run (one model per run; the report is named after the model):
    AGENT_BACKEND=ollama OLLAMA_MODEL=mistral-small3.2 EMBEDDER_DEVICE=cpu \\
      PYTHONPATH=src .venv/bin/python scripts/eval_tool_trajectory.py

Writes eval_results/trajectory/trajectory_<model>.json
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from bikefinder_rag.agent.loop import BACKEND, MODEL, OLLAMA_MODEL, TURN_LIMIT_MESSAGE, run_agent
from bikefinder_rag.db.client import get_connection

GOLDEN_PATH = Path(__file__).resolve().parent.parent / "src/bikefinder_rag/eval/golden_questions.json"
OUT_DIR = Path(__file__).resolve().parent.parent / "eval_results/trajectory"

KNOWN_TOOLS = {"filter_specs", "search_reviews", "get_bike_details"}


def extract_tool_calls(messages: list) -> list[dict]:
    """Normalize both transcript shapes to [{'name', 'args'}]: Anthropic
    stores tool_use blocks in assistant content, Ollama a tool_calls list."""
    calls = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)
                if block_type == "tool_use":
                    name = getattr(block, "name", None) or block.get("name")
                    args = getattr(block, "input", None) or block.get("input") or {}
                    calls.append({"name": name, "args": dict(args)})
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            args = function.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append({"name": function.get("name"), "args": args})
    return calls


# --- predicate helpers -----------------------------------------------------

def _named(calls, name):
    return [c for c in calls if c["name"] == name]


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def used(name):
    return lambda calls: bool(_named(calls, name))


def arg_between(name, key, lo, hi):
    """Some call of `name` has numeric arg `key` in [lo, hi] — tolerant on
    purpose: 'under 600cc' phrased as 599 or 600 are both right calls."""
    def check(calls):
        return any(lo <= v <= hi for c in _named(calls, name)
                   if (v := _num(c["args"].get(key))) is not None)
    return check


def arg_truthy(name, key):
    """Some call of `name` sets `key` to a truthy value (e.g. count_only)."""
    return lambda calls: any(c["args"].get(key) for c in _named(calls, name))


def call_mentions(name, pattern):
    """One single call of `name` matches `pattern` across its string args
    joined — the model referenced the right bike/topic in that call."""
    def check(calls):
        for c in _named(calls, name):
            text = " ".join(str(v) for v in c["args"].values() if isinstance(v, (str, int, float)))
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False
    return check


def all_calls_mention(name, pattern):
    """`pattern` appears somewhere across ALL calls of `name` combined —
    for comparisons where each bike may get its own call."""
    def check(calls):
        text = " ".join(
            str(v) for c in _named(calls, name)
            for v in c["args"].values() if isinstance(v, (str, int, float))
        )
        return bool(re.search(pattern, text, re.IGNORECASE))
    return check


# One list of (label, predicate) per golden question id. Labels are what
# the report prints, so word them as the expectation being tested.
EXPECTATIONS = {
    "struct-1": [
        ("calls filter_specs", used("filter_specs")),
        ("min displacement ~600", arg_between("filter_specs", "min_displacement_ccm", 500, 650)),
        ("max displacement ~900", arg_between("filter_specs", "max_displacement_ccm", 850, 950)),
        ("category naked", call_mentions("filter_specs", r"naked")),
    ],
    "struct-2": [
        ("calls filter_specs", used("filter_specs")),
        ("brand Harley", call_mentions("filter_specs", r"harley")),
        ("years bounded to the 1980s", arg_between("filter_specs", "min_year", 1975, 1985)),
    ],
    "struct-3": [
        ("calls filter_specs", used("filter_specs")),
        ("max weight ~130 kg", arg_between("filter_specs", "max_weight_kg", 100, 130)),
        ("category enduro/offroad", call_mentions("filter_specs", r"enduro|off.?road")),
    ],
    "struct-4": [
        ("calls filter_specs", used("filter_specs")),
        ("max seat height ~800 mm", arg_between("filter_specs", "max_seat_height_mm", 750, 800)),
        ("category sport", call_mentions("filter_specs", r"sport")),
    ],
    "struct-5": [
        ("calls filter_specs", used("filter_specs")),
        ("years bounded to the 1950s", arg_between("filter_specs", "min_year", 1945, 1955)),
        ("category custom/cruiser", call_mentions("filter_specs", r"custom|cruiser")),
    ],
    "narrative-1": [
        ("calls search_reviews", used("search_reviews")),
        ("targets the Electra Glide", call_mentions("search_reviews", r"electra")),
    ],
    "narrative-2": [
        ("calls search_reviews", used("search_reviews")),
        ("targets the BMW F 650", call_mentions("search_reviews", r"f\s*650")),
    ],
    "narrative-3": [
        ("calls search_reviews", used("search_reviews")),
        ("targets the Aprilia RS 125", call_mentions("search_reviews", r"rs\s*125")),
    ],
    "hybrid-1": [
        ("calls filter_specs", used("filter_specs")),
        ("calls search_reviews too", used("search_reviews")),
        ("max displacement ~600", arg_between("filter_specs", "max_displacement_ccm", 400, 650)),
        ("asks reviews about reliability", call_mentions("search_reviews", r"reliab|fiab|issue|problem")),
    ],
    "hybrid-2": [
        ("calls search_reviews", used("search_reviews")),
        ("covers the CBR 1000", all_calls_mention("search_reviews", r"cbr")),
        ("covers the GSF 1200 Bandit", all_calls_mention("search_reviews", r"bandit|gsf")),
    ],
    "honesty-1": [
        ("calls filter_specs", used("filter_specs")),
        ("filters on MSRP <= 3000", arg_between("filter_specs", "max_msrp_eur", 1, 3000)),
    ],
    "honesty-2": [
        ("calls search_reviews", used("search_reviews")),
        ("targets the BMW R 16", call_mentions("search_reviews", r"r\s*16")),
    ],
    "details-1": [
        ("calls get_bike_details", used("get_bike_details")),
        ("targets the GSF 1200 Bandit", call_mentions("get_bike_details", r"bandit|gsf")),
    ],
    "details-2": [
        ("calls get_bike_details", used("get_bike_details")),
        ("targets the RS 125", call_mentions("get_bike_details", r"rs\s*125")),
    ],
    "count-1": [
        ("calls filter_specs", used("filter_specs")),
        ("brand Kawasaki", call_mentions("filter_specs", r"kawasaki")),
        ("asks for a count", arg_truthy("filter_specs", "count_only")),
    ],
    "recall-1": [
        ("calls get_bike_details", used("get_bike_details")),
        ("targets the Multistrada", call_mentions("get_bike_details", r"multistrada")),
    ],
    "cote-1": [
        ("calls get_bike_details", used("get_bike_details")),
        ("targets the Bandit 1200", call_mentions("get_bike_details", r"bandit|gsf")),
    ],
    "a2-1": [
        ("calls filter_specs", used("filter_specs")),
        ("uses the a2_only filter", arg_truthy("filter_specs", "a2_only")),
    ],
}


def main() -> None:
    questions = json.loads(GOLDEN_PATH.read_text())
    model_tag = OLLAMA_MODEL if BACKEND == "ollama" else MODEL
    safe_tag = re.sub(r"[^A-Za-z0-9._-]", "-", model_tag)

    client = None
    if BACKEND != "ollama":
        from anthropic import Anthropic
        client = Anthropic()

    conn = get_connection()
    per_question = []
    try:
        for q in questions:
            print(f"[{q['id']}] {q['question']}", file=sys.stderr)
            answer, messages = run_agent(conn, client, q["question"], history=None)
            calls = extract_tool_calls(messages)

            checks = [
                {"label": label, "ok": bool(predicate(calls))}
                for label, predicate in EXPECTATIONS[q["id"]]
            ]
            unknown = sorted({c["name"] for c in calls} - KNOWN_TOOLS)
            result = {
                "id": q["id"],
                "type": q["type"],
                "question": q["question"],
                "n_tool_calls": len(calls),
                "calls": calls,
                "checks": checks,
                "unknown_tools": unknown,
                "hit_turn_limit": answer == TURN_LIMIT_MESSAGE,
                "all_ok": all(c["ok"] for c in checks) and not unknown and answer != TURN_LIMIT_MESSAGE,
                "answer_head": answer[:300],
            }
            per_question.append(result)
            status = "OK " if result["all_ok"] else "FAIL"
            failed = [c["label"] for c in checks if not c["ok"]]
            print(f"  -> {status} ({len(calls)} calls)" + (f" failed: {failed}" if failed else ""), file=sys.stderr)
    finally:
        conn.close()

    report = {
        "backend": BACKEND,
        "model": model_tag,
        "questions_ok": sum(r["all_ok"] for r in per_question),
        "questions_total": len(per_question),
        "checks_ok": sum(c["ok"] for r in per_question for c in r["checks"]),
        "checks_total": sum(len(r["checks"]) for r in per_question),
        "per_question": per_question,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"trajectory_{safe_tag}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != "per_question"}, indent=2))
    print(f"\nWritten to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

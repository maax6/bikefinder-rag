#!/usr/bin/env python3
"""Layer 1.75: hard-constraint violation rate of the agent's final answers.

The trajectory eval (layer 1.5) checks that constraints reach the tools as
arguments; this eval checks the thing a user actually experiences — does
any motorcycle *named in the final answer* violate the question's hard
constraints? A recommendation that sounds right but breaks the budget or
the displacement bracket is a failure whatever RAGAS thinks of its prose.

Method, fully deterministic (no LLM judge):
1. Ask the agent each constraint-bearing question.
2. Extract candidate motorcycle mentions from the answer (bold spans and
   list lines — the agent's formatting habit).
3. Resolve each mention against the motorcycles table (normalized
   word-by-word match, year-scoped when the answer states one).
4. Check every resolved bike against the question's constraint spec.

Three buckets per mention: satisfied, VIOLATED, unverifiable (the mention
didn't resolve to a database row — reported separately, since a made-up
model name is its own kind of failure).

Run (one model per run):
    AGENT_BACKEND=ollama OLLAMA_MODEL=mistral-small3.2 EMBEDDER_DEVICE=cpu \\
      PYTHONPATH=src .venv/bin/python scripts/eval_constraints.py

Writes eval_results/constraints/constraints_<model>_<UTC timestamp>.json
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from bikefinder_rag.agent.loop import BACKEND, run_agent
from bikefinder_rag.db.client import get_connection
from bikefinder_rag.eval.provenance import collect_provenance, dated_report_path

OUT_DIR = Path(__file__).resolve().parent.parent / "eval_results/constraints"

# Constraint-bearing questions (a subset mirrors the golden set; the last
# two are fresh phrasings so the eval isn't only testing memorized goldens).
# Constraint spec keys: min_/max_displacement_ccm, max_weight_kg,
# max_seat_height_mm, min_/max_year, max_msrp_eur, category (normalized
# substring against category OR category_fr).
QUESTIONS = [
    {"id": "cc-bracket", "q": "What naked bikes are there between 600cc and 900cc?",
     "constraints": {"min_displacement_ccm": 600, "max_displacement_ccm": 900, "category": "naked"}},
    {"id": "weight", "q": "List enduro/offroad bikes that weigh under 130 kg.",
     "constraints": {"max_weight_kg": 130}},
    {"id": "seat", "q": "List sport motorcycles with a seat height under 800mm.",
     "constraints": {"max_seat_height_mm": 800}},
    {"id": "decade-fr", "q": "Quelles motos custom/cruiser des annees 1950 sont dans la base ?",
     "constraints": {"min_year": 1950, "max_year": 1959}},
    {"id": "budget", "q": "What's the cheapest motorcycle under 3000 EUR in the database?",
     "constraints": {"max_msrp_eur": 3000}},
    {"id": "beginner-cc", "q": "A light beginner naked bike under 600cc, and what do owners say about reliability?",
     "constraints": {"max_displacement_ccm": 600}},
    {"id": "supermoto-fr", "q": "Quelle moto supermotard de plus de 600 cm3 me conseilles-tu, et a quel prix ?",
     "constraints": {"min_displacement_ccm": 600}},
    {"id": "a2-weight-fr", "q": "Une moto de moins de 500 cm3 et moins de 170 kg pour debuter, tu as quoi ?",
     "constraints": {"max_displacement_ccm": 500, "max_weight_kg": 170}},
]

_NORM = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())

# Bold spans and list lines are where the agent names bikes.
_MENTION_RE = re.compile(r"\*\*([^*\n]{3,80})\*\*|^\s*(?:\d+\.|[-•])\s+([^\n(]{3,80})", re.M)
_YEAR_RE = re.compile(r"\b(18[5-9]\d|19\d\d|20[0-2]\d)\b")
# Spec sub-lines under a bike bullet ('Displacement: 649 cc', 'Poids : 135
# kg') are list items too — not bike names.
_SPEC_LINE_RE = re.compile(
    r"^[-•\s]*(displacement|weight|power|torque|seat|fuel|price|prix|cylindr|poids|puissance|hauteur|couple)\b|^[-•\s]*[\w é]{3,25}:",
    re.I,
)


def load_catalog(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, brand, model, year, displacement_ccm, weight_kg,
                   seat_height_mm, msrp_eur, category, category_fr
            FROM motorcycles
        """)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def index_catalog(rows):
    """(normalized 'brand model' string, row) pairs for containment matching."""
    return [(_NORM(f"{r['brand']} {r['model']}"), r) for r in rows]


def extract_mentions(answer: str) -> list[tuple[str, int | None]]:
    """(mention text, stated year or None), deduplicated, order kept."""
    seen, out = set(), []
    for m in _MENTION_RE.finditer(answer):
        text = (m.group(1) or m.group(2) or "").strip().rstrip(":,.")
        if not text or _NORM(text) in seen or _SPEC_LINE_RE.match(text):
            continue
        # A mention needs at least one digit or two words to look like a
        # model name — filters headings like "Note" or "Specifications".
        if not (re.search(r"\d", text) or len(text.split()) >= 2):
            continue
        # Year: stated in the mention itself or right after ("(2015)").
        tail = answer[m.end():m.end() + 20]
        year_match = _YEAR_RE.search(text) or _YEAR_RE.search(tail)
        seen.add(_NORM(text))
        out.append((text, int(year_match.group()) if year_match else None))
    return out


def resolve(mention: str, year: int | None, catalog_index) -> list[dict]:
    """Rows whose full 'brand model' words are all contained in the mention
    OR whose mention words are all in 'brand model' — take the tightest
    (longest normalized name) matches only."""
    mention_norm = _NORM(_YEAR_RE.sub("", mention))
    if len(mention_norm) < 4:
        return []
    # Closest name length wins: 'Leoncino 800' must resolve to the
    # Leoncino 800, not to the longer 'Leoncino 800 Trail' that happens
    # to contain it.
    best_dist, best = None, []
    for name_norm, row in catalog_index:
        if year is not None and row["year"] != year:
            continue
        if mention_norm in name_norm or name_norm in mention_norm:
            dist = abs(len(name_norm) - len(mention_norm))
            if best_dist is None or dist < best_dist:
                best_dist, best = dist, [row]
            elif dist == best_dist:
                best.append(row)
    return best


def check(row: dict, constraints: dict) -> list[str]:
    """Known violations only; classify_matches handles absent data separately."""
    violated = []
    def num(field):
        v = row.get(field)
        return float(v) if v is not None else None

    for key, bound in constraints.items():
        if key == "category":
            label = _NORM(f"{row.get('category') or ''}|{row.get('category_fr') or ''}")
            if label and _NORM(bound) not in label:
                violated.append(f"category!={bound}")
        elif key.startswith("min_") and (v := num(key[4:] if key[4:] != "year" else "year")) is not None:
            if v < bound:
                violated.append(f"{key[4:]}={v}<{bound}")
        elif key.startswith("max_") and (v := num(key[4:] if key[4:] != "year" else "year")) is not None:
            if v > bound:
                violated.append(f"{key[4:]}={v}>{bound}")
    return violated


def classify_matches(rows: list[dict], constraints: dict) -> dict:
    """An unknown spec cannot vindicate a recommendation as satisfied."""
    candidates = []
    for row in rows:
        missing = []
        for key in constraints:
            field = key[4:] if key.startswith(("min_", "max_")) else key
            if field == "category":
                if not (row.get("category") or row.get("category_fr")):
                    missing.append(field)
            elif row.get(field) is None:
                missing.append(field)
        candidates.append((check(row, constraints), missing))
    for violations, missing in candidates:
        if not violations and not missing:
            return {"status": "satisfied", "violations": [], "missing_fields": []}
    unknown = [missing for violations, missing in candidates if not violations]
    if not candidates or unknown:
        return {"status": "unverifiable", "violations": [],
                "missing_fields": min(unknown, key=len) if unknown else []}
    violations, missing = min(candidates, key=lambda pair: len(pair[0]))
    return {"status": "violated", "violations": violations, "missing_fields": missing}


def main() -> None:
    client = None
    if BACKEND not in ("ollama",):
        from anthropic import Anthropic
        client = Anthropic()

    conn = get_connection()
    per_question = []
    try:
        metadata = collect_provenance(conn, generation=True)
        safe_tag = re.sub(r"[^A-Za-z0-9._-]", "-", metadata["generation"]["model"])
        catalog_index = index_catalog(load_catalog(conn))
        for spec in QUESTIONS:
            print(f"[{spec['id']}] {spec['q']}", file=sys.stderr)
            answer, _ = run_agent(conn, client, spec["q"], None)
            mentions = extract_mentions(answer)

            results = []
            for mention, year in mentions:
                rows = resolve(mention, year, catalog_index)
                results.append({
                    "mention": mention, "year": year,
                    **classify_matches(rows, spec["constraints"]),
                })

            counts = {s: sum(1 for r in results if r["status"] == s)
                      for s in ("satisfied", "violated", "unverifiable")}
            per_question.append({
                "id": spec["id"], "question": spec["q"],
                "constraints": spec["constraints"],
                "mentions": results, **counts,
                "answer_head": answer[:300],
            })
            print(f"  -> {counts}", file=sys.stderr)
    finally:
        conn.close()

    total = {s: sum(q[s] for q in per_question) for s in ("satisfied", "violated", "unverifiable")}
    verified = total["satisfied"] + total["violated"]
    report = {
        "metadata": metadata,
        "backend": BACKEND,
        "model": metadata["generation"]["model"],
        "mentions_total": verified + total["unverifiable"],
        **total,
        "violation_rate": round(total["violated"] / verified, 4) if verified else None,
        "unverifiable_rate": round(total["unverifiable"] / (verified + total["unverifiable"]), 4)
                             if (verified + total["unverifiable"]) else None,
        "per_question": per_question,
    }
    out_path = dated_report_path(OUT_DIR, f"constraints_{safe_tag}", metadata["created_at_utc"])
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != "per_question"}, indent=2))
    print(f"\nWritten to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

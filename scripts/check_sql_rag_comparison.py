#!/usr/bin/env python3
"""Check frozen inputs, reference IDs and schedule without invoking models."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3

from prepare_sql_rag_comparison import DEFAULT_OUT, digest


def check(root, *, verify_source=True):
    root = Path(root)
    read = lambda name: json.loads((root / name).read_text(encoding="utf-8"))
    manifest = read("manifest.json")
    for name, expected in manifest["files"].items():
        if Path(name).name != name or digest(root / name) != expected:
            raise ValueError(f"Frozen artifact checksum mismatch: {name}")
    tools = read("tools.json")
    names = {t["name"] for t in tools["tools"]}
    if len(names) != 6 or any(t["input_schema"].get("additionalProperties") is not False for t in tools["tools"]):
        raise ValueError("Expected six closed tool schemas")
    questions = read("questions.json")["cases"]
    public = read("model-inputs.json")["cases"]
    if public != [{"id": c["id"], "turns": c["turns"]} for c in questions]:
        raise ValueError("Model inputs differ from questions or leak evaluation material")
    if len(questions) != 40 or len({c["id"] for c in questions}) != 40:
        raise ValueError("Question panel is not forty unique cases")
    if Counter(c["split"] for c in questions) != {"dev": 24, "reserved": 16}:
        raise ValueError("Invalid dev/reserved split")
    refs = read("references.private.json")
    if {r["id"] for r in refs["cases"]} != {c["id"] for c in questions}:
        raise ValueError("References do not cover every question")
    protocol = read("protocol.json")
    if refs["source_sha256"] != manifest["source_sha256"] or protocol["corpus"]["sha256"] != manifest["source_sha256"]:
        raise ValueError("Reference corpus fingerprints disagree")
    candidates = read("candidates.json")["candidates"]
    scheduled = read("run-plan.json")["sessions"]
    expected = {(c["id"], q["id"], repeat) for c in candidates for q in questions for repeat in range(1, 4)}
    actual = [(s["candidate_id"], s["case_id"], s["repeat"]) for s in scheduled]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("Candidate schedules are unequal or duplicated")
    by_id = {q["id"]: q for q in questions}
    if any(s["split"] != by_id[s["case_id"]]["split"] or s["turns"] != len(by_id[s["case_id"]]["turns"]) for s in scheduled):
        raise ValueError("Schedule does not preserve split/session turns")
    if verify_source:
        source = Path(protocol["corpus"]["snapshot"])
        if digest(source) != manifest["source_sha256"]:
            raise ValueError("Source corpus changed")
        conn = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            for ref in refs["cases"]:
                def visit(value):
                    if isinstance(value, dict):
                        if {"id", "source_url", "source_sha256", "brand", "model", "year"} <= value.keys():
                            row = conn.execute("SELECT url,source_sha256,brand,model,year,record FROM objects WHERE id=?", [value["id"]]).fetchone()
                            if row is None or list(row[:5]) != [value[k] for k in ["source_url", "source_sha256", "brand", "model", "year"]]:
                                raise ValueError("Reference fiche identity/source mismatch")
                            record = json.loads(row[5])
                            for p in value.get("passages", []):
                                n = int(p["id"].rsplit(":", 1)[1])
                                if p["id"] != f"{value['id']}:section:{n}" or record["technical_sections"][n] != {"section": p["section"], "text": p["text"]}:
                                    raise ValueError("Reference passage is not the original source")
                        for child in value.values():
                            visit(child)
                    elif isinstance(value, list):
                        for child in value:
                            visit(child)
                visit(ref["expected"])
                if "count" in ref["expected"]:
                    e = ref["expected"]
                    if e["count"] != len(set(e["matching_ids"])):
                        raise ValueError("Reference count differs from contributing IDs")
            for name, expected_hash in protocol["retrieval"]["file_sha256"].items():
                if digest(Path(protocol["retrieval"]["prepared_index"]) / name) != expected_hash:
                    raise ValueError(f"Retrieval index changed: {name}")
        finally:
            conn.close()
    return {"status": "valid_preparation_not_model_evaluation", "tools": len(names), "cases": len(questions),
            "sessions": len(scheduled), "model_input_leakage": False, "source_verified": verify_source}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(json.dumps(check(args.pack), ensure_ascii=False, indent=2))

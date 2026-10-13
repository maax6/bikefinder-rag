#!/usr/bin/env python3
"""Validate frozen questions through the real chat, then inspect its evidence.

API-first timings include Jev, SQL, local BGE and the chat queue. Separate
inspection is warm and must not be reported as first-response latency.
Assertions check provenance and omissions; answers also need source review.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time

from dotenv import load_dotenv
from gradio_client import Client
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def receipt_paths():
    return set(Path(os.getenv("BIKEFINDER_RAG_ROUTER_CACHE", str(ROOT / "data/technical/rag-router-cache"))).glob("*.json"))


def content_text(visible):
    content = visible[-1]["content"]
    return content if isinstance(content, str) else "\n".join(b.get("text", "") for b in content)


def validate(case, answer, routing, expected):
    evidence = routing.get("evidence", {})
    sources = evidence.get("sources", [])
    wanted = {m["object_id"] for m in case["models"]}
    found = {s["object_id"] for s in sources}
    checks = {"api_matches_inspection": answer == routing.get("answer"),
              "exact_identities": found == wanted,
              "no_legal_certification": not evidence.get("legal_certification", False),
              "no_runtime_error": routing.get("route") != "rag_error"}
    if wanted:
        checks["visible_legal_limit"] = "je ne certifie pas" in answer
        checks["correct_citations"] = all(expected[s["object_id"]]["source_url"] in answer for s in sources)
        checks["intact_source_passages"] = all(
            p["original_text"] == expected[s["object_id"]]["sections"].get(p["id"])
            and p["object_id"] == s["object_id"] and p["year"] == expected[s["object_id"]]["year"]
            and p["source_sha256"] == expected[s["object_id"]]["source_sha256"]
            for s in sources for p in s["passages"])
        checks["requested_fields_considered"] = all(
            set(case.get("requested_fields", [])).issubset(s["coverage"]) for s in sources)
        checks["facts_or_visible_gaps"] = all(
            s["coverage"].get(f, {}).get("covered") or
            any(m.get("field") == f and m.get("object_id") == s["object_id"] for m in evidence.get("missing", []))
            for s in sources for f in case.get("requested_fields", []))
        checks["bge_local_executed"] = evidence.get("retrieval_executed", False) and all(
            r.get("model") == "BAAI/bge-m3" and r.get("query_encoding_seconds", 0) > 0
            for r in evidence.get("retrievals", []))
        # Values below come from the original sections, not the renderer.
        for s in sources:
            original = expected[s["object_id"]]
            for field, pattern in [("power_ch", r"\b\d+(?:[,.]\d+)? ch à [\d ]+ tr/min"),
                                   ("seat_height_mm", r"Hauteur de selle : ([\d ]+ mm)")]:
                if field in case.get("requested_fields", []):
                    match = re.search(pattern, " ; ".join(original["sections"].values()))
                    checks[f"original_{field}_{s['object_id']}"] = bool(match and (match[1] if field == "seat_height_mm" else match[0]) in answer)
            if "license" in case.get("requested_fields", []):
                mentions = [text for text in original["sections"].values() if "permis" in text.lower()]
                checks[f"original_license_{s['object_id']}"] = bool(mentions) and all(t in answer for t in mentions)
                if not any(re.search(r"\ba2\b", t, re.I) for t in original["sections"].values()):
                    checks[f"missing_A2_marked_{s['object_id']}"] = any(
                        m.get("field") == "a2_mention" and m.get("object_id") == s["object_id"] for m in evidence.get("missing", []))
    else:
        checks["no_bge_on_unresolved_identity"] = not evidence.get("retrieval_executed", False)
    if case.get("expected_year_clarification"):
        checks["asks_year"] = "millésime" in answer
    if case.get("expected_identity_missing"):
        checks["missing_exact_year"] = str(case["requested_year"]) in answer and "substituée" in answer
    if case.get("expected_authority_missing"):
        checks["missing_authority"] = any(m.get("kind") == "authority" for m in evidence.get("missing", []))
    if case.get("expected_no_certification") or case.get("expected_certificate_missing") or case.get("expected_individual_state_missing"):
        checks["missing_authority"] = any(m.get("kind") == "authority" for m in evidence.get("missing", []))
    for field in case.get("expected_missing_fields", []):
        checks[f"precise_{field}_not_claimed_complete"] = bool(sources) and all(
            not s["coverage"].get(field, {}).get("covered", False) and
            any(m.get("field") == field and m.get("object_id") == s["object_id"] for m in evidence.get("missing", []))
            for s in sources)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:7861/")
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Refusing to overwrite an earlier validation")
    load_dotenv(ROOT / ".env")
    if os.getenv("BIKEFINDER_JEV_ROUTER") != "1" or os.getenv("BIKEFINDER_JEV_RAG") != "1":
        parser.error("Jev router and local RAG must be enabled")
    from bikefinder_rag.agent.rag_router import route_question, PROTOCOL
    from bikefinder_rag.db.client import get_connection
    from bikefinder_rag.catalog.enriched import _rows
    from bikefinder_rag.embeddings.embedder import MODEL_REVISION
    dataset = json.loads(args.questions.read_text())
    cases = dataset["questions"]
    conn = get_connection()
    expected = {}
    try:
        for case in cases:
            for m in case["models"]:
                row, = _rows(conn, "SELECT id,brand,model,year,source_url,source_sha256,record FROM technical_fiches WHERE id=%s", [m["object_id"]])
                assert (row["brand"], row["model"], row["year"]) == (m["brand"], m["model"], m["year"])
                expected[m["object_id"]] = {**{k: row[k] for k in ["brand", "model", "year", "source_url", "source_sha256"]},
                    "sections": {f"{row['id']}:section:{n}": s["text"] for n, s in enumerate(row["record"]["technical_sections"])}}
        corpus = _rows(conn, "SELECT count(*) AS fiches FROM technical_fiches", [])[0]
        results = []
        metadata = {"schema": "jev-rag-chat-validation-v1", "label": args.label,
                    "started_at": datetime.now(timezone.utc).isoformat(), "api_url": args.url,
                    "questions_sha256": sha(args.questions), "author": dataset["author"],
                    "previous_benchmark_questions_reused": dataset["previous_benchmark_questions_reused"],
                    "protocol": PROTOCOL, "embedding_revision": MODEL_REVISION, "corpus": corpus,
                    "latency_method": "API first; route inspected separately afterwards with warmed decision/document caches",
                    "remote_inference": "Jev only; no generator or external quality judge",
                    "decision_cache": os.getenv("BIKEFINDER_RAG_ROUTER_CACHE", "data/technical/rag-router-cache"),
                    "code_sha256": {f: sha(ROOT / f) for f in [
                        "src/bikefinder_rag/agent/rag_router.py", "src/bikefinder_rag/catalog/technical_rag.py",
                        "src/bikefinder_rag/embeddings/embedder.py", "src/bikefinder_rag/agent/loop.py",
                        "src/bikefinder_rag/agent/jev_router.py", "src/bikefinder_rag/app.py", "scripts/evaluate_jev_rag.py"]},
                    "expected_sources": expected}
        args.out.parent.mkdir(parents=True, exist_ok=True)

        def run(client, case, visible, history):
            before = receipt_paths()
            start = time.perf_counter()
            visible = client.predict(case["question"], visible, "", api_name="/chat")
            seconds = time.perf_counter() - start
            after = receipt_paths()
            answer = content_text(visible)
            start = time.perf_counter()
            routing = route_question(conn, case["question"], history)
            inspection = time.perf_counter() - start
            history += [{"role": "user", "content": case["question"]},
                        {"role": "assistant", "content": answer, "_catalog_plan": routing.get("plan")}]
            return visible, history, {"id": case["id"], "question": case["question"], "answer": answer,
                "api_seconds": seconds, "inspection_seconds": inspection, "routing": routing,
                "new_successful_jev_receipts": len(after - before),
                "receipt_ids": sorted(p.stem for p in after - before),
                "checks": validate(case, answer, routing, expected)}

        for case in cases:
            client = Client(args.url, verbose=False)
            visible, history, seed = [], [], None
            if case.get("history_seed"):
                seeded = next(q for q in cases if q["id"] == case["history_seed"])
                visible, history, seed = run(client, seeded, visible, history)
            visible, history, result = run(client, case, visible, history)
            if seed:
                result["history_seed_result"] = seed
            results.append(result)
            timings = [r["api_seconds"] for r in results]
            summary = {"completed": len(results), "automated_checks_passed": sum(all(r["checks"].values()) for r in results),
                       "routes": dict(Counter(r["routing"]["route"] for r in results)),
                       "api_p50_seconds": float(np.percentile(timings, 50)),
                       "api_p95_seconds": float(np.percentile(timings, 95)), "api_max_seconds": max(timings),
                       "new_successful_jev_receipts": sum(r["new_successful_jev_receipts"] for r in results)}
            args.out.write_text(json.dumps({**metadata, "summary": summary, "results": results}, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"id": case["id"], "route": result["routing"]["route"], "api_seconds": result["api_seconds"],
                              "new_jev_receipts": result["new_successful_jev_receipts"],
                              "failed_checks": [k for k, v in result["checks"].items() if not v]}), flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

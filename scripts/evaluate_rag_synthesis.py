"""Validate actual Gradio turns without a second routing/generation invocation.

Use --serve to start an isolated front with an explicit local trace directory.
The wrapper records the state returned by that very request; no production
telemetry or external tracing is introduced. Then run --questions/--out.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import uuid


def serve(port, traces, questions_paths):
    from bikefinder_rag import app
    original = app.run_agent
    observed_questions = {case["question"] for path in questions_paths
                          for case in json.loads(path.read_text())["cases"]}
    traces.mkdir(parents=True, exist_ok=True)
    def observed(conn, client, question, history, **kwargs):
        started = time.perf_counter()
        answer, completed = original(conn, client, question, history, **kwargs)
        if question not in observed_questions:
            return answer, completed
        state = completed[-1]
        receipt = {"question": question, "answer": answer, "seconds": time.perf_counter() - started,
                   "timestamp": datetime.now(timezone.utc).isoformat(),
                   **{k: v for k, v in state.items() if k.startswith("_catalog_")}}
        path = traces / (uuid.uuid4().hex + ".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)
        return answer, completed
    app.run_agent = observed
    app.launch_chatbot(server_port=port)


def text_content(message):
    value = message["content"]
    if isinstance(value, list):
        return "\n".join(b.get("text", "") for b in value if isinstance(b, dict))
    return str(value)


def evaluate(url, questions_path, traces, out):
    import numpy as np
    from gradio_client import Client
    if out.exists():
        raise FileExistsError("Keep prior runs immutable; choose a new output path")
    questions_bytes = questions_path.read_bytes()
    cases = json.loads(questions_bytes)["cases"]
    results = []
    for case in cases:
        before = set(traces.glob("*.json"))
        client = Client(url, verbose=False)
        started = time.perf_counter()
        visible = client.predict(case["question"], [], "", api_name="/chat")
        elapsed = time.perf_counter() - started
        answer = text_content(visible[-1])
        receipts = [json.loads(p.read_text()) for p in set(traces.glob("*.json")) - before]
        matches = [r for r in receipts if r["question"] == case["question"] and r["answer"] == answer]
        if len(matches) != 1:
            raise RuntimeError("Cannot bind Gradio answer to exactly one server receipt")
        receipt = matches[0]
        generation = receipt.get("_catalog_generation") or {}
        evidence = receipt.get("_catalog_evidence") or {}
        actual_ids = [[s["brand"], s["model"], s["year"]] for s in evidence.get("sources", [])]
        checks = {"actual_server_answer": True,
                  "requested_identities": actual_ids == case["identities"],
                  "requested_tokens": all(t.casefold() in answer.casefold() for t in case["required"])}
        if case["kind"] == "generation":
            checks.update(local_generation_published=generation.get("published") is True,
                          bge_executed=evidence.get("retrieval_executed") is True,
                          citations=all(s["source_url"] in answer for s in evidence.get("sources", [])),
                          missing_visible=not evidence.get("missing") or "Preuves manquantes" in answer,
                          a2_limit=not (receipt.get("_catalog_plan") or {}).get("a2_context") or "je ne certifie pas" in answer)
        else:
            checks["no_generator"] = not generation.get("call_attempted")
        results.append({**case, "api_seconds": elapsed, "checks": checks, "receipt": receipt})
        durations = [r["api_seconds"] for r in results]
        report = {"timestamp": datetime.now(timezone.utc).isoformat(), "front_url": url,
                  "questions_sha256": hashlib.sha256(questions_bytes).hexdigest(),
                  "method": "Fresh Gradio session for each question, server receipt matched to the actual frontend answer; root-authored curated cases, not independent or blind",
                  "summary": {"completed": len(results), "checks_passed": sum(all(r["checks"].values()) for r in results),
                      "published_local_generation": sum((r["receipt"].get("_catalog_generation") or {}).get("published", False) for r in results),
                      "p50_seconds": float(np.percentile(durations, 50)), "p95_seconds": float(np.percentile(durations, 95)),
                      "max_seconds": max(durations)}, "results": results}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"id": case["id"], "seconds": round(elapsed, 2), "route": receipt.get("_catalog_route"),
                          "failed": [k for k, v in checks.items() if not v], "generation_error": generation.get("error")}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=7862)
    parser.add_argument("--url", default="http://127.0.0.1:7862/")
    parser.add_argument("--traces", type=Path, required=True)
    parser.add_argument("--questions", type=Path)
    parser.add_argument("--observe-questions", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.serve:
        if not args.observe_questions:
            parser.error("--observe-questions is required: only named test questions are recorded")
        serve(args.port, args.traces, args.observe_questions)
    else:
        if not args.questions or not args.out:
            parser.error("--questions and --out are required when evaluating")
        evaluate(args.url, args.questions, args.traces, args.out)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Run common-tool smoke checks or a frozen candidate evaluation, saving receipts.

Smoke mode never opens references or reserved questions. Compare mode requires
a successful full service verification and preserves each initial execution.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from dotenv import load_dotenv

from bikefinder_rag.agent.sql_rag_adapters import create_adapter
from bikefinder_rag.agent.sql_rag_session import CatalogSession
from bikefinder_rag.agent.sql_rag_contract import TOOLS
from bikefinder_rag.agent.sql_rag_output import SUBMIT_ANSWER
from bikefinder_rag.catalog.sql_rag_service import CatalogService, digest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK = ROOT / "eval_results/technical/sql-rag-comparison-20261014"
DEFAULT_PROJECTION = ROOT / "data/technical/sql-rag-service-v2/catalog.sqlite3"


def run(args):
    if args.out.exists():
        raise FileExistsError("Keep first runs; choose a new report")
    load_dotenv(ROOT / ".env")
    # Only model-inputs, prompt, tools and execution protocol are allowed inputs.
    manifest = json.loads((args.pack / "manifest.json").read_text())
    for name in ["model-inputs.json", "system-prompt.txt", "tools.json", "protocol.json", "answer-channel.json"]:
        if digest(args.pack / name) != manifest["files"][name]:
            raise ValueError("Frozen model inputs changed")
    protocol = json.loads((args.pack / "protocol.json").read_text())
    if json.loads((args.pack / "tools.json").read_text())["tools"] != TOOLS:
        raise ValueError("Active tool definitions differ from frozen pack; prepare a revised pack")
    if json.loads((args.pack / "answer-channel.json").read_text()) != SUBMIT_ANSWER:
        raise ValueError("Active answer channel differs from frozen pack")
    prompt = (args.pack / "system-prompt.txt").read_text()
    if args.mode == "compare":
        if not args.verification:
            raise ValueError("Compare mode requires --verification from the real-corpus check")
        if not args.smoke_verification:
            raise ValueError("Compare mode requires --smoke-verification for this exact provider/model")
        smoke = json.loads(args.smoke_verification.read_text())
        if (smoke.get("provider"), smoke.get("model"), smoke.get("corpus_sha256")) != (args.provider, args.model, protocol["corpus"]["sha256"]) or not smoke.get("results") or any(r["status"] != "completed" for r in smoke["results"]):
            raise ValueError("This provider/model has not passed a real end-to-end smoke check")
        for key, path in [("service_sha256", "catalog/sql_rag_service.py"), ("adapter_sha256", "agent/sql_rag_adapters.py"),
                          ("session_sha256", "agent/sql_rag_session.py"), ("retrieval_sha256", "catalog/sql_rag_retrieval.py")]:
            if smoke.get(key) != digest(ROOT / "src/bikefinder_rag" / path):
                raise ValueError("Implementation changed after model smoke verification")
        verification = json.loads(args.verification.read_text())
        if verification["status"] != "passed" or verification["source_sha256"] != protocol["corpus"]["sha256"] or len(verification["covered_cases"]) != 40 or verification.get("validated_index_passages") != protocol["corpus"]["counts"]["passages"]:
            raise ValueError("Full service verification has not passed")
        expected_code = verification.get("implementation_sha256", {})
        if len(expected_code) != 3 or any(digest(ROOT / p) != sha for p, sha in expected_code.items()):
            raise ValueError("Service changed after verification; rerun the real-corpus check")
    for name, expected in protocol["retrieval"]["file_sha256"].items():
        if digest(Path(protocol["retrieval"]["prepared_index"]) / name) != expected:
            raise ValueError("Frozen retrieval file changed")
    start = time.perf_counter()
    service = CatalogService(protocol["corpus"]["snapshot"], args.projection, index=protocol["retrieval"]["prepared_index"])
    service.index.encoder("Préparation de la recherche locale dans le catalogue.")
    prepared_seconds = time.perf_counter() - start
    adapter = create_adapter(args.provider, args.model)
    model_warmup = adapter.warmup(prompt) if args.provider == "ollama" else None
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "mode": args.mode, "provider": args.provider, "model": args.model,
              "corpus_sha256": service.snapshot_id, "pack_manifest_sha256": digest(args.pack / "manifest.json"),
              "service_sha256": digest(ROOT / "src/bikefinder_rag/catalog/sql_rag_service.py"),
              "adapter_sha256": digest(ROOT / "src/bikefinder_rag/agent/sql_rag_adapters.py"),
              "session_sha256": digest(ROOT / "src/bikefinder_rag/agent/sql_rag_session.py"),
              "retrieval_sha256": digest(ROOT / "src/bikefinder_rag/catalog/sql_rag_retrieval.py"),
              "preparation_seconds": prepared_seconds, "model_warmup": model_warmup, "streamed": False, "results": []}
    budget = protocol["budget"]

    def new_session():
        return CatalogSession(service, adapter, prompt, rounds=budget["model_rounds_per_turn"], calls=budget["total_tool_calls_per_turn"],
                              timeout=budget["timeout_seconds_per_turn"], context_characters=budget["context_characters"])

    def save():
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    try:
        if args.mode == "smoke":
            session = new_session()
            for question in args.question or ["Quelle est la hauteur de selle de la Honda CB 500 F 2020 ?"]:
                receipt = session.ask(question)
                receipt.update(case_id="smoke", repeat=1, candidate_id=f"{args.provider}:{args.model}")
                report["results"].append(receipt)
                save()
                print(json.dumps({"status": receipt["status"], "seconds": round(receipt["timing"]["full_answer_seconds"], 3), "answer": receipt["answer"], "error": receipt["error"], "tools": [c["name"] for c in receipt["calls"]]}, ensure_ascii=False), flush=True)
                if receipt["status"] != "completed":
                    break
        else:
            inputs = {c["id"]: c["turns"] for c in json.loads((args.pack / "model-inputs.json").read_text())["cases"]}
            schedule = json.loads((args.pack / "run-plan.json").read_text())["sessions"]
            if not args.candidate_id:
                raise ValueError("Compare mode requires explicit --candidate-id; a provider/runtime change needs a new candidate label")
            candidates = json.loads((args.pack / "candidates.json").read_text())["candidates"]
            declared = next((c for c in candidates if c["id"] == args.candidate_id), None)
            if not declared or (declared["provider"], declared["model"]) != (args.provider, args.model):
                raise ValueError("Provider/model differs from frozen candidate; prepare a revised pack first")
            for planned in schedule:
                if planned["candidate_id"] != args.candidate_id or planned["split"] != args.split:
                    continue
                session = new_session()
                for question in inputs[planned["case_id"]]:
                    receipt = session.ask(question)
                    receipt.update(case_id=planned["case_id"], repeat=planned["repeat"], candidate_id=args.candidate_id)
                    report["results"].append(receipt)
                    save()
                    print(json.dumps({"case": planned["case_id"], "repeat": planned["repeat"], "status": receipt["status"], "seconds": round(receipt["timing"]["full_answer_seconds"], 3)}, ensure_ascii=False), flush=True)
                    if receipt["status"] != "completed":
                        break
        return all(r["status"] == "completed" for r in report["results"]) and bool(report["results"])
    finally:
        adapter.close()
        service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["smoke", "compare"], default="smoke")
    parser.add_argument("--provider", choices=["ollama", "openai_responses", "gemini", "openrouter"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--candidate-id")
    parser.add_argument("--split", choices=["dev", "reserved"], default="dev")
    parser.add_argument("--question", action="append")
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--projection", type=Path, default=DEFAULT_PROJECTION)
    parser.add_argument("--verification", type=Path)
    parser.add_argument("--smoke-verification", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    raise SystemExit(0 if run(parser.parse_args()) else 1)

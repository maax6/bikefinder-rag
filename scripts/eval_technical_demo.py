#!/usr/bin/env python3
"""Sequential live acceptance probes through Gradio; no judge or model ranking."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import requests
from gradio_client import Client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
CASES = {
    "sheet": ("Donne la fiche technique de la Suzuki GSF 1200 N Bandit de 2000 : cylindrée, puissance, couple, poids et type de poids, unités et source.", [("Suzuki", "GSF 1200 N Bandit", 2000)]),
    "comparison": ("Compare la Suzuki GSF 1200 N Bandit et la Kawasaki ER-5 Twister de 2000 : cylindrée, puissance, couple et poids sec, avec unités et sources.", [("Suzuki", "GSF 1200 N Bandit", 2000), ("Kawasaki", "ER-5 Twister", 2000)]),
    "missing_torque": ("Quel couple est documenté pour l'Aprilia RSV Mille SP de 2000 ? Donne uniquement la valeur sourcée ou précise qu'elle n'est pas documentée.", [("Aprilia", "RSV Mille SP", 2000)]),
    "missing_year": ("Quelle est la puissance de la Suzuki GSF 1200 N Bandit ?", []),
    "absent_sheet": ("Donne la puissance et le couple de la Suzuki GSF 1200 N Bandit de 2025, à partir du catalogue uniquement.", [("Suzuki", "GSF 1200 N Bandit", 2025)]),
    "abs_catalog_scope": ("Quelles motos avaient l'ABS en 2000 ? Donne toutes les motos du catalogue qui l'avaient et distingue série et option.", []),
    "launch_date": ("Quelle est la date de lancement exacte de la Suzuki GSF 1200 N Bandit de 2000 ? Ne confonds pas millésime et date de lancement.", [("Suzuki", "GSF 1200 N Bandit", 2000)]),
    "reviews_deferred": ("Quels avis de propriétaires prouvent la puissance de la Bandit 1200 de 2000 ?", []),
}


def text_answer(result):
    content = result[-1]["content"]
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", "") for block in content if block.get("type") == "text")


def positive_finite_seconds(value):
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number of seconds") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number of seconds")
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=CASES, help="Select cases (default: all).")
    parser.add_argument("--demo-url", default="http://127.0.0.1:7860/")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--gradio-timeout-seconds", type=positive_finite_seconds, default=240,
                        help="Maximum wait for a Gradio job result (default: 240 s); not a server execution deadline.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from bikefinder_rag.agent.tools import get_bike_details
    from bikefinder_rag.db.client import get_connection

    now = datetime.now(timezone.utc)
    output = args.output or ROOT / "eval_results/technical" / f"live_gradio_{now.strftime('%Y%m%dT%H%M%S.%fZ')}.json"
    paths = ["src/bikefinder_rag/agent/loop.py", "src/bikefinder_rag/agent/tools.py", "src/bikefinder_rag/app.py", "scripts/eval_technical_demo.py"]
    report = {
        "created_at": now.isoformat(),
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "runtime_files_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths},
        "transport": "Real Gradio /chat, local Ollama and PostgreSQL; fresh session per case.",
        "gradio_wait_timeout_seconds": args.gradio_timeout_seconds,
        "cases": [], "manual_review_pending": True,
        "stopped_after_api_error": None, "unrun_cases": [],
        "limitations": ["One pass of selected acceptance cases; not a model ranking or latency benchmark.",
                         "No automatic verification of every free-text claim.",
                         "Gradio does not expose tool transcripts; expected evidence is read independently.",
                         "Source hashes describe files on disk; reload the demo before evaluating a code change.",
                         "The Gradio timeout bounds client result waiting, not total evaluation time or server execution.",
                         "Cancellation is best effort and does not prove that a server-side job stopped; after an API error no further cases are submitted. Check the server before another run."],
    }

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    save()
    case_ids = list(args.case or CASES)
    try:
        for field, endpoint in (("ollama_version", "/api/version"),
                                ("installed_models", "/api/tags"),
                                ("model_runtime_before", "/api/ps")):
            response = requests.get(args.ollama_url + endpoint, timeout=5)
            response.raise_for_status()
            report[field] = response.json()
    except Exception as exc:
        report["preflight_api_error"] = f"{type(exc).__name__}: {exc}"
        report["stopped_after_api_error"] = "preflight"
        report["unrun_cases"] = case_ids
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
        print("STOP before cases after API error. REPORT " + str(output), flush=True)
        return
    for case_index, case_id in enumerate(case_ids):
        question, expected = CASES[case_id]
        evidence = []
        with get_connection() as conn:
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                for brand, model, year in expected:
                    evidence.extend(get_bike_details(conn, model, brand, year))
        print("START " + case_id, flush=True)
        start = time.monotonic()
        client, job, cancellation, close_error = None, None, None, None
        result, answer, error = None, None, None
        try:
            client = Client(args.demo_url, verbose=False, analytics_enabled=False,
                            httpx_kwargs={"timeout": 30.0})
            job = client.submit(question, [], "", api_name="/chat")
            result = job.result(timeout=args.gradio_timeout_seconds)
            answer, error = text_answer(result), None
        except Exception as exc:
            result, answer, error = None, None, f"{type(exc).__name__}: {exc}"
            if job is not None:
                cancellation = {"attempted": True, "accepted": None, "server_stop_verified": False}
                try:
                    cancellation["accepted"] = job.cancel()
                except Exception as cancel_exc:
                    cancellation["error"] = f"{type(cancel_exc).__name__}: {cancel_exc}"
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception as exc:
                    close_error = f"{type(exc).__name__}: {exc}"
                    error = error or f"Client close failed: {close_error}"
        case = {"id": case_id, "question": question, "elapsed_seconds": round(time.monotonic() - start, 3),
                "answer": answer, "result": result, "expected_evidence": evidence, "api_error": error,
                "cancellation": cancellation, "client_close_error": close_error}
        report["cases"].append(case)
        if error:
            report["stopped_after_api_error"] = case_id
            report["unrun_cases"] = case_ids[case_index + 1:]
        save()
        print(json.dumps({key: case[key] for key in ("id", "elapsed_seconds", "answer", "api_error")}, ensure_ascii=False), flush=True)
        if error:
            print("STOP after API error; a server-side job may still be running.", flush=True)
            break
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    try:
        response = requests.get(args.ollama_url + "/api/ps", timeout=5)
        response.raise_for_status()
        report["model_runtime_after"] = response.json()
    except Exception as exc:
        report["model_runtime_after_api_error"] = f"{type(exc).__name__}: {exc}"
    save()
    print("REPORT " + str(output), flush=True)


if __name__ == "__main__":
    main()

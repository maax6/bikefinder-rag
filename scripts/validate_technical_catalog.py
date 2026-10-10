"""Read-only acceptance checks for the audited full local technical catalog.

Requires the October 2026 full corpus, including the two 2000 example sheets.
Does not call Ollama, embeddings, a cloud service or a judge.
Run from the repository root with PYTHONPATH=src.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import argparse
import subprocess
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from bikefinder_rag.db.client import get_connection
from bikefinder_rag.agent.tools import execute_tool

parser = argparse.ArgumentParser(description="Validate the first technical slice on the audited full local catalog, using read-only SQL and no LLM.")
parser.add_argument("--output", type=Path, help="JSON report path (default: a new dated report).")
args = parser.parse_args()

cases = []
checks = [
    ("sheet_exact_variant", "get_bike_details", {"brand": "Suzuki", "model": "GSF 1200 N Bandit", "year": 2000}),
    ("comparison_second_sheet", "get_bike_details", {"brand": "Kawasaki", "model": "ER-5 Twister", "year": 2000}),
    ("different_variant", "get_bike_details", {"brand": "Suzuki", "model": "GSF 1200 S Bandit", "year": 2000}),
    ("absent_sheet", "get_bike_details", {"brand": "FixtureUnlisted", "model": "FixtureUnlisted", "year": 2000}),
    ("year_listing", "filter_specs", {"min_year": 2000, "max_year": 2000, "limit": 20}),
    ("year_count", "filter_specs", {"min_year": 2000, "max_year": 2000, "count_only": True}),
    ("torque_filter", "filter_specs", {"min_year": 2000, "max_year": 2000, "min_torque_nm": 50, "max_torque_nm": 70, "limit": 5}),
    ("equipment_unsupported", "filter_specs", {"min_year": 2000, "max_year": 2000, "abs": True}),
    ("missing_model_year", "get_bike_details", {"model": "GSF 1200 N Bandit"}),
    ("reviews_disabled", "search_reviews", {"query": "technical specifications"}),
]
with get_connection() as conn:
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), min(year), max(year) FROM motorcycles")
            count, min_year, max_year = cur.fetchone()
        for name, tool, arguments in checks:
            result = execute_tool(conn, tool, arguments)
            cases.append({"case": name, "tool": tool, "arguments": arguments, "result": result})
            if name in {"sheet_exact_variant", "comparison_second_sheet", "different_variant"}:
                assert len(result) == 1 and result[0]["model"] == arguments["model"]
                assert result[0]["year"] == 2000 and result[0]["url"].startswith("https://bikez.com/")
                assert result[0]["specs"] and "family_id" not in result[0]
            elif name == "absent_sheet":
                assert result == []
            elif name == "year_listing":
                assert len(result) == 20 and all(row["year"] == 2000 for row in result)
            elif name == "year_count":
                assert result[0]["matching_motorcycles"] > 20
            elif name == "torque_filter":
                assert result and all(50 <= row["torque_nm"] <= 70 for row in result)
            else:
                assert len(result) == 1 and "error" in result[0]
            cases[-1]["passed"] = True

paths = ["src/bikefinder_rag/agent/tools.py", "src/bikefinder_rag/agent/loop.py", "src/bikefinder_rag/app.py", "scripts/validate_technical_catalog.py"]
now = datetime.now(timezone.utc)
selected = cases[:3]
report = {
    "generated_at": now.isoformat(), "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "validation": "Real PostgreSQL tool calls in a read-only transaction; no LLM generation, embedding, service restart or benchmark.",
    "limitations": ["Does not validate final model wording or latency.", "Legacy normalization remains; identity/measure migration is the next step.", "Existing Gradio process has not loaded these changes."],
    "catalog_snapshot": {"motorcycles": count, "min_year": min_year, "max_year": max_year},
    "working_tree_sha256": {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths},
    "selected_evidence_sha256": hashlib.sha256(json.dumps(selected, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
    "cases": cases,
}
output = args.output or Path("eval_results/technical") / ("catalog_tools_" + now.strftime("%Y%m%dT%H%M%S.%fZ") + ".json")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"report": str(output), "checks_passed": len(cases), "catalog_snapshot": report["catalog_snapshot"]}, ensure_ascii=False, indent=2))

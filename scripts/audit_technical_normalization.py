#!/usr/bin/env python3
"""Audit bounded migration candidates with read-only SQL; never reimport data."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from bikefinder_rag.catalog import NORMALIZATION_VERSION
    from bikefinder_rag.catalog.normalization import normalize_sheet
    from bikefinder_rag.db.client import get_connection

    # Deliberate strata, not a random sample or a market coverage estimate.
    strata = [
        ("compound_brands", "brand IN ('MV', 'Moto', 'Royal', 'Brough', 'Sucker')"),
        ("dry_weight", "raw_specs ? 'Dry weight'"),
        ("wet_weight", "raw_specs ? 'Weight incl. oil, gas, etc'"),
        ("generic_weight", "raw_specs ? 'Weight'"),
        ("before_1930", "year < 1930"),
        ("after_2020", "year >= 2020"),
    ]
    rows, membership = {}, {}
    with get_connection() as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            counts = conn.execute("SELECT count(*), min(year), max(year) FROM motorcycles").fetchone()
            for name, clause in strata:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT * FROM motorcycles WHERE {clause} ORDER BY year, url LIMIT 4")
                    columns = [column.name for column in cur.description]
                    selected = [dict(zip(columns, values)) for values in cur.fetchall()]
                membership[name] = [row["url"] for row in selected]
                for row in selected:
                    rows[row["url"]] = row
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM motorcycles WHERE year = %s AND brand = %s AND model IN (%s, %s) ORDER BY url",
                            (2000, "Suzuki", "GSF 1200 N Bandit", "GSF 1200 S Bandit"))
                columns = [column.name for column in cur.description]
                for values in cur.fetchall():
                    row = dict(zip(columns, values))
                    rows[row["url"]] = row

    candidates = [normalize_sheet(row) for _, row in sorted(rows.items())]
    identities = Counter(item["identity"]["status"] for item in candidates)
    measurements = {name: dict(Counter(item["measurements"][name]["status"] for item in candidates))
                    for name in candidates[0]["measurements"]} if candidates else {}
    # Every candidate keeps every raw field, including misleading legacy ones.
    raw_preserved = all(json.loads(json.dumps(rows[item["raw_record"]["url"]], default=lambda value: value.isoformat()))
                        == item["raw_record"] for item in candidates)
    raw_specs_preserved = all(item["raw_record"]["raw_specs"] == rows[item["raw_record"]["url"]]["raw_specs"]
                              for item in candidates)
    deterministic = all(normalize_sheet(rows[item["raw_record"]["url"]]) == item for item in candidates)
    assert raw_preserved and raw_specs_preserved and deterministic
    files = ["src/bikefinder_rag/catalog/identity.py", "src/bikefinder_rag/catalog/measurements.py",
             "src/bikefinder_rag/catalog/normalization.py", "src/bikefinder_rag/catalog/brands.json",
             "src/bikefinder_rag/catalog/__init__.py", "scripts/audit_technical_normalization.py"]
    now = datetime.now(timezone.utc)
    report = {
        "created_at": now.isoformat(), "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip(),
        "normalization_version": NORMALIZATION_VERSION,
        "scope": "Bounded, deliberately stratified migration-candidate audit; no DB mutation or corpus reimport.",
        "limitations": ["Not a coverage estimate or validation of every catalog record.",
                         "Provisional unknown identities require review.",
                         "Not integrated into runtime filters or comparisons yet."],
        "catalog_snapshot": dict(zip(("motorcycles", "min_year", "max_year"), counts)),
        "strata": membership, "sample_size": len(candidates),
        "checks": {"raw_records_preserved": raw_preserved, "raw_specs_preserved": raw_specs_preserved,
                   "deterministic": deterministic},
        "identity_statuses": dict(identities), "measurement_statuses": measurements,
        "source_files_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in files},
        "candidates": candidates,
    }
    output = args.output or ROOT / "eval_results/technical" / f"normalization_pilot_{now.strftime('%Y%m%dT%H%M%S.%fZ')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"report": str(output), "sample_size": len(candidates), "identity_statuses": dict(identities),
                      "measurement_statuses": measurements}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

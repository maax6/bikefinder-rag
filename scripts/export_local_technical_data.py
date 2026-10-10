#!/usr/bin/env python3
"""Export versioned technical candidates from retained local Bikez sheets.

Only data/*/motorcycles.jsonl is read. Forum comments and owner reviews are
excluded. The source fiche's technical ``raw_specs['Comments']`` wording is
preserved with the complete raw record; it is not a forum-comment object.
The complete export is regenerated offline and atomically replaces its target.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bikefinder_rag.catalog import NORMALIZATION_VERSION
from bikefinder_rag.catalog.normalization import normalize_sheet

EXPORT_VERSION = "bikez-local-technical-export-v1"
EQUIPMENT_EXTRACTION_VERSION = "bikez-equipment-evidence-v1"
_EXCLUDED_LABELS = re.compile(
    r"^\s*(?:model(?: name| year)?|motorcycle name|name|year(?: model| of manufacture)?|category|type|"
    r"ask questions|related bikes|update specs|insurance costs|maintenance|rating|further information)\s*:?\s*$",
    re.IGNORECASE,
)
_EQUIPMENT_LABELS = {
    "front brakes", "rear brakes", "clutch", "instruments", "light", "electrical", "seat",
    "starter", "wheels", "front suspension", "rear suspension", "exhaust system", "color options",
    "equipment", "accessories",
}
_EQUIPMENT_TERMS = (
    ("ABS", r"\bABS\b"), ("CBS", r"\bCBS\b"), ("TCS", r"\bTCS\b"),
    ("traction control", r"\b(?:traction control|contr[oô]le (?:de|de la) traction)\b"),
    ("cruise control", r"\b(?:cruise control|r[eé]gulateur (?:de )?vitesse)\b"),
    ("shifter", r"\b(?:quick\s*shifter|shifter)\b"), ("TFT", r"\bTFT\b"),
    ("Bluetooth", r"\bBluetooth\b"), ("airbag", r"\bairbag\b"),
    ("heated grips", r"\b(?:heated grips|poign[eé]es chauffantes)\b"),
    ("reverse gear", r"\b(?:reverse gear|marche arri[eè]re)\b"),
    ("TPMS", r"\b(?:TPMS|surveillance (?:de la )?pression des pneus)\b"),
    ("IMU", r"\b(?:IMU|centrale inertielle)\b"),
    ("riding modes", r"\b(?:riding modes?|modes? de conduite)\b"),
    ("ride by wire", r"\b(?:ride[- ]by[- ]wire|acc[eé]l[eé]rateur [eé]lectronique)\b"),
    ("slipper clutch", r"\b(?:slipper clutch|anti[- ]dribble)\b"),
)
_REVIEW_KEYS = {"author", "comment_id", "comment_text", "comments", "reviews", "reviewer_model_year"}


def _canonical(row):
    return json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def equipment_evidence(row):
    """Locate source wording without assigning fitment, absence or a market."""
    specs = row.get("raw_specs")
    if not isinstance(specs, dict):
        return []
    evidence = []
    for label, text in specs.items():
        if not isinstance(label, str) or _EXCLUDED_LABELS.search(label) or not isinstance(text, str):
            continue
        normalized_label = " ".join(label.casefold().strip().rstrip(":").split())
        if not text.strip() or text.strip().casefold() in {"loading...", "loading…"}:
            continue
        terms = [term for term, pattern in _EQUIPMENT_TERMS if re.search(pattern, text, re.IGNORECASE)]
        if not terms and normalized_label not in _EQUIPMENT_LABELS:
            continue
        evidence.append({"label": label, "text": text, "terms": terms, "status": "unclassified",
                         "source_url": row.get("url"), "collected_at": None,
                         "extraction_version": EQUIPMENT_EXTRACTION_VERSION})
    return evidence


def _source_records(data_dir):
    """Keep the first full record per URL and explicitly journal conflicts."""
    selected, files, duplicates = {}, {}, {}
    input_rows = 0
    for path in sorted(data_dir.glob("*/motorcycles.jsonl")):
        relative = str(path.relative_to(data_dir))
        digest, row_count, byte_count = hashlib.sha256(), 0, 0
        with path.open("rb") as stream:
            for number, line in enumerate(stream, 1):
                digest.update(line)
                byte_count += len(line)
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict) or not isinstance(row.get("url"), str) or not row["url"].strip():
                        raise ValueError("expected a technical record with a nonempty URL")
                    if _REVIEW_KEYS & row.keys():
                        raise ValueError("review/author fields are outside the technical-export scope")
                    canonical = _canonical(row)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ValueError(f"Invalid technical input at {relative}:{number}: {exc}") from exc
                row_count += 1
                input_rows += 1
                origin = {"file": relative, "line": number,
                          "line_sha256": hashlib.sha256(line).hexdigest()}
                if row["url"] in selected:
                    first = selected[row["url"]]["record"]
                    different_fields = sorted(key for key in first.keys() | row.keys() if first.get(key) != row.get(key))
                    duplicates.setdefault(row["url"], []).append({**origin, "different_fields": different_fields,
                                                                 "identical_raw_record": not different_fields})
                else:
                    selected[row["url"]] = {"record": row, "origin": origin,
                                             "source_record_sha256": hashlib.sha256(canonical.encode()).hexdigest()}
        files[relative] = {"sha256": digest.hexdigest(), "bytes": byte_count, "rows": row_count}
    if not files:
        raise ValueError(f"No */motorcycles.jsonl files found under {data_dir}")
    return selected, files, duplicates, input_rows


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=f".{path.name}.",
                                         suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_local_data(data_dir, output, *, imported_at=None):
    """Regenerate all candidates, replacing the destination only after success.

    ``imported_at`` describes this offline export. Unknown original collection
    dates stay null; no file mtime or export time is substituted for them.
    """
    data_dir, output = Path(data_dir), Path(output)
    imported_at = imported_at or datetime.now(timezone.utc).isoformat()
    parsed_time = datetime.fromisoformat(imported_at)
    if parsed_time.tzinfo is None:
        raise ValueError("imported_at must include a timezone")
    selected, files, duplicates, input_rows = _source_records(data_dir)
    if output.resolve() in {(data_dir / path).resolve() for path in files}:
        raise ValueError("The export destination must not overwrite a source input")
    output.parent.mkdir(parents=True, exist_ok=True)
    identity_statuses, equipment_terms = Counter(), Counter()
    measurement_statuses = {}
    loading_rows, equipment_rows, evidence_count = 0, 0, 0
    output_digest, output_bytes = hashlib.sha256(), 0
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{output.name}.", suffix=".tmp",
                                         dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            for url, retained in selected.items():
                row = retained["record"]
                candidate = normalize_sheet(row)
                # Neither the input shape nor the legacy typed values become
                # an alternate normalization source in this export.
                assert candidate["raw_record"] == row
                assert candidate["source_record_sha256"] == retained["source_record_sha256"]
                origin = retained["origin"]
                candidate.update({
                    "export_version": EXPORT_VERSION,
                    "source": "bikez",
                    "url": url,
                    "provenance": {**origin, "file_sha256": files[origin["file"]]["sha256"],
                                   "input_root": str(data_dir.resolve()),
                                   "imported_at": imported_at, "collected_at": None,
                                   "collection_date_status": "unknown_original_collection_date",
                                   "input_duplicate_occurrences": duplicates.get(url, []),
                                   "selection_rule": "First full source row in sorted input-file/line order."},
                    "equipment_evidence": equipment_evidence(row),
                })
                specs = row.get("raw_specs")
                specs = specs if isinstance(specs, dict) else {}
                placeholders = [label for label, text in specs.items()
                                if isinstance(text, str) and text.strip().casefold() in {"loading...", "loading…"}]
                candidate["quality_flags"] = ([{"flag": "unresolved_loading_placeholders", "labels": placeholders}]
                                               if placeholders else [])
                loading_rows += bool(placeholders)
                evidence = candidate["equipment_evidence"]
                equipment_rows += bool(evidence)
                evidence_count += len(evidence)
                equipment_terms.update(term for item in evidence for term in item["terms"])
                identity_statuses[candidate["identity"]["status"]] += 1
                for field, measurement in candidate["measurements"].items():
                    measurement_statuses.setdefault(field, Counter())[measurement["status"]] += 1
                serialized = (_canonical(candidate) + "\n").encode("utf-8")
                stream.write(serialized)
                output_digest.update(serialized)
                output_bytes += len(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    conflicts = [{"url": url, "selected_origin": selected[url]["origin"], "additional_occurrences": origins}
                 for url, origins in sorted(duplicates.items())
                 if any(not origin["identical_raw_record"] for origin in origins)]
    dependencies = ["src/bikefinder_rag/catalog/__init__.py", "src/bikefinder_rag/catalog/identity.py",
                    "src/bikefinder_rag/catalog/measurements.py", "src/bikefinder_rag/catalog/normalization.py",
                    "src/bikefinder_rag/catalog/brands.json", "scripts/export_local_technical_data.py"]
    return {
        "export_version": EXPORT_VERSION, "normalization_version": NORMALIZATION_VERSION,
        "equipment_extraction_version": EQUIPMENT_EXTRACTION_VERSION, "imported_at": imported_at,
        "scope": "Offline Bikez technical-sheet export only; no network, database import or owner-review/forum file reads.",
        "input_root": str(data_dir.resolve()),
        "input_files": files, "input_rows": input_rows, "exported_records": len(selected),
        "output": {"path": str(output), "sha256": output_digest.hexdigest(), "bytes": output_bytes},
        "deduplication": {"duplicate_rows": sum(len(origins) for origins in duplicates.values()),
                          "duplicated_urls": len(duplicates), "conflicting_urls": len(conflicts),
                          "conflict_examples": conflicts[:20],
                          "selection_rule": "First full source row in sorted input-file/line order; no field merging or cross-year/variant transfer."},
        "identity_statuses": dict(identity_statuses),
        "measurement_statuses": {field: dict(counts) for field, counts in measurement_statuses.items()},
        "equipment": {"rows_with_supporting_text": equipment_rows, "supporting_passages": evidence_count,
                      "term_passage_counts": dict(equipment_terms), "status": "unclassified"},
        "quality": {"rows_with_loading_placeholders": loading_rows,
                    "complete_raw_record_preserved": True, "source_collection_dates_not_invented": True},
        "code_files_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in dependencies},
        "limitations": [
            "Migration candidates are not imported into the running catalog or its filters.",
            "Unknown original scrape dates remain null; imported_at is the export date only.",
            "Equipment passages retain wording and can describe several variants, options, absence or markets.",
            "Literal model/year identities stay separate; normalization does not establish worldwide completeness or French availability.",
            "Raw technical source descriptions, including the Comments label, are retained; no owner-review or forum-comment object is exported.",
            "Historical Loading placeholders require recollection; retaining them is not recovering their missing values.",
            "Current source licences, access rules and live page availability are not verified by this offline export.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / "data/technical/bikez-local/records.jsonl")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = export_local_data(args.data, args.output)
    try:
        report["base_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        report["base_commit"] = None
    report_path = args.report or ROOT / "eval_results/technical" / f"local_technical_export_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}.json"
    _atomic_json(report_path, report)
    print(json.dumps({"records": report["exported_records"], "output": str(args.output),
                      "bytes": report["output"]["bytes"], "report": str(report_path),
                      "identity_statuses": report["identity_statuses"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

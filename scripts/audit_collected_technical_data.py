#!/usr/bin/env python3
"""Audit one consistent, read-only snapshot of the Motoplanete crawl store.

This measures retained technical source text, not worldwide motorcycle or
equipment coverage. Success and needs_review records remain separate cohorts.
"""

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[1]
AUDIT_VERSION = "collected-technical-data-audit-v1"
_UNKNOWN_TEXT = {
    "unknown", "n/a", "nc", "n.c.", "not available", "not specified", "not documented",
    "non communiqué", "non communiquée", "non renseigné", "non renseignée", "non documenté",
    "non documentée", "inconnu", "inconnue", "-", "--", "?",
}


@contextmanager
def read_only_snapshot(database):
    """Allow SELECTs from a fixed SQLite snapshot; never initialize the store."""
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        yield connection
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _year(value):
    return str(value) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else "unknown"


def _value_status(value):
    if not _text(value):
        return "missing_or_nontext"
    normalized = " ".join(value.casefold().split())
    if normalized in {"loading...", "loading…"}:
        return "loading_placeholder"
    if normalized in _UNKNOWN_TEXT:
        return "unknown_placeholder"
    return "source_text"


def _partial_unknown_marker(value):
    """Flag source text such as 'Fourche Ø nc', without discarding known parts."""
    if _value_status(value) != "source_text":
        return False
    return bool(re.search(
        r"(?<!\w)(?:n\.?c\.?|n/a)(?![a-z0-9_]|\s*\d)|\b(?:unknown|inconnue?|indisponible|not available|non communiqu[eé]e?)\b",
        value, re.IGNORECASE,
    ))


def _group():
    return {"row_count": 0, "value_statuses": Counter(), "fiches": set(), "text_fiches": set(),
            "partial_unknown_rows": 0, "partial_unknown_fiches": set()}


def _add(group, url, status, *, partial_unknown=False):
    group["row_count"] += 1
    group["value_statuses"][status] += 1
    group["fiches"].add(url)
    if status == "source_text":
        group["text_fiches"].add(url)
    if partial_unknown:
        group["partial_unknown_rows"] += 1
        group["partial_unknown_fiches"].add(url)


def _summarize_group(group):
    return {"row_count": group["row_count"], "fiche_count": len(group["fiches"]),
            "fiches_with_nonempty_source_text": len(group["text_fiches"]),
            "rows_with_partial_unknown_markers": group["partial_unknown_rows"],
            "fiches_with_partial_unknown_markers": len(group["partial_unknown_fiches"]),
            "value_statuses": dict(sorted(group["value_statuses"].items()))}


def _cohort(pages, *, max_fiche_examples):
    sections, labels, section_labels, years, terms = {}, {}, {}, {}, {}
    missing_identity, identity_warnings, versions = Counter(), Counter(), Counter()
    value_statuses, equipment_statuses = Counter(), Counter()
    parse_errors, fiche_examples = [], []
    counts = Counter()
    for page in pages:
        counts["state_rows"] += 1
        url = page["url"]
        try:
            record = json.loads(page["result"])
            if not isinstance(record, dict):
                raise ValueError("result is not an object")
        except (TypeError, ValueError):
            counts["missing_or_invalid_result"] += 1
            if len(parse_errors) < 10:
                parse_errors.append({"url": url, "issue": "missing_or_invalid_result"})
            continue
        counts["parsed_fiches"] += 1
        identity = record.get("identity")
        identity = identity if isinstance(identity, dict) else {}
        documented_year = _year(identity.get("year"))
        year_counts = years.setdefault(documented_year, Counter())
        year_counts["fiche_count"] += 1
        missing_fields = [field for field in ("brand", "model") if not _text(identity.get(field))]
        if documented_year == "unknown":
            missing_fields.append("year")
        missing_identity.update(missing_fields)
        counts["fiches_with_missing_identity"] += bool(missing_fields)
        counts["fiches_without_raw_name"] += not _text(identity.get("raw_name"))
        counts["fiches_without_explicit_spec_market"] += not _text(identity.get("market"))
        counts["fiches_with_explicit_spec_market"] += _text(identity.get("market"))
        warnings = identity.get("warnings")
        if isinstance(warnings, list):
            identity_warnings.update({warning for warning in warnings if isinstance(warning, str)})
        if _text(record.get("parser_version")):
            versions[record["parser_version"]] += 1
        collection = record.get("collection")
        collection = collection if isinstance(collection, dict) else {}
        counts["fiches_without_collection_date"] += not _text(collection.get("collected_at"))
        price_markets = record.get("price_markets")
        counts["fiches_with_price_market_text"] += isinstance(price_markets, list) and any(_text(value) for value in price_markets)
        rows = record.get("spec_rows")
        if not isinstance(rows, list):
            counts["fiches_with_invalid_spec_rows"] += 1
            rows = []
        if not rows:
            counts["fiches_without_spec_rows"] += 1
        seen_rows, seen_fields = set(), set()
        fiche_statuses = Counter()
        valid_rows = partial_unknown_rows = 0
        for row in rows:
            if not isinstance(row, dict):
                counts["invalid_spec_row_entries"] += 1
                continue
            valid_rows += 1
            counts["spec_row_count"] += 1
            year_counts["spec_row_count"] += 1
            section = row.get("section") if _text(row.get("section")) else "[unlabelled section]"
            label = row.get("label") if _text(row.get("label")) else "[unlabelled row]"
            counts["unlabelled_source_rows"] += label == "[unlabelled row]"
            status = _value_status(row.get("value"))
            partial_unknown = _partial_unknown_marker(row.get("value"))
            partial_unknown_rows += partial_unknown
            counts["rows_with_partial_unknown_markers"] += partial_unknown
            value_statuses[status] += 1
            fiche_statuses[status] += 1
            year_counts[status + "_rows"] += 1
            year_counts["partial_unknown_marker_rows"] += partial_unknown
            _add(sections.setdefault(section, _group()), url, status, partial_unknown=partial_unknown)
            _add(labels.setdefault(label, _group()), url, status, partial_unknown=partial_unknown)
            _add(section_labels.setdefault(section, {}).setdefault(label, _group()), url, status, partial_unknown=partial_unknown)
            signature = json.dumps([section, label, row.get("value")], ensure_ascii=False, sort_keys=True)
            counts["exact_duplicate_spec_rows"] += signature in seen_rows
            counts["repeated_section_label_rows"] += (section, label) in seen_fields
            seen_rows.add(signature)
            seen_fields.add((section, label))
        unknown_rows = sum(count for status, count in fiche_statuses.items() if status != "source_text")
        counts["fiches_with_unknown_or_missing_values"] += unknown_rows > 0 or partial_unknown_rows > 0
        counts["fiches_with_loading_placeholders"] += fiche_statuses["loading_placeholder"] > 0
        equipment = record.get("equipment_evidence")
        equipment = equipment if isinstance(equipment, list) else []
        valid_equipment = 0
        for evidence in equipment:
            if not isinstance(evidence, dict):
                counts["invalid_equipment_entries"] += 1
                continue
            valid_equipment += 1
            counts["equipment_candidate_count"] += 1
            status = evidence.get("status") if _text(evidence.get("status")) else "[missing status]"
            equipment_statuses[status] += 1
            term = evidence.get("term") if _text(evidence.get("term")) else "[unlabelled candidate]"
            _add(terms.setdefault(term, _group()), url, _value_status(evidence.get("text")))
        counts["fiches_without_equipment_candidates"] += valid_equipment == 0
        counts["fiches_with_equipment_candidates"] += valid_equipment > 0
        year_counts["equipment_candidate_count"] += valid_equipment
        if len(fiche_examples) < max_fiche_examples:
            fiche_examples.append({"requested_url": url, "documented_year": identity.get("year"),
                                   "spec_row_count": valid_rows, "value_statuses": dict(fiche_statuses),
                                   "rows_with_partial_unknown_markers": partial_unknown_rows,
                                   "missing_identity_fields": missing_fields,
                                   "explicit_spec_market": identity.get("market"),
                                   "equipment_candidate_count": valid_equipment})
    # Stable zero counts make an empty needs_review cohort explicit.
    for key in ("state_rows", "parsed_fiches", "missing_or_invalid_result", "spec_row_count",
                "fiches_without_spec_rows", "fiches_with_missing_identity", "fiches_without_explicit_spec_market",
                "fiches_with_explicit_spec_market", "fiches_with_unknown_or_missing_values", "fiches_with_loading_placeholders",
                "rows_with_partial_unknown_markers",
                "equipment_candidate_count", "fiches_with_equipment_candidates", "fiches_without_equipment_candidates",
                "exact_duplicate_spec_rows", "repeated_section_label_rows"):
        counts.setdefault(key, 0)
    return {
        "counts": dict(counts), "by_documented_year": {year: dict(values) for year, values in sorted(years.items())},
        "value_statuses": dict(value_statuses), "missing_identity_fields": dict(missing_identity),
        "identity_warning_fiche_counts": dict(identity_warnings), "parser_version_fiche_counts": dict(versions),
        "by_section": {key: _summarize_group(group) for key, group in sorted(sections.items())},
        "by_label": {key: _summarize_group(group) for key, group in sorted(labels.items())},
        "by_section_and_label": {section: {label: _summarize_group(group) for label, group in sorted(groups.items())}
                                 for section, groups in sorted(section_labels.items())},
        "equipment_candidates": {"provided_statuses": dict(equipment_statuses),
                                 "by_term": {term: _summarize_group(group) for term, group in sorted(terms.items())},
                                 "semantics": "Extracted supporting text only; no equipment presence, absence or fitment conclusion."},
        "fiche_summary_examples": fiche_examples,
        "fiche_examples_truncated": counts["parsed_fiches"] > len(fiche_examples), "result_issue_examples": parse_errors,
    }


def audit_database(database, *, max_fiche_examples=20):
    if max_fiche_examples < 0:
        raise ValueError("max_fiche_examples must be non-negative")
    started_at = datetime.now(timezone.utc).isoformat()
    with read_only_snapshot(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(pages)")}
        if not {"url", "year", "state", "result"} <= columns:
            raise ValueError("Expected a technical crawl pages table with url/year/state/result")
        pages = [dict(row) for row in connection.execute("SELECT * FROM pages ORDER BY url")]
        source_state = []
        if connection.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='source_state'").fetchone():
            source_state = [dict(row) for row in connection.execute("SELECT * FROM source_state ORDER BY key")]
    snapshot_hash = hashlib.sha256()
    for row in pages:
        snapshot_hash.update((json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    snapshot_hash.update(json.dumps(source_state, sort_keys=True, separators=(",", ":")).encode())
    states = Counter(page["state"] for page in pages)
    queue_years = {}
    for page in pages:
        queue_years.setdefault(_year(page["year"]), Counter())[page["state"]] += 1
    return {
        "audit_version": AUDIT_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
        "database": str(Path(database).resolve()), "snapshot_started_at": started_at,
        "snapshot_method": "SQLite URI mode=ro, query_only connection and one explicit read transaction; no queue writes.",
        "logical_snapshot_sha256": snapshot_hash.hexdigest(),
        "scope": "Retained technical records from this Motoplanete crawl store only; no legacy corpus, network or PostgreSQL access.",
        "queue": {"discovered_urls": len(pages), "states": dict(states),
                  "by_url_year_and_state": {year: dict(values) for year, values in sorted(queue_years.items())},
                  "nonaccepted_states_excluded_from_technical_aggregates": sorted(state for state in states if state not in {"success", "needs_review"})},
        "success": _cohort([page for page in pages if page["state"] == "success"], max_fiche_examples=max_fiche_examples),
        "needs_review": _cohort([page for page in pages if page["state"] == "needs_review"], max_fiche_examples=max_fiche_examples),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": [
            "Success measures stored extraction, not manual validation of every source statement.",
            "Needs-review records are reported separately and never enlarge accepted success coverage.",
            "Retryable/pending/blocked/terminal/quarantined records do not contribute technical rows, even if stale result text exists.",
            "Row count includes retained repeats; fiche_count counts a field once per source fiche URL.",
            "Nonempty source text is not a normalized measurement or verified equipment state.",
            "Unknown/missing values or zero equipment candidates are data gaps, not equipment absence.",
            "Partial unknown markers such as 'Ø nc' retain the known source text and flag its unspecified part; they are lexical diagnostics.",
            "Year summaries reflect explicit record identity; missing identity years are not filled from queue URLs.",
            "Price-market text applies to tariffs and does not establish the market of all technical specifications.",
            "The discovery manifest and partial collected records do not establish worldwide completeness, continuity or current licences.",
            "The logical hash fingerprints the exact read snapshot; a live SQLite-file hash would also depend on concurrent WAL changes.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/technical/motoplanete/crawl.sqlite3")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-fiche-examples", type=int, default=20)
    args = parser.parse_args()
    if args.max_fiche_examples < 0:
        parser.error("--max-fiche-examples must be non-negative")
    report = audit_database(args.database, max_fiche_examples=args.max_fiche_examples)
    output = args.output or ROOT / "eval_results/technical" / f"motoplanete_coverage_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}.json"
    if output.resolve() == args.database.resolve():
        parser.error("--output must not overwrite the crawl database")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=f".{output.name}.", suffix=".tmp",
                                         dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(json.dumps({"report": str(output), "queue_states": report["queue"]["states"],
                      "success_counts": report["success"]["counts"],
                      "needs_review_counts": report["needs_review"]["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

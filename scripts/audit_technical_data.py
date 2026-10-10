#!/usr/bin/env python3
"""Inventory local technical sources without fetching pages or changing the DB.

Counts refer to retained source sheets, not worldwide motorcycle coverage.
ABS detection only locates text to review: it never assigns equipment states.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
AUDIT_VERSION = "technical-data-inventory-v1"
_ABS = re.compile(r"\bABS\b", re.IGNORECASE)
_IDENTITY = re.compile(
    r"^\s*(?:model(?: name| year)?|motorcycle name|name|year(?: model| of manufacture)?|category|type)\s*:?\s*$",
    re.IGNORECASE,
)
_NAVIGATION = re.compile(
    r"ask questions|related bikes|update specs|insurance costs|maintenance|rating|further information",
    re.IGNORECASE,
)


def _has_text(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().casefold() != "loading..."


def _year(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 9999 else None


def _signature(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _year_summary(rows):
    counts = Counter(_year(row.get("year")) for row in rows)
    invalid = counts.pop(None, 0)
    return {
        "counts": {str(year): count for year, count in sorted(counts.items())},
        "minimum": min(counts) if counts else None,
        "maximum": max(counts) if counts else None,
        "distinct_years": len(counts),
        "invalid_or_missing_year_rows": invalid,
    }


def _read_jsonl(path, data_dir, inputs):
    digest = hashlib.sha256()
    rows, invalid_lines = [], []
    with path.open("rb") as stream:
        for number, line in enumerate(stream, 1):
            digest.update(line)
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("row is not an object")
            except (ValueError, UnicodeDecodeError):
                invalid_lines.append(number)
                continue
            rows.append(row)
    relative = str(path.relative_to(data_dir))
    inputs[relative] = {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}
    return rows, {"path": relative, "rows": len(rows), "invalid_json_lines": len(invalid_lines),
                  "invalid_line_examples": invalid_lines[:10]}


def _read_journal(path, data_dir, inputs):
    if not path.exists():
        return set(), {"present": False, "lines": 0, "distinct_urls": 0, "duplicate_lines": 0}
    content = path.read_bytes()
    inputs[str(path.relative_to(data_dir))] = {"sha256": hashlib.sha256(content).hexdigest(),
                                             "bytes": len(content)}
    lines = [line.strip() for line in content.decode("utf-8").splitlines() if line.strip()]
    urls = set(lines)
    return urls, {"present": True, "lines": len(lines), "distinct_urls": len(urls),
                  "duplicate_lines": len(lines) - len(urls)}


def _deduplicate(rows):
    selected, signatures, spec_signatures, occurrences = {}, {}, {}, Counter()
    conflicting_fields = {}
    missing_url = 0
    for row in rows:
        url = row.get("url")
        if not isinstance(url, str) or not url.strip():
            missing_url += 1
            continue
        occurrences[url] += 1
        selected.setdefault(url, row)
        signatures.setdefault(url, set()).add(_signature(row))
        spec_signatures.setdefault(url, set()).add(_signature(row.get("raw_specs")))
        first = selected[url]
        differences = {key for key in first.keys() | row.keys() if first.get(key) != row.get(key)}
        if differences:
            conflicting_fields.setdefault(url, set()).update(differences)
    return selected, {
        "rows_without_url": missing_url,
        "distinct_urls": len(selected),
        "duplicate_rows": sum(count - 1 for count in occurrences.values()),
        "duplicated_urls": sum(count > 1 for count in occurrences.values()),
        "conflicting_duplicate_urls": sum(len(values) > 1 for values in signatures.values()),
        "conflicting_raw_specs_urls": sum(len(values) > 1 for values in spec_signatures.values()),
        "conflict_examples": [{"url": url, "different_fields": sorted(keys)}
                              for url, keys in sorted(conflicting_fields.items())[:10]],
        "selection_rule": "First retained row in sorted input-file order; conflicts are counted, not reconciled.",
    }


def _raw_fields_and_abs(rows):
    fields = {}
    abs_rows = Counter()
    abs_years = Counter()
    abs_fields = Counter()
    loading_years = Counter()
    examples, examples_2000 = [], []
    missing_raw_specs = 0
    for row in rows:
        specs = row.get("raw_specs")
        if not isinstance(specs, dict):
            missing_raw_specs += 1
            continue
        roles = set()
        substantive = {}
        has_loading = False
        for label, value in specs.items():
            counts = fields.setdefault(label, {"present": 0, "nonempty_nonloading_text": 0,
                                                "loading_placeholder": 0, "empty_or_nontext": 0})
            counts["present"] += 1
            if isinstance(value, str) and value.strip().casefold() == "loading...":
                counts["loading_placeholder"] += 1
                has_loading = True
            elif _has_text(value):
                counts["nonempty_nonloading_text"] += 1
            else:
                counts["empty_or_nontext"] += 1
            if not _has_text(value) or not _ABS.search(f"{label} {value}"):
                continue
            if _NAVIGATION.search(label):
                roles.add("navigation")
            elif _IDENTITY.search(label):
                roles.add("identity")
            else:
                roles.add("substantive_source_text")
                substantive[label] = value
                abs_fields[label] += 1
        if has_loading:
            loading_years[str(row.get("year"))] += 1
        if roles:
            abs_rows["any_text"] += 1
            for role in roles:
                abs_rows[role] += 1
        if substantive:
            abs_years[str(row.get("year"))] += 1
            text = " ".join(substantive.values())
            if re.search(r"option|optional|en option", text, re.IGNORECASE):
                abs_rows["substantive_text_also_mentions_option"] += 1
            example = {"url": row["url"], "year": row.get("year"),
                       "excerpts": {label: text[:500] for label, text in substantive.items()}}
            if len(examples) < 5:
                examples.append(example)
            if row.get("year") == 2000 and len(examples_2000) < 5:
                examples_2000.append(example)
    return {
        "fields": dict(sorted(fields.items())),
        "rows_missing_raw_specs": missing_raw_specs,
        "rows_with_loading_placeholder": sum(loading_years.values()),
        "loading_rows_by_year": dict(sorted(loading_years.items())),
        "field_count_semantics": "A nonempty non-Loading string is retained source text, not a normalized or verified fact; literal 'None' is preserved.",
    }, {
        "role": "Lexical discovery only; no standard/option/absent equipment classification.",
        "rows": dict(abs_rows),
        "substantive_rows_by_year": dict(sorted(abs_years.items())),
        "substantive_field_mentions": dict(sorted(abs_fields.items())),
        "examples": examples,
        "examples_year_2000": examples_2000,
        "limits": ["Model names and navigation mentions do not count as substantive equipment evidence.",
                   "A sheet can discuss several variants, optional equipment or other markets.",
                   "No ABS mention is not proof of ABS absence."],
    }


def _year_flags(rows, as_of_year):
    future = Counter()
    quarantine, early = [], []
    for row in rows:
        year = _year(row.get("year"))
        if year is None:
            continue
        if year > as_of_year:
            future[str(year)] += 1
        if year > as_of_year + 5:
            quarantine.append({"url": row.get("url"), "year": year,
                               "flag": "far_future_catalog_year_requires_review",
                               "content_kind": "unknown", "quarantine_candidate": True})
        elif year < 1885:
            early.append({"url": row.get("url"), "year": year,
                          "flag": "early_historical_catalog_year_requires_review",
                          "content_kind": "unknown", "quarantine_candidate": False})
    return {"reference_year": as_of_year, "future_model_year_counts": dict(sorted(future.items())),
            "quarantine_candidates": quarantine[:20], "quarantine_candidate_count": len(quarantine),
            "early_historical_examples": early[:20], "early_historical_count": len(early),
            "semantics": "Future model years are not automatically fictional. Far-future rows require source review; no content kind is asserted from the year alone."}


def audit_data(data_dir, *, as_of_year):
    """Return a JSON-serializable inventory; never modify any input file."""
    data_dir = Path(data_dir)
    inputs, files, bikez_rows = {}, [], []
    for path in sorted(data_dir.glob("*/motorcycles.jsonl")):
        rows, metadata = _read_jsonl(path, data_dir, inputs)
        metadata["years"] = _year_summary(rows)
        metadata["fields_present"] = dict(sorted(Counter(key for row in rows for key in row).items()))
        files.append(metadata)
        bikez_rows.extend(rows)
    retained, duplicates = _deduplicate(bikez_rows)
    sheets = list(retained.values())
    raw_fields, abs_mentions = _raw_fields_and_abs(sheets)
    bikez = {
        "input_files": files, "retained_rows": len(bikez_rows), "deduplication": duplicates,
        "years": _year_summary(sheets),
        "legacy_brand_labels": len({row.get("brand") for row in sheets if row.get("brand")}),
        "categories": dict(sorted(Counter(str(row.get("category", "missing")) for row in sheets).items())),
        "raw_specs": raw_fields, "abs_mentions": abs_mentions, "year_flags": _year_flags(sheets, as_of_year),
        "provenance": {"rows_with_collection_timestamp": sum(bool(row.get("scraped_at")) for row in sheets),
                       "rows_with_raw_name": sum(bool(row.get("raw_name")) for row in sheets),
                       "observed_source_hosts": dict(sorted(Counter(urlparse(row["url"]).netloc for row in sheets).items())),
                       "observed_path_families": dict(sorted(Counter(urlparse(row["url"]).path.lstrip("/").split("/")[0] for row in sheets).items()))},
    }
    motoplanete_dir = data_dir / "motoplanete"
    price_path = motoplanete_dir / "prices.jsonl"
    prices, metadata = _read_jsonl(price_path, data_dir, inputs) if price_path.exists() else ([], {"present": False})
    retained_prices, price_duplicates = _deduplicate(prices)
    cached, cache_info = _read_journal(motoplanete_dir / "fiche_urls.txt", data_dir, inputs)
    done, done_info = _read_journal(motoplanete_dir / "urls_done.txt", data_dir, inputs)
    saved = set(retained_prices)
    motoplanete = {
        "prices_file": metadata, "deduplication": price_duplicates,
        "years": _year_summary(retained_prices.values()),
        "year_flags": _year_flags(retained_prices.values(), as_of_year),
        "legacy_brand_labels": len({row.get("brand") for row in prices if row.get("brand")}),
        "prices_present": sum(row.get("price_eur") is not None for row in retained_prices.values()),
        "categories_present": sum(bool(row.get("category_fr")) for row in retained_prices.values()),
        "cached_discovery": cache_info, "done_journal": done_info,
        "reconciliation": {
            "done_without_saved_row": len(done - saved), "saved_without_done": len(saved - done),
            "cached_not_done": len(cached - done), "done_not_cached": len(done - cached),
            "saved_not_cached": len(saved - cached),
            "cached_not_done_examples": sorted(cached - done)[:10],
            "meaning": "Done is a historical journal entry, not proof of a successful parsed record or currently available page.",
        },
        "retained_fields": sorted({key for row in prices for key in row}),
        "technical_specs_in_retained_prices": sum(isinstance(row.get("raw_specs"), dict) and bool(row["raw_specs"]) for row in prices),
        "rows_with_collection_timestamp": sum(bool(row.get("scraped_at")) for row in prices),
        "limits": ["These price rows and URL journals do not retain complete fiche HTML or equipment tables.",
                   "A French price field does not independently establish every model's French availability."],
    }
    return {
        "audit_version": AUDIT_VERSION, "reference_year": as_of_year,
        "scope": "Offline inventory of data/*/motorcycles.jsonl and Motoplanete prices/discovery/done journals; no network requests or database imports.",
        "input_files": inputs, "bikez": bikez, "motoplanete": motoplanete,
        "limitations": [
            "Distinct source URLs are sheets, not guaranteed unique worldwide model/variant identities.",
            "Year counts describe retained catalog labels, not production dates, continuity or worldwide completeness.",
            "Legacy brand strings have not all been normalized; their count is not a verified manufacturer count.",
            "Market and variant applicability require evidence; no market is inferred from source language.",
            "This inventory does not verify current robots rules, licences, permissions or source availability.",
            "Historical collection excludes ATV and scooters below 500 cc; observed category coverage is therefore filtered.",
            "Owner reviews and safety-recall files are excluded from this technical-sheet inventory.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--as-of-year", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.as_of_year <= 9999:
        parser.error("--as-of-year must be between 1 and 9999")
    report = audit_data(args.data, as_of_year=args.as_of_year)
    now = datetime.now(timezone.utc)
    report["created_at"] = now.isoformat()
    report["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    try:
        report["base_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        report["base_commit"] = None
    output = args.output or ROOT / "eval_results/technical" / f"data_inventory_{now.strftime('%Y%m%dT%H%M%S.%fZ')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), "bikez_sheets": report["bikez"]["deduplication"]["distinct_urls"],
                      "bikez_loading_sheets": report["bikez"]["raw_specs"]["rows_with_loading_placeholder"],
                      "motoplanete_price_sheets": report["motoplanete"]["deduplication"]["distinct_urls"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

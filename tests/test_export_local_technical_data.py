"""Local export preserves source evidence without inventing equipment or dates."""

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/export_local_technical_data.py"
spec = importlib.util.spec_from_file_location("local_technical_export", SCRIPT)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)
IMPORTED_AT = "2026-10-10T13:00:00+00:00"


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def sheet(year=2000, model="GSF 1200 N Bandit", **changes):
    row = {"url": f"https://bikez.com/motorcycles/suzuki_{model.lower().replace(' ', '_')}_{year}.php",
           "brand": "Suzuki", "model": model, "year": year, "category": "Naked bike",
           "typed_fields": {"weight_kg": 999.0, "power_hp": 999.0},
           "raw_specs": {"Dry weight": "214 kg", "Power": "Loading...", "Front brakes": "ABS optional"}}
    row.update(changes)
    return row


def run_export(tmp_path):
    output = tmp_path / "technical/bikez-local/records.jsonl"
    report = exporter.export_local_data(tmp_path, output, imported_at=IMPORTED_AT)
    records = [json.loads(line) for line in output.read_text().splitlines()]
    return report, records


def test_duplicate_equivalent_rows_deduplicate_and_conflicts_keep_the_first_full_record(tmp_path):
    first = sheet()
    write_rows(tmp_path / "a/motorcycles.jsonl", [first])
    write_rows(tmp_path / "b/motorcycles.jsonl", [first, sheet(raw_specs={"Dry weight": "240 kg"})])

    report, records = run_export(tmp_path)

    assert len(records) == report["exported_records"] == 1
    assert report["deduplication"]["duplicate_rows"] == 2
    assert report["deduplication"]["conflicting_urls"] == 1
    assert records[0]["raw_record"] == first
    assert records[0]["measurements"]["weight_dry_kg"]["value"] == 214.0
    assert records[0]["provenance"]["file"] == "a/motorcycles.jsonl"
    occurrences = records[0]["provenance"]["input_duplicate_occurrences"]
    assert [origin["identical_raw_record"] for origin in occurrences] == [True, False]
    assert occurrences[1]["different_fields"] == ["raw_specs"]


def test_identity_year_variant_and_original_collection_dates_are_not_invented(tmp_path):
    write_rows(tmp_path / "a/motorcycles.jsonl", [sheet(), sheet(model="GSF 1200 S Bandit"), sheet(year=2001)])

    report, records = run_export(tmp_path)

    assert len(records) == 3
    assert len({record["identity"]["model_year_id"] for record in records}) == 3
    assert all(record["identity"]["variant"] is None for record in records)
    assert all(record["identity"]["market"] is None for record in records)
    assert all(record["provenance"]["collected_at"] is None for record in records)
    assert all(record["identity"]["source"]["collected_at"] is None for record in records)
    assert all(record["provenance"]["imported_at"] == IMPORTED_AT for record in records)
    assert report["quality"]["source_collection_dates_not_invented"] is True


def test_equipment_stays_unclassified_and_navigation_does_not_supply_abs_evidence(tmp_path):
    row = sheet(raw_specs={"Model name": "Suzuki GSF 1200 N Bandit ABS", "Category": "ABS bike",
                          "Ask questions": "Discuss ABS", "Front brakes": "ABS optional",
                          "Comments": "Also sold without ABS", "Light": "LED headlamp",
                          "Modifications compared to previous model": "New ABS system for this model year"})
    write_rows(tmp_path / "a/motorcycles.jsonl", [row])

    _, records = run_export(tmp_path)

    record = records[0]
    assert record["raw_record"] == row
    evidence = record["equipment_evidence"]
    assert {item["label"] for item in evidence} == {
        "Front brakes", "Comments", "Light", "Modifications compared to previous model",
    }
    assert all(item["status"] == "unclassified" for item in evidence)
    assert all(item["collected_at"] is None for item in evidence)
    assert not any(isinstance(value, bool) for item in evidence for value in item.values())
    assert not any(key in record for key in ("abs", "has_abs", "abs_state", "author", "reviews"))


def test_loading_placeholders_and_legacy_typed_values_do_not_become_valid_measurements(tmp_path):
    row = sheet(raw_specs={"Power": "Loading...", "Dry weight": "Loading...", "Torque": "100 Nm"})
    write_rows(tmp_path / "a/motorcycles.jsonl", [row])

    report, records = run_export(tmp_path)

    record = records[0]
    assert record["raw_record"]["typed_fields"] == {"weight_kg": 999.0, "power_hp": 999.0}
    assert record["measurements"]["power_kw"]["value"] is None
    assert record["measurements"]["power_kw"]["status"] == "unknown"
    assert record["measurements"]["weight_dry_kg"]["value"] is None
    assert record["measurements"]["weight_wet_kg"]["value"] is None
    assert record["measurements"]["torque_nm"]["value"] == 100.0
    assert record["quality_flags"][0]["labels"] == ["Power", "Dry weight"]
    assert report["quality"]["rows_with_loading_placeholders"] == 1


def test_owner_review_files_are_not_read_and_author_objects_are_rejected(tmp_path):
    write_rows(tmp_path / "a/motorcycles.jsonl", [sheet()])
    (tmp_path / "a/comments.jsonl").write_text("not JSON; private author contents\n")
    write_rows(tmp_path / "motoplanete/reviews.jsonl", [{"author": "Private", "text": "Owner opinion"}])

    report, _ = run_export(tmp_path)

    assert set(report["input_files"]) == {"a/motorcycles.jsonl"}
    write_rows(tmp_path / "a/motorcycles.jsonl", [sheet(author="Private")])
    with pytest.raises(ValueError, match="review/author fields"):
        run_export(tmp_path)


def test_failed_regeneration_preserves_the_previous_export_and_removes_temporary_output(tmp_path, monkeypatch):
    write_rows(tmp_path / "a/motorcycles.jsonl", [sheet()])
    output = tmp_path / "technical/bikez-local/records.jsonl"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"previous completed export\n")

    def failed_normalization(row):
        raise RuntimeError("normalization failed")

    monkeypatch.setattr(exporter, "normalize_sheet", failed_normalization)
    with pytest.raises(RuntimeError, match="normalization failed"):
        exporter.export_local_data(tmp_path, output, imported_at=IMPORTED_AT)

    assert output.read_bytes() == b"previous completed export\n"
    assert list(output.parent.glob("*.tmp")) == []


def test_export_destination_cannot_overwrite_an_original_source_file(tmp_path):
    source = tmp_path / "a/motorcycles.jsonl"
    write_rows(source, [sheet()])
    original = source.read_bytes()

    with pytest.raises(ValueError, match="must not overwrite"):
        exporter.export_local_data(tmp_path, source, imported_at=IMPORTED_AT)

    assert source.read_bytes() == original

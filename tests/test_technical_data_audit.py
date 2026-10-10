"""Offline inventory must distinguish retained evidence from crawl progress."""

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit_technical_data.py"
spec = importlib.util.spec_from_file_location("technical_data_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def sheet(url="https://bikez.example/a", year=2000, **changes):
    return {"url": url, "year": year, "brand": "Example", "model": "A", "category": "Sport",
            "raw_specs": {"Front brakes": "Single disc. Optional ABS."}, **changes}


def test_duplicate_urls_and_conflicts_are_visible_without_inventing_extra_sheets(tmp_path):
    row = sheet()
    write_rows(tmp_path / "first/motorcycles.jsonl", [row, row])
    write_rows(tmp_path / "second/motorcycles.jsonl", [sheet(raw_specs={"Front brakes": "Double disc. ABS."})])

    report = audit.audit_data(tmp_path, as_of_year=2026)

    assert report["bikez"]["retained_rows"] == 3
    assert report["bikez"]["deduplication"]["distinct_urls"] == 1
    assert report["bikez"]["deduplication"]["duplicate_rows"] == 2
    assert report["bikez"]["deduplication"]["conflicting_duplicate_urls"] == 1
    assert report["bikez"]["deduplication"]["conflicting_raw_specs_urls"] == 1
    assert report["bikez"]["deduplication"]["conflict_examples"][0]["different_fields"] == ["raw_specs"]
    assert report["bikez"]["years"]["counts"] == {"2000": 1}
    assert report["bikez"]["abs_mentions"]["rows"]["substantive_source_text"] == 1


def test_done_journal_is_not_a_success_count_and_inputs_are_hashed(tmp_path):
    base = tmp_path / "motoplanete"
    write_rows(base / "prices.jsonl", [{"url": "saved", "year": 2026, "price_eur": None}])
    (base / "fiche_urls.txt").write_text("saved\nfailed\nunvisited\n")
    (base / "urls_done.txt").write_text("saved\nfailed\nfailed\n")
    before = {path: path.read_bytes() for path in base.iterdir()}

    report = audit.audit_data(tmp_path, as_of_year=2026)

    reconciliation = report["motoplanete"]["reconciliation"]
    assert reconciliation["done_without_saved_row"] == 1
    assert reconciliation["cached_not_done"] == 1
    assert report["motoplanete"]["done_journal"]["duplicate_lines"] == 1
    assert report["motoplanete"]["deduplication"]["distinct_urls"] == 1
    assert all(len(value["sha256"]) == 64 for value in report["input_files"].values())
    assert all(path.read_bytes() == content for path, content in before.items())


def test_loading_empty_and_nontext_are_missing_but_literal_none_is_retained(tmp_path):
    write_rows(tmp_path / "demo/motorcycles.jsonl", [sheet(year=2024, raw_specs={
        "Power": " Loading... ", "Torque": "", "Seat": None, "Light": "None", "Color options": "Blue",
    })])

    raw = audit.audit_data(tmp_path, as_of_year=2026)["bikez"]["raw_specs"]

    assert raw["rows_with_loading_placeholder"] == 1
    assert raw["loading_rows_by_year"] == {"2024": 1}
    assert raw["fields"]["Power"]["nonempty_nonloading_text"] == 0
    assert raw["fields"]["Power"]["loading_placeholder"] == 1
    assert raw["fields"]["Torque"]["empty_or_nontext"] == 1
    assert raw["fields"]["Seat"]["empty_or_nontext"] == 1
    assert raw["fields"]["Light"]["nonempty_nonloading_text"] == 1


def test_abs_titles_and_navigation_do_not_become_equipment_evidence(tmp_path):
    write_rows(tmp_path / "demo/motorcycles.jsonl", [
        sheet(url="title-only", raw_specs={"Model name": "A ABS", "Ask questions": "Discuss A ABS"}),
        sheet(url="equipment", raw_specs={
            "Front brakes": "ABS optional", "Comments": "Also sold without ABS.",
            "Modifications compared to previous model": "New ABS system for this model year",
        }),
    ])

    mentions = audit.audit_data(tmp_path, as_of_year=2026)["bikez"]["abs_mentions"]

    assert mentions["rows"]["any_text"] == 2
    assert mentions["rows"]["identity"] == 1
    assert mentions["rows"]["navigation"] == 1
    assert mentions["rows"]["substantive_source_text"] == 1
    assert mentions["substantive_rows_by_year"] == {"2000": 1}
    assert mentions["substantive_field_mentions"]["Modifications compared to previous model"] == 1
    assert [example["url"] for example in mentions["examples"]] == ["equipment"]
    assert "classification" in mentions["role"]
    assert not any("abs_state" in example for example in mentions["examples"])


def test_far_future_is_quarantined_for_review_without_calling_all_future_rows_fiction(tmp_path):
    write_rows(tmp_path / "motoplanete/prices.jsonl", [
        {"url": "announced", "year": 2027}, {"url": "unclear", "year": 2078},
        {"url": "historical", "year": 1871},
    ])

    flags = audit.audit_data(tmp_path, as_of_year=2026)["motoplanete"]["year_flags"]

    assert flags["future_model_year_counts"] == {"2027": 1, "2078": 1}
    assert flags["quarantine_candidate_count"] == 1
    assert flags["quarantine_candidates"][0]["url"] == "unclear"
    assert flags["quarantine_candidates"][0]["content_kind"] == "unknown"
    assert flags["early_historical_count"] == 1
    assert flags["early_historical_examples"][0]["quarantine_candidate"] is False


def test_invalid_lines_and_missing_urls_are_reported_separately(tmp_path):
    path = tmp_path / "pilot/motorcycles.jsonl"
    write_rows(path, [{"year": True, "raw_specs": {}}, sheet()])
    with path.open("a") as output:
        output.write("[1, 2]\nnot json\n")

    report = audit.audit_data(tmp_path, as_of_year=2026)

    assert report["bikez"]["input_files"][0]["invalid_json_lines"] == 2
    assert report["bikez"]["deduplication"]["rows_without_url"] == 1
    assert report["bikez"]["deduplication"]["distinct_urls"] == 1
    json.dumps(report, allow_nan=False)

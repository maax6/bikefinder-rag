from copy import deepcopy
from datetime import datetime, timezone
import json

from bikefinder_rag.catalog.normalization import normalize_sheet


def record(**changes):
    row = {
        "brand": "MV", "model": "Agusta Brutale 800", "year": 2024,
        "url": "https://catalog.example/mv-agusta-2024",
        "scraped_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
        "weight_kg": 175.0, "power_hp": 140.0,
        "raw_specs": {"Dry weight": "175 kg", "Wet weight": "194 kg",
                      "Power": "140 HP", "Torque": "Loading..."},
    }
    row.update(changes)
    return row


def test_candidate_corrects_identity_without_losing_source_or_legacy_values():
    row = record()
    original = deepcopy(row)

    candidate = normalize_sheet(row)

    assert row == original
    assert candidate["identity"]["brand"] == "MV Agusta"
    assert candidate["identity"]["model"] == "Brutale 800"
    assert candidate["raw_record"]["brand"] == "MV"
    assert candidate["raw_record"]["raw_specs"] == original["raw_specs"]
    assert candidate["raw_record"]["weight_kg"] == 175.0
    assert candidate["measurements"]["weight_dry_kg"]["value"] == 175.0
    assert candidate["measurements"]["weight_wet_kg"]["value"] == 194.0
    assert candidate["measurements"]["power_kw"]["value"] is None
    assert candidate["measurements"]["torque_nm"]["value"] is None
    json.dumps(candidate, allow_nan=False)


def test_candidates_do_not_inherit_measurements_from_another_model_year():
    older = normalize_sheet(record(year=2023, raw_specs={"Power": "80 kW"}))
    newer = normalize_sheet(record(raw_specs={}))

    assert older["identity"]["model_id"] == newer["identity"]["model_id"]
    assert older["identity"]["model_year_id"] != newer["identity"]["model_year_id"]
    assert older["measurements"]["power_kw"]["value"] == 80.0
    assert newer["measurements"]["power_kw"]["value"] is None
    assert older["source_record_sha256"] != newer["source_record_sha256"]


def test_candidate_is_reproducible_and_keeps_unrecognized_raw_fields():
    row = record(raw_specs={"A historical field": "Original text", "Weight": "180 kg"})

    first, second = normalize_sheet(row), normalize_sheet(deepcopy(row))

    assert first == second
    assert first["raw_record"]["raw_specs"]["A historical field"] == "Original text"
    assert first["measurements"]["weight_unspecified_kg"]["value"] == 180.0
    assert first["measurements"]["weight_dry_kg"]["value"] is None
    assert first["measurements"]["weight_wet_kg"]["value"] is None


def test_candidate_retains_conflicts_instead_of_selecting_a_convenient_value():
    candidate = normalize_sheet(record(raw_specs={"Dry weight": "170 kg", "Poids à sec": "190 kg"}))

    field = candidate["measurements"]["weight_dry_kg"]
    assert field["status"] == "conflict" and field["value"] is None
    assert {proof["raw_value"] for proof in field["evidence"]} == {"170 kg", "190 kg"}

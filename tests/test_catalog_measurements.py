"""Measurement behavior on preserved sheets; no live corpus is modified."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from bikefinder_rag.catalog.measurements import normalize_measurements
from bikefinder_rag.scraper.detail_scraper import parse_spec_page


SOURCE = "https://catalog.example/bike-2000"
COLLECTED = datetime(2026, 10, 10, 12, 30, tzinfo=timezone.utc)


def normalize(specs, **legacy):
    return normalize_measurements({"raw_specs": specs, "url": SOURCE, "scraped_at": COLLECTED, **legacy})


def test_preserved_xadv_sheet_produces_traceable_independent_measures():
    detail = parse_spec_page((Path(__file__).parent / "fixtures/xadv_spec.html").read_bytes())
    row = {"raw_specs": detail.raw_specs, **detail.typed_fields, "url": SOURCE, "scraped_at": COLLECTED}
    before = deepcopy(row)

    measures = normalize_measurements(row)

    assert measures["displacement_ccm"]["value"] == 745.0
    assert measures["weight_wet_kg"]["value"] == 236.0
    assert measures["weight_dry_kg"]["value"] is None
    assert measures["weight_unspecified_kg"]["value"] is None
    assert measures["power_kw"]["value"] == 42.2
    assert measures["seat_height_mm"]["value"] == 820.0
    power = measures["power_kw"]
    assert power["status"] == "documented"
    assert power["nature"] == "undocumented"
    assert any(proof["original_unit"] == "HP" and proof["conversion"] is None for proof in power["evidence"])
    for measurement in measures.values():
        for proof in measurement["evidence"]:
            assert proof["source_url"] == SOURCE
            assert proof["collected_at"] == COLLECTED.isoformat()
            assert proof["raw_value"] == detail.raw_specs[proof["label"]]
    assert row == before
    assert json.loads(json.dumps(measures, allow_nan=False)) == measures


def test_dry_wet_and_unspecified_weights_never_merge():
    measures = normalize({"Dry weight": "173 kg", "Weight incl. oil, gas, etc.": "196 kg", "Weight": "180 kg"})

    assert measures["weight_dry_kg"]["value"] == 173
    assert measures["weight_wet_kg"]["value"] == 196
    assert measures["weight_unspecified_kg"]["value"] == 180
    assert [measures[field]["nature"] for field in (
        "weight_dry_kg", "weight_wet_kg", "weight_unspecified_kg",
    )] == ["dry", "wet", "unspecified"]


@pytest.mark.parametrize("label,raw,field", [
    ("Wet weight", "180 kg (dry)", "weight_wet_kg"),
    ("Dry weight", "180 kg (wet)", "weight_dry_kg"),
    ("Poids à sec", "180 kg (tous pleins faits)", "weight_dry_kg"),
])
def test_weight_qualifier_cannot_assert_the_opposite_measurement_nature(label, raw, field):
    result = normalize({label: raw})[field]

    assert result["value"] is None and result["status"] == "unknown"
    assert any("contradicts" in warning for warning in result["warnings"])
    assert result["evidence"][0]["raw_value"] == raw
    assert result["evidence"][0]["original_value"] == 180


def test_unparsed_substantive_alias_blocks_the_other_alias_scalar():
    result = normalize({"Weight": "173 kg", "Poids": "180 (kg)"})["weight_unspecified_kg"]

    assert result["value"] is None and result["status"] == "unknown"
    assert {proof["raw_value"] for proof in result["evidence"]} == {"173 kg", "180 (kg)"}
    assert any("No supported" in warning for warning in result["warnings"])


@pytest.mark.parametrize("unavailable", ["Loading...", None, ""])
def test_unavailable_alias_retains_unknown_proof_without_blocking_documented_value(unavailable):
    result = normalize({"Weight": "173 kg", "Poids": unavailable})["weight_unspecified_kg"]

    assert result["value"] == 173 and result["status"] == "documented"
    unavailable_proof = next(proof for proof in result["evidence"] if proof["label"] == "Poids")
    assert unavailable_proof["raw_value"] == unavailable
    assert unavailable_proof["original_value"] is None
    assert unavailable_proof["conversion"] is None


@pytest.mark.parametrize("label,raw,field", [
    ("Power", "35 kW restricted", "power_kw"),
    ("Weight", "190 kg with ABS", "weight_unspecified_kg"),
    ("Wet weight", "190 kg for the ABS version", "weight_wet_kg"),
    ("Seat height", "780 mm (low seat option)", "seat_height_mm"),
    ("Hauteur de selle", "780 mm (selle basse en option)", "seat_height_mm"),
])
def test_single_configuration_value_is_preserved_without_becoming_general_scalar(label, raw, field):
    result = normalize({label: raw})[field]

    assert result["value"] is None and result["status"] == "unknown"
    assert any("scoped" in warning for warning in result["warnings"])
    assert result["evidence"][0]["raw_value"] == raw
    assert result["evidence"][0]["original_value"] is not None


@pytest.mark.parametrize("specs,field", [
    ({"Wet weight": "196 kg", "Kerb weight": "206 kg"}, "weight_wet_kg"),
    ({"Dry weight": "173 kg", "Poids à sec": "180 kg"}, "weight_dry_kg"),
    ({"Displacement": "745 ccm", "Engine size": "750 cm³"}, "displacement_ccm"),
    ({"Power": "42 kW", "Effect": "50 kW"}, "power_kw"),
    ({"Power": "42 kW (35 kW restricted version)"}, "power_kw"),
    ({"Wet weight": "200 kg (100 pounds)"}, "weight_wet_kg"),
    ({"Power": "100 PS (42 kW)"}, "power_kw"),
])
def test_conflicting_values_return_no_scalar_and_retain_every_source(specs, field):
    result = normalize(specs)[field]

    assert result["value"] is None
    assert result["status"] == "conflict"
    assert len(result["evidence"]) == 2
    assert {proof["raw_value"] for proof in result["evidence"]} == set(specs.values())
    assert result["warnings"]


def test_consistent_alias_values_agree_without_losing_proofs():
    result = normalize({"Power": "42.0 kW", "Effect": "42 kW"})["power_kw"]

    assert result["status"] == "documented" and result["value"] == 42.0
    assert {proof["label"] for proof in result["evidence"]} == {"Power", "Effect"}


@pytest.mark.parametrize("label", ["Power", "Power output", "Output", "Effect", "Puissance"])
def test_power_label_aliases_prefer_explicit_kw_to_ambiguous_hp(label):
    raw = "100 HP (73.5 kW) @ 9500 RPM"

    result = normalize({label: raw})["power_kw"]

    assert result["value"] == 73.5 and result["unit"] == "kW"
    assert all(proof["raw_value"] == raw for proof in result["evidence"])
    assert {proof["original_unit"] for proof in result["evidence"]} == {"kW", "HP"}
    assert any("convention" in warning for warning in result["warnings"])


@pytest.mark.parametrize("unit", ["HP", "hp", "bhp", "CV"])
def test_ambiguous_horsepower_does_not_become_kw_even_with_legacy_numeric(unit):
    result = normalize({"Power": f"100 {unit}"}, power_hp=100)["power_kw"]

    assert result["value"] is None and result["status"] == "unknown"
    assert result["evidence"][0]["original_unit"] == unit
    assert result["evidence"][0]["conversion"] is None


@pytest.mark.parametrize("unit", ["PS", "ch"])
def test_explicit_metric_horsepower_uses_its_own_documented_conversion(unit):
    result = normalize({"Power": f"100 {unit}"})["power_kw"]

    assert result["value"] == pytest.approx(73.549875)
    conversion = result["evidence"][0]["conversion"]
    assert conversion["factor"] == 0.73549875
    assert conversion["reference_url"].startswith("https://eur-lex.europa.eu/")


def test_explicit_kw_wins_over_parenthetical_rounded_metric_horsepower():
    result = normalize({"Power": "100 PS (73.5 kW)"})["power_kw"]

    assert result["value"] == 73.5
    assert len(result["evidence"]) == 2
    assert result["warnings"]


@pytest.mark.parametrize("label,raw,field,expected,unit", [
    ("Engine size", "1 234,5 ccm", "displacement_ccm", 1234.5, "cm³"),
    ("Displacement", "0.745 litres", "displacement_ccm", 745.0, "cm³"),
    ("Displacement", "10 cu. in.", "displacement_ccm", 163.87064, "cm³"),
    ("Dry weight", "100 pounds", "weight_dry_kg", 45.359237, "kg"),
    ("Seat height", "80,5 cm (adjustable)", "seat_height_mm", 805.0, "mm"),
    ("Seat height", "32 inches", "seat_height_mm", 812.8, "mm"),
    ("Torque", "50,2 N m @ 5000 RPM", "torque_nm", 50.2, "N·m"),
    ("Torque", "10 lbf·ft", "torque_nm", 13.558179483, "N·m"),
    ("Top speed", "100 mph", "top_speed_kmh", 160.9344, "km/h"),
    ("Maximum speed", "50 m/s", "top_speed_kmh", 180.0, "km/h"),
])
def test_supported_units_decimal_formats_and_qualifiers(label, raw, field, expected, unit):
    result = normalize({label: raw})[field]

    assert result["status"] == "documented" and result["value"] == pytest.approx(expected)
    assert result["unit"] == unit
    assert result["evidence"][0]["raw_value"] == raw
    assert result["evidence"][0]["conversion"]["reference_url"]


def test_native_units_do_not_conflict_with_rounded_parenthetical_alternatives():
    result = normalize({"Wet weight": "236.0 kg (520.3 pounds)"})["weight_wet_kg"]

    assert result["value"] == 236.0 and result["status"] == "documented"
    assert len(result["evidence"]) == 2


@pytest.mark.parametrize("raw", [
    "Loading...", "", "unknown", "n/a", "173", "-173 kg", "−173 kg",
    "0 kg", "NaN kg", "inf kg", "1,234.5 kg", "1.234,5 kg", None,
    "1e3 kg", "1e-3 kg", "10^3 kg", "bad-173 kg", "173 kg/m³",
    "9" * 1000 + " kg",
])
def test_invalid_unknown_or_unitless_values_stay_unknown_without_legacy_fallback(raw):
    result = normalize({"Weight": raw}, weight_kg=173)["weight_unspecified_kg"]

    assert result["value"] is None and result["status"] == "unknown"
    assert result["evidence"][0]["raw_value"] == raw
    assert result["warnings"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("raw", ["800-830 mm (adjustable)", "800 / 830 mm for N / S variants"])
def test_range_or_variant_alternatives_do_not_select_one_endpoint(raw):
    result = normalize({"Seat height": raw})["seat_height_mm"]

    assert result["status"] == "unknown" and result["value"] is None
    assert result["evidence"][0]["raw_value"] == raw
    assert result["warnings"]


def test_announced_speed_does_not_imply_independent_measurement():
    result = normalize({"Top speed": "180 km/h (claimed)"})["top_speed_kmh"]

    assert result["value"] == 180
    assert result["nature"] == "announced"
    assert result["evidence"][0]["raw_value"] == "180 km/h (claimed)"


def test_missing_sheet_has_all_fields_unknown_even_if_legacy_columns_are_populated():
    results = normalize_measurements({"weight_kg": 200, "power_hp": 100, "torque_nm": 80, "displacement_ccm": 745})

    assert set(results) == {
        "displacement_ccm", "weight_dry_kg", "weight_wet_kg", "weight_unspecified_kg",
        "power_kw", "torque_nm", "seat_height_mm", "top_speed_kmh",
    }
    assert all(result["value"] is None and result["status"] == "unknown" for result in results.values())
    json.dumps(results, allow_nan=False)

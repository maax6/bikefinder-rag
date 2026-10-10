from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from bikefinder_rag.catalog.identity import known_brands, normalize_identity, split_brand_model


def record(brand="Honda", model="CB 500", year=2000, **changes):
    row = {"brand": brand, "model": model, "year": year,
           "url": "https://catalog.example/sheet", "raw_specs": {},
           "scraped_at": datetime(2026, 10, 10, tzinfo=timezone.utc)}
    row.update(changes)
    return row


@pytest.mark.parametrize("brand,model,expected_brand,expected_model", [
    ("MV", "Agusta Brutale 800", "MV Agusta", "Brutale 800"),
    ("Moto", "Guzzi V7", "Moto Guzzi", "V7"),
    ("Moto", "Morini 3 1/2 Sport", "Moto Morini", "3 1/2 Sport"),
    ("Royal", "Enfield Classic 350", "Royal Enfield", "Classic 350"),
    ("Royal", "Pioneer 500", "Royal Pioneer", "500"),
    ("Atlas", "Honda CG 125", "Atlas Honda", "CG 125"),
    ("BSA", "Motors Gold Star 650", "BSA Motors", "Gold Star 650"),
])
def test_sourced_compound_brand_repair_preserves_original_identity(brand, model, expected_brand, expected_model):
    row = record(brand, model)
    original = deepcopy(row)

    result = normalize_identity(row)

    assert (result["brand"], result["model"]) == (expected_brand, expected_model)
    assert result["raw_identity"] == {"brand": brand, "model": model, "year": 2000}
    assert result["status"] == "corrected"
    assert result["warnings"] == ["brand_model_split_corrected"]
    assert result["identity_evidence"]["brand"]["source"]["url"].startswith("https://")
    assert row == original


def test_retained_fixture_supplies_brand_vocabulary_and_provenance():
    path = Path(__file__).parent / "fixtures/xadv_spec.html"
    html = path.read_bytes()
    labels = {option.get_text(" ", strip=True)
              for option in BeautifulSoup(html, "html.parser").select("select#CompBrand option")}

    assert labels <= set(known_brands())
    source = normalize_identity(record("MV", "Agusta Brutale 800"))["identity_evidence"]["brand"]["source"]
    assert source["fixture"] == "tests/fixtures/xadv_spec.html"
    assert source["fixture_sha256"] == hashlib.sha256(html).hexdigest()
    assert source["selector"] == "select#CompBrand option"


def test_enfield_is_not_merged_with_royal_enfield():
    enfield = normalize_identity(record("Enfield", "Classic 350"))
    royal = normalize_identity(record("Royal Enfield", "Classic 350"))

    assert enfield["brand"] == "Enfield"
    assert enfield["brand_id"] != royal["brand_id"]
    assert enfield["model_id"] != royal["model_id"]


@pytest.mark.parametrize("model", ["GSF 1200 N Bandit", "GSF 1200 S Bandit", "CBR 1000 RR-R Fireblade SP", "3 1/2 Sport"])
def test_model_suffix_does_not_invent_a_variant_or_family(model):
    result = normalize_identity(record("Suzuki", model))

    assert result["model"] == model
    assert result["variant"] is None and result["variant_id"] is None
    assert result["market"] is None
    assert "family_id" not in result and "launch_date" not in result


def test_stable_ids_ignore_sources_case_and_whitespace_but_keep_years_separate():
    first = normalize_identity(record())
    repeated = normalize_identity(record())
    spelling = normalize_identity(record(" honda ", "CB   500", url="https://other.example/sheet"))
    next_year = normalize_identity(record(year=2001))

    assert first == repeated
    assert first["brand_id"] == spelling["brand_id"]
    assert first["model_id"] == spelling["model_id"]
    assert first["model_year_id"] == spelling["model_year_id"]
    assert first["model_id"] == next_year["model_id"]
    assert first["model_year_id"] != next_year["model_year_id"]
    assert first["brand_id"].startswith("identity-v1:brand:")


@pytest.mark.parametrize("first,second", [
    ("CB 500", "CB 550"), ("500", "550"), ("V7", "V70"),
    ("CB-R", "CBR"), ("CB 500", "CB500"),
    ("GSF 1200 N Bandit", "GSF 1200 S Bandit"),
])
def test_model_ids_do_not_drop_numbers_punctuation_or_variant_suffixes(first, second):
    assert normalize_identity(record(model=first))["model_id"] != normalize_identity(record(model=second))["model_id"]


def test_explicit_variant_and_market_are_sourced_and_year_scoped():
    specs = {"Variant": "Touring ABS", "Market": "EU"}
    first = normalize_identity(record(raw_specs=specs))
    next_year = normalize_identity(record(year=2001, raw_specs=specs))
    other_market = normalize_identity(record(raw_specs={**specs, "Market": "US"}))

    assert (first["variant"], first["market"]) == ("Touring ABS", "EU")
    assert first["identity_evidence"]["variant"] == {"label": "Variant", "raw_value": "Touring ABS"}
    assert first["variant_id"] != next_year["variant_id"]
    assert first["variant_id"] != other_market["variant_id"]
    assert json.loads(json.dumps(first))["source"]["collected_at"] == "2026-10-10T00:00:00+00:00"


def test_conflicting_explicit_variants_remain_unknown_with_evidence():
    result = normalize_identity(record(raw_specs={"Variant": "Standard", "variant:": "Sport"}))

    assert result["variant"] is None and result["variant_id"] is None
    assert "conflicting_variant" in result["warnings"]
    assert result["status"] == "needs_review"
    assert len(result["identity_evidence"]["variant"]) == 2


@pytest.mark.parametrize("placeholder", ["", "Loading...", "Unknown", "Not documented", "N/A", "inconnu"])
def test_placeholder_variant_or_market_does_not_get_an_identifier(placeholder):
    result = normalize_identity(record(raw_specs={"Variant": placeholder, "Market": placeholder}))

    assert result["variant"] is None and result["market"] is None
    assert result["variant_id"] is None


def test_source_identity_conflicts_are_visible_and_never_overwrite_raw_values():
    result = normalize_identity(record(raw_specs={"Model name": "Honda CB 550", "Year of manufacture": "2001"}))

    assert result["model"] == "CB 500" and result["model_year"] == 2000
    assert result["raw_identity"]["model"] == "CB 500"
    assert set(result["warnings"]) == {"source_name_conflict", "source_year_conflict"}
    assert result["status"] == "needs_review"


def test_model_label_conflict_is_visible_and_preserves_source_evidence():
    result = normalize_identity(record(raw_specs={"Model": "Honda CB 550"}))

    assert result["model"] == "CB 500"
    assert result["raw_identity"]["model"] == "CB 500"
    assert result["identity_evidence"]["names"] == [{"label": "Model", "raw_value": "Honda CB 550"}]
    assert result["warnings"] == ["source_name_conflict"]
    assert result["status"] == "needs_review"


def test_consistent_model_label_keeps_normalized_identity_and_evidence():
    result = normalize_identity(record(raw_specs={"Model": "Honda CB 500"}))

    assert result["model"] == "CB 500"
    assert result["identity_evidence"]["names"] == [{"label": "Model", "raw_value": "Honda CB 500"}]
    assert result["warnings"] == []
    assert result["status"] == "normalized"


@pytest.mark.parametrize("brand,model", [("FutureWorks", "500 Sport"), ("Moto", "GuzziV7")])
def test_unrecognized_or_unseparated_brand_is_not_guessed(brand, model):
    result = normalize_identity(record(brand, model))

    assert (result["brand"], result["model"]) == (brand, model)
    assert result["status"] == "needs_review"
    assert "brand_not_in_vocabulary" in result["warnings"]
    assert result["brand_id"] and result["model_id"]


@pytest.mark.parametrize("year", [None, True, "2000", 2000.5, 0])
def test_invalid_model_year_never_gets_a_year_identifier(year):
    result = normalize_identity(record(year=year))

    assert result["model_year"] is None and result["model_year_id"] is None
    assert result["raw_identity"]["year"] == year
    assert result["status"] == "needs_review"


def test_known_brand_requires_an_exact_boundary_not_a_similar_prefix():
    assert split_brand_model("Hondaline 500") == (None, "Hondaline 500")
    assert split_brand_model("Moto Guzzi V7") == ("Moto Guzzi", "V7")

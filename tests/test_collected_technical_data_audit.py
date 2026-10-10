"""Collected coverage is a read-only source snapshot, not global fitment proof."""

import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit_collected_technical_data.py"
spec = importlib.util.spec_from_file_location("collected_technical_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def record(rows, **changes):
    return {"identity": {"brand": "Honda", "model": "Example", "year": 2000, "market": None},
            "spec_rows": rows, "equipment_evidence": [], "parser_version": "fixture-v1", **changes}


def make_database(tmp_path, pages):
    path = tmp_path / "crawl.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE pages(url TEXT PRIMARY KEY,year INTEGER,state TEXT,result TEXT)")
        connection.executemany("INSERT INTO pages VALUES (?,?,?,?)", [
            (url, 2000, state, json.dumps(result) if result is not None else None)
            for url, state, result in pages
        ])
    return path


def test_repeated_rows_count_separately_but_field_fiche_count_deduplicates(tmp_path):
    row = {"section": "Châssis", "label": "Freins", "value": "ABS en option"}
    evidence = {"term": "ABS", "text": "ABS en option", "status": "unclassified"}
    database = make_database(tmp_path, [
        ("a", "success", record([row, row], equipment_evidence=[evidence, evidence])),
        ("b", "success", record([row])),
    ])

    report = audit.audit_database(database)

    success = report["success"]
    assert success["counts"]["parsed_fiches"] == 2
    assert success["counts"]["spec_row_count"] == 3
    assert success["counts"]["exact_duplicate_spec_rows"] == 1
    assert success["by_label"]["Freins"]["row_count"] == 3
    assert success["by_label"]["Freins"]["fiche_count"] == 2
    assert success["by_section_and_label"]["Châssis"]["Freins"]["fiche_count"] == 2
    assert success["equipment_candidates"]["by_term"]["ABS"]["row_count"] == 2
    assert success["equipment_candidates"]["by_term"]["ABS"]["fiche_count"] == 1


def test_needs_review_is_separate_and_retryable_payload_never_expands_success(tmp_path):
    database = make_database(tmp_path, [
        ("accepted", "success", record([{"section": "Moteur", "label": "Couple", "value": "100 Nm"}])),
        ("review", "needs_review", record([{"section": "Moteur", "label": "Puissance", "value": "50 kW"}])),
        ("retry", "retryable", record([{"section": "Équipement", "label": "ABS", "value": "Oui"}])),
        ("pending", "pending", None),
    ])

    report = audit.audit_database(database)

    assert report["success"]["counts"]["parsed_fiches"] == 1
    assert set(report["success"]["by_label"]) == {"Couple"}
    assert report["needs_review"]["counts"]["parsed_fiches"] == 1
    assert set(report["needs_review"]["by_label"]) == {"Puissance"}
    assert report["queue"]["nonaccepted_states_excluded_from_technical_aggregates"] == ["pending", "retryable"]


def test_missing_loading_and_unknown_text_remain_data_gaps_not_equipment_absence(tmp_path):
    rows = [{"section": "Moteur", "label": "Puissance", "value": "Loading..."},
            {"section": "Châssis", "label": "Poids", "value": ""},
            {"section": "Châssis", "label": "Freins", "value": "N/A"},
            {"section": "Train avant", "label": "Fourche", "value": "Fourche WP Ø nc, déb : 147 mm"}]
    database = make_database(tmp_path, [("a", "success", record(
        rows, identity={"brand": "", "model": "Example", "year": None, "market": None}, price_markets=["France"],
    ))])

    success = audit.audit_database(database)["success"]

    assert success["value_statuses"] == {
        "loading_placeholder": 1, "missing_or_nontext": 1, "unknown_placeholder": 1, "source_text": 1,
    }
    assert success["counts"]["rows_with_partial_unknown_markers"] == 1
    assert success["by_label"]["Fourche"]["fiches_with_nonempty_source_text"] == 1
    assert success["by_label"]["Fourche"]["rows_with_partial_unknown_markers"] == 1
    assert success["counts"]["fiches_with_unknown_or_missing_values"] == 1
    assert success["counts"]["fiches_without_equipment_candidates"] == 1
    assert success["counts"]["fiches_with_explicit_spec_market"] == 0
    assert success["counts"]["fiches_with_price_market_text"] == 1
    assert success["missing_identity_fields"] == {"brand": 1, "year": 1}
    assert set(success["by_documented_year"]) == {"unknown"}
    assert "absence" in success["equipment_candidates"]["semantics"]
    assert not any(key in success for key in ("abs_absent", "no_abs", "worldwide_coverage"))


def test_readonly_transaction_sees_a_consistent_snapshot_during_wal_writes(tmp_path):
    database = make_database(tmp_path, [("a", "success", record([]))])
    with audit.read_only_snapshot(database) as reader:
        assert reader.execute("SELECT count(*) FROM pages").fetchone()[0] == 1
        with sqlite3.connect(database) as writer:
            writer.execute("INSERT INTO pages VALUES ('b',2001,'pending',NULL)")
        assert reader.execute("SELECT count(*) FROM pages").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only"):
            reader.execute("DELETE FROM pages")
    assert audit.audit_database(database)["queue"]["discovered_urls"] == 2


def test_bad_result_is_reported_without_inventing_rows_and_examples_are_bounded(tmp_path):
    database = make_database(tmp_path, [("a", "success", record([])), ("b", "success", None)])

    report = audit.audit_database(database, max_fiche_examples=0)

    assert report["success"]["counts"]["state_rows"] == 2
    assert report["success"]["counts"]["parsed_fiches"] == 1
    assert report["success"]["counts"]["missing_or_invalid_result"] == 1
    assert report["success"]["counts"]["spec_row_count"] == 0
    assert report["success"]["fiche_summary_examples"] == []
    assert report["success"]["fiche_examples_truncated"] is True
    assert report["needs_review"]["counts"]["parsed_fiches"] == 0
    assert len(report["logical_snapshot_sha256"]) == 64
    assert any("worldwide completeness" in text for text in report["limitations"])
    json.dumps(report, allow_nan=False)

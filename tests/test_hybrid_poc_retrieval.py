"""Isolation and factual-scope checks for the frozen technical retrieval POC."""

import importlib.util
from pathlib import Path
import sqlite3

import numpy as np
import pytest


SPEC = importlib.util.spec_from_file_location("hybrid_poc_retrieval", Path(__file__).parents[1] / "scripts/hybrid_poc_retrieval.py")
retrieval = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retrieval)


@pytest.fixture
def index(tmp_path):
    records = []
    passages = []
    for object_id, year, text in [
        ("old", 2000, "Assistance au freinage : ABS en option"),
        ("new", 2001, "Assistance au freinage : ABS de série"),
        ("other", 2000, "Transmission : boîte à 6 rapports"),
    ]:
        records.append({"id": object_id, "name": f"Honda Exemple {year}", "brand": "Honda", "model": "Exemple", "year": year,
                        "source_url": f"https://source.invalid/{object_id}", "identity": {"market": None}, "price_markets": ["France"],
                        "spec_rows": [{"section": "Train avant", "label": "Freinage", "value": "Deux disques"},
                                      {"section": "Train arrière", "label": "Freinage", "value": "Un disque"}]})
        passages.append({"id": f"{object_id}:section:0", "object_id": object_id, "section": "Équipement de série", "text": text,
                         "source_url": f"https://source.invalid/{object_id}"})
    db = tmp_path / "index.sqlite3"
    retrieval.build_index({"created_at": "2026-10-10", "records": records, "passages": passages}, db)
    # The 2001 passage is deliberately closer than the correct 2000 passage.
    vectors = np.zeros((3, 1024), dtype=np.float32)
    vectors[0, :2] = [0.5, 0.5]
    vectors[1, 0] = 1
    vectors[2, 1] = 1
    retrieval.save_vectors([p["id"] for p in passages], vectors, db)
    return db


def vector():
    result = np.zeros(1024, dtype=np.float32)
    result[0] = 1
    return result


def test_year_scope_is_applied_before_similarity_and_never_relaxed(index):
    unscoped = retrieval.retrieve("ABS", topk=1, db_path=index, query_vector=vector())
    scoped = retrieval.retrieve("ABS", {"year": 2000, "object_ids": ["old"]}, topk=1, db_path=index, query_vector=vector())
    assert unscoped[0]["year"] == 2001
    assert scoped[0]["id"] == "old:section:0"
    assert "en option" in scoped[0]["text"]
    assert retrieval.retrieve("ABS", {"year": 1999}, db_path=index, query_vector=vector()) == []


def test_unknown_market_not_inferred_from_french_prices(index):
    unknown = retrieval.sql_filter(db_path=index, market="unknown")
    assert len(unknown) == 3
    assert all(row["market"] is None for row in unknown)
    assert retrieval.sql_filter(db_path=index, market="France") == []


def test_optional_equipment_is_not_returned_as_standard(index):
    retrieval.ingest_decisions([
        {"object_id": "old", "equipment": "ABS", "prediction": {"status": "optional", "market": "unknown"}},
        {"object_id": "new", "equipment": "ABS", "prediction": {"status": "standard", "market": "unknown"}},
    ], index, provider="hybrid")
    standard = retrieval.sql_filter(db_path=index, equipment="ABS", status="standard", provider="hybrid")
    optional = retrieval.sql_filter(db_path=index, equipment="ABS", status="optional", provider="hybrid")
    assert [r["id"] for r in standard] == ["new"]
    assert [r["id"] for r in optional] == ["old"]
    assert standard[0]["equipment_market"] is None
    with pytest.raises(ValueError, match="provider"):
        retrieval.sql_filter(db_path=index, equipment="ABS", status="standard")


def test_unclassified_or_provider_error_does_not_become_an_equipment_fact(index):
    assert retrieval.sql_filter(db_path=index, equipment="ABS", status="standard", provider="hybrid") == []
    assert retrieval.ingest_decisions([{"error_type": "HTTPError"}], index, provider="jev") == 0
    assert retrieval.sql_filter(db_path=index, equipment="ABS", status="standard", provider="jev") == []
    with pytest.raises(ValueError, match="Invalid equipment status"):
        retrieval.ingest_decisions([{"object_id": "old", "equipment": "ABS", "status": "unclassified"}], index, provider="jev")


def test_sql_returns_complete_paginated_objects_dense_retrieval_is_topk(index):
    complete = retrieval.sql_filter(db_path=index)
    pages = [r for offset in range(3) for r in retrieval.sql_filter(db_path=index, limit=1, offset=offset)]
    assert pages == complete
    assert len(complete) == 3
    assert len(retrieval.retrieve("Freins", topk=1, db_path=index, query_vector=vector())) == 1


def test_original_specs_keep_duplicate_labels_and_distinct_sections(index):
    with sqlite3.connect(index) as conn:
        rows = conn.execute("SELECT section,label,value FROM specifications WHERE object_id='old' ORDER BY ordinal").fetchall()
    assert rows == [("Train avant", "Freinage", "Deux disques"), ("Train arrière", "Freinage", "Un disque")]


def test_invalid_scope_and_cross_object_decision_conflicts_fail_closed(index):
    assert retrieval.retrieve("ABS", {"object_ids": []}, db_path=index) == []
    with pytest.raises(ValueError, match="Unsupported filters"):
        retrieval.sql_filter(db_path=index, guessed_market="France")
    with pytest.raises(ValueError, match="named equipment"):
        retrieval.sql_filter(db_path=index, status="standard")
    with pytest.raises(ValueError, match="Conflicting decisions"):
        retrieval.ingest_decisions([
            {"object_id": "old", "equipment": "ABS", "status": "standard"},
            {"object_id": "old", "equipment": "ABS", "status": "optional"},
        ], index, provider="jev")


def test_vector_index_cannot_claim_an_unseen_source_passage(index):
    with pytest.raises(ValueError, match="unknown source passage"):
        retrieval.save_vectors(["invented-id"], np.array([vector()]), index)

"""Prepared evidence resolution through its public local retrieval interface."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from bikefinder_rag.catalog.experiment import Corpus
from bikefinder_rag.embeddings import embedder


@pytest.fixture
def prepared(tmp_path):
    rows = [{"id": "bmw", "brand": "BMW", "model": "R 1300 RT", "year": 2025, "source_sha256": "catalogue-bmw", "source_url": "https://catalogue.test/bmw", "record": {"technical_sections": []}},
            {"id": "honda", "brand": "Honda", "model": "GL 1800 GOLDWING Tour", "year": 2018, "source_sha256": "catalogue-honda", "source_url": "https://catalogue.test/honda", "record": {"technical_sections": []}}]
    sources, docs = [], []
    for id, brand, model, year, market, family, aliases, binding in [
        ("official-bmw", "BMW", "R 1300 RT", 2026, "USA", "rt", ["RT", "R 1300 RT"], rows[0]),
        ("official-honda", "Honda", "GL 1800 GOLDWING Tour", 2018, "USA", "goldwing", ["Gold Wing", "Goldwing"], rows[1])]:
        snapshot = tmp_path / (id + ".html")
        snapshot.write_text("<article>Transmission documentée</article>")
        sha = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        sources.append({"id": id, "brand": brand, "family": family, "aliases": aliases,
                        "snapshot": str(snapshot), "sha256": sha, "sql_bindings": [{k: binding[k] for k in ["id", "brand", "model", "year", "source_sha256"]}]})
        docs.append({"id": id + ":1", "object_id": id, "brand": brand, "model": model, "year": year, "binding_year": binding["year"],
                     "publisher": brand, "kind": "manufacturer", "market": market, "published": "2025-04-29" if brand == "BMW" else "2017-10-25", "family": family,
                     "section": "Transmission", "original_text": "Transmission documentée", "source_url": "https://official.test/" + id, "source_sha256": sha})
    documents = tmp_path / "documents.jsonl"
    documents.write_text("".join(json.dumps(d) + "\n" for d in docs))
    vectors = tmp_path / "vectors.npy"
    np.save(vectors, np.array([[1.] + [0.] * 1023] * 2))
    (tmp_path / "manifest.json").write_text(json.dumps({"revision": embedder.MODEL_REVISION, "sources": sources,
        "files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [documents, vectors]}}))
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params):
            assert sql.startswith("SELECT") and params
            self.selected = [r for r in rows if r["id"] in params[0]]
            self.description = [SimpleNamespace(name=k) for k in rows[0]]
        def fetchall(self): return [tuple(r.values()) for r in self.selected]
    conn = SimpleNamespace(cursor=lambda: Cursor())
    corpus = Corpus(tmp_path, encode=lambda q: [1.] + [0.] * 1023, rerank=lambda q, docs: [1.] * len(docs))
    return corpus, conn, rows, tmp_path


def test_sql_binding_year_does_not_substitute_constructor_model_year(prepared):
    corpus, conn, _, _ = prepared
    result = corpus.retrieve(conn, "BMW RT 2025 aux USA : transmission ?", [])
    assert not result["passages"]
    assert result["missing"]


def test_edition_qualifier_does_not_eliminate_other_requested_family(prepared):
    corpus, conn, _, _ = prepared
    result = corpus.retrieve(conn, "Gold Wing édition Tour et BMW RT : transmissions ?", [])
    assert {p["identity"]["brand"] for p in result["passages"]} == {"Honda", "BMW"}


def test_unknown_version_is_not_replaced_with_normal_model(prepared):
    corpus, conn, _, _ = prepared
    result = corpus.retrieve(conn, "Honda Gold Wing version Galaxie : transmission ?", [])
    assert not result["passages"]
    assert result["missing"]


def test_catalogue_binding_changed_cannot_publish_prepared_evidence(prepared):
    corpus, conn, rows, _ = prepared
    rows[0]["source_sha256"] = "changed"
    with pytest.raises(ValueError, match="live SQL"):
        corpus.retrieve(conn, "BMW RT", [])


def test_snapshot_amended_requires_new_preparation(prepared):
    corpus, conn, _, root = prepared
    (root / "official-bmw.html").write_text("Amended source")
    with pytest.raises(ValueError, match="changed"):
        corpus.retrieve(conn, "BMW RT", [])


def test_rt_does_not_match_partir(prepared):
    corpus, conn, _, _ = prepared
    assert not corpus.retrieve(conn, "À partir de quelle année ?", [])["passages"]


def test_two_markets_do_not_erase_explicit_model_year(prepared):
    corpus, conn, _, _ = prepared
    assert not corpus.retrieve(conn, "BMW RT 2024 en France et aux USA", [])["passages"]


def test_followup_unknown_version_keeps_its_qualifier(prepared):
    corpus, conn, _, _ = prepared
    assert not corpus.retrieve(conn, "Et cette version Galaxie ?", [{"role": "user", "content": "Honda Gold Wing"}])["passages"]

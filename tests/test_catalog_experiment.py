"""The experimental public answer interface must publish useful verified facts."""
from bikefinder_rag.agent import catalog_experiment

import pytest
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_one_local_answer_uses_manufacturer_proof_without_source_dump():
    calls = []
    proof = {"id": "P1", "passage_id": "bmw:asa", "identity": {"object_id": "bmw-release", "brand": "BMW", "model": "R 1300 RT", "year": 2025},
             "section": "Transmission", "text": "R 1300 RT : ASA disponible en option ; changement de vitesse manuel ou automatique.",
             "source_url": "https://www.press.bmwgroup.com/release", "publisher": "BMW", "kind": "manufacturer"}
    class Corpus:
        def retrieve(self, conn, question, history):
            return {"passages": [proof], "missing": [], "timing": {}, "scopes": ["BMW RT"]}
    def generate(question, passages, remaining):
        calls.append(passages)
        return {"claims": [{"text": "La BMW R 1300 RT propose l’ASA en option, avec changement de vitesse manuel ou automatique.", "sources": ["P1"]}]}, {"model": "ministral-3:3b"}
    def verify(question, claims, passages):
        return {"accepted": True, "verified_claim_indices": [0], "coverage_verified": True, "jev_calls": 1}
    result = catalog_experiment.answer_question(None, "L’ASA sur la BMW RT est-il fourni de série ?", corpus=Corpus(), generator=generate, verifier=verify)
    assert len(calls) == 1
    assert "en option" in result["answer"]
    assert "[1]" in result["answer"] and proof["source_url"] in result["answer"]
    assert "fiche" not in result["answer"].lower()
    assert "Complément en lecture directe" not in result["answer"]
    assert result["research"]["local_planner_calls"] == 0
    assert result["generation"]["published"] is True


def test_written_source_numbers_can_be_read_but_not_changed():
    p = {"id": "P1", "identity": {"brand": "Honda", "model": "Gold Wing", "year": 2018},
         "section": "Transmission", "text": "six-speed manual transmission or seven-speed automatic Dual Clutch Transmission", "published": "2017-10-25"}
    valid = {"claims": [{"text": "La Gold Wing 2018 propose une boîte manuelle à 6 rapports ou une DCT à 7 rapports.", "sources": ["P1"]}]}
    assert catalog_experiment.validate_candidate(valid, [p]) == valid["claims"]
    with pytest.raises(ValueError, match="numeric"):
        catalog_experiment.validate_candidate({"claims": [{"text": "Boîte à 9 rapports", "sources": ["P1"]}]}, [p])


def test_unverified_claim_is_not_published_as_a_fast_success():
    class Corpus:
        def retrieve(self, *args):
            return {"passages": [{"id": "P1", "identity": {"brand": "BMW", "model": "R 1300 RT", "year": 2025}, "text": "ASA en option", "section": "Transmission", "source_url": "https://www.press.bmwgroup.com/asa"}], "timing": {}}
    def generator(*args):
        return {"claims": [{"text": "ASA de série", "sources": ["P1"]}]}, {}
    def verifier(*args):
        pytest.fail("The literal standard-equipment guard must reject before Jev")
    result = catalog_experiment.answer_question(None, "ASA de série ?", corpus=Corpus(), generator=generator, verifier=verifier)
    assert result["generation"]["published"] is False
    assert "ASA de série" not in result["answer"]


def test_missing_identity_does_not_call_the_writer():
    class Corpus:
        def retrieve(self, *args):
            return {"passages": [], "missing": [{"message": "Édition non documentée"}], "timing": {}}
    def generator(*args):
        pytest.fail("No sources must not call the generator")
    result = catalog_experiment.answer_question(None, "Édition inconnue", corpus=Corpus(), generator=generator)
    assert result["generation"]["call_attempted"] is False
    assert "version" in result["answer"]


def test_constructor_list_facts_are_not_assigned_as_headings(tmp_path):
    source_documents = runpy.run_path(str(ROOT / "scripts/prepare_catalog_experiment.py"))["source_documents"]
    snapshot = tmp_path / "source.html"
    snapshot.write_text('<h1>Navigation</h1><article><h1>2018 Gold Wing</h1><p class="title__timeplace">October 25, 2017, U.S.A.</p><p>Transmission</p><p>six-speed manual or seven-speed DCT.</p><ul><li>Six-speed manual transmission</li><li>Radial brakes</li></ul></article>')
    source = {"id": "official", "publisher": "Honda", "brand": "Honda", "model": "Gold Wing", "model_year": 2018,
              "published": "2017-10-25", "market": "USA", "family": "goldwing", "catalog_binding_year": 2018,
              "url": "https://global.honda/en/release"}
    docs = source_documents(source, snapshot)
    assert any(d["original_text"] == "Six-speed manual transmission" for d in docs)
    assert next(d for d in docs if d["original_text"] == "Radial brakes")["section"] != "Six-speed manual transmission"
    assert all("Navigation" not in d["text"] for d in docs)


def test_source_date_in_url_does_not_count_as_an_answered_year():
    facts = runpy.run_path(str(ROOT / "scripts/evaluate_catalog_experiment.py"))["facts"]
    flags = facts("DCT à 7 rapports [1](https://global.honda/en/2017/2171025Gold-Wing-2018.html)")
    assert flags["honda2018"] is False
    assert flags["announce2017"] is False


def test_retrieval_integrity_failure_is_reported_without_publishing():
    class Corpus:
        def retrieve(self, *args):
            raise ValueError("Snapshot changed")
    result = catalog_experiment.answer_question(None, "BMW RT", corpus=Corpus())
    assert result["generation"]["published"] is False
    assert result["generation"]["call_attempted"] is False
    assert "sources locales" in result["answer"]

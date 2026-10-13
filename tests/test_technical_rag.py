from copy import deepcopy
from unittest.mock import Mock

import numpy as np
import pytest

from bikefinder_rag.agent import loop, rag_router
from bikefinder_rag.catalog import technical_rag as rag
from bikefinder_rag.embeddings import embedder


@pytest.fixture
def fiche():
    return {"id": "exact", "brand": "Honda", "model": "Example", "year": 2025,
            "source_url": "https://source.test/exact", "source_sha256": "original",
            "record": {"spec_rows": [
                {"section": "Moteur", "label": "Puissance", "value": "73 ch à 8 500 tr/min"},
                {"section": "Équipement de série", "label": "ABS", "value": "ABS en option"}],
                "technical_sections": [
                    {"section": "Châssis", "text": "Hauteur de selle : 800 mm"},
                    {"section": "Moteur", "text": "Puissance : 73 ch à 8 500 tr/min"},
                    {"section": "Infos pratiques", "text": "A2 ou bridable ; permis : A, A2"},
                    {"section": "Équipement de série", "text": "ABS en option"}]}}


def plan(fields=None, **extra):
    return {"models": [{"brand": "Honda", "model": "Example", "year": 2025}],
            "identity": {}, "fields": fields or ["license", "power_ch"], "a2_context": True, **extra}


@pytest.fixture
def local_rag(tmp_path, monkeypatch, fiche):
    monkeypatch.setenv("BIKEFINDER_RAG_CACHE", str(tmp_path))
    def rows(_conn, _sql, params):
        return [deepcopy(fiche)] if params == ["Honda", "Example", 2025] else []
    monkeypatch.setattr(rag, "_rows", rows)
    documents = Mock(side_effect=lambda texts: [[1.0] + [0.0] * 1023 for _ in texts])
    queries = Mock(return_value=[1.0] + [0.0] * 1023)
    monkeypatch.setattr(embedder, "embed_texts", documents)
    monkeypatch.setattr(embedder, "embed_text", queries)
    return documents, queries


def test_exact_identity_before_embeddings_and_no_nearby_year(local_rag):
    docs, queries = local_rag
    request = plan(); request["models"][0]["year"] = 2024
    result = rag.answer_from_sources(object(), "Permis A2 en 2024 ?", request)
    assert result["route"] == "clarification"
    assert not result["evidence"]["retrieval_executed"]
    assert "2024" in result["answer"] and "substituée" in result["answer"]
    docs.assert_not_called(); queries.assert_not_called()


def test_duplicate_sql_identity_does_not_choose_a_variant(local_rag, monkeypatch, fiche):
    monkeypatch.setattr(rag, "_rows", lambda *args: [deepcopy(fiche), deepcopy(fiche)])
    assert rag.answer_from_sources(object(), "A2 ?", plan())["route"] == "clarification"
    local_rag[0].assert_not_called()


def test_sql_identity_tolerates_only_case_changes(local_rag, monkeypatch, fiche):
    queries = []
    def rows(conn, sql, params):
        queries.append(sql)
        return [deepcopy(fiche)]
    monkeypatch.setattr(rag, "_rows", rows)
    requested = plan()
    requested["models"][0]["model"] = "EXAMPLE"
    result = rag.answer_from_sources(object(), "A2 ?", requested)
    assert result["evidence"]["sources"][0]["model"] == "Example"
    assert "lower(model)=lower(%s)" in queries[0] and "year=%s" in queries[0]


def test_unverified_coverage_keeps_literal_facts_without_claiming_completeness(local_rag):
    check = lambda *args: {"fields": {"power_ch": "unverified"}, "jev_calls": 0}
    result = rag.answer_from_sources(object(), "Puissance pour A2 ?", plan(["power_ch"]), check)
    assert "73 ch à 8 500" in result["answer"] and "n'a pas pu être vérifiée" in result["answer"]
    assert not result["evidence"]["sources"][0]["coverage"]["power_ch"]["covered"]
    assert result["route"] == "rag_partial"


def test_sources_preserve_values_qualifiers_and_identity(local_rag):
    result = rag.answer_from_sources(object(), "A2, puissance et ABS ?", plan(["license", "power_ch", "equipment"]))
    assert "73 ch à 8 500" in result["answer"] and "ABS en option" in result["answer"]
    assert "https://source.test/exact" in result["answer"]
    assert "pas des documents officiels" in result["answer"]
    assert result["evidence"]["legal_certification"] is False
    assert all(p["object_id"] == "exact" and p["year"] == 2025 for p in result["evidence"]["sources"][0]["passages"])


def test_source_cache_reuses_documents_but_encodes_every_question(local_rag):
    first = rag.answer_from_sources(object(), "Quelle puissance pour A2 ?", plan())
    second = rag.answer_from_sources(object(), "Quelle mention A2 ?", plan())
    assert not first["evidence"]["retrievals"][0]["document_cache_hit"]
    assert second["evidence"]["retrievals"][0]["document_cache_hit"]
    assert local_rag[0].call_count == 1 and local_rag[1].call_count == 2


def test_changed_source_reencodes_the_fiche(local_rag, fiche):
    rag.answer_from_sources(object(), "A2 ?", plan())
    fiche["record"]["technical_sections"][1]["text"] = "Puissance : 74 ch"
    rag.answer_from_sources(object(), "A2 ?", plan())
    assert local_rag[0].call_count == 2


def test_corrupt_but_finite_cached_vectors_are_recomputed(local_rag, tmp_path):
    rag.answer_from_sources(object(), "A2 ?", plan())
    path = next(tmp_path.glob("*.npz"))
    with np.load(path, allow_pickle=False) as saved:
        payload = dict(saved)
    payload["vectors"] = np.roll(payload["vectors"], 1, axis=1)
    np.savez(path, **payload)
    rag.answer_from_sources(object(), "A2 ?", plan())
    assert local_rag[0].call_count == 2


def test_damaged_npz_member_is_recomputed(local_rag, tmp_path):
    from zipfile import ZipFile
    rag.answer_from_sources(object(), "A2 ?", plan())
    path = next(tmp_path.glob("*.npz"))
    with ZipFile(path) as archive:
        member = archive.getinfo("vectors.npy")
        offset = member.header_offset + 30 + len(member.filename) + len(member.extra)
    payload = bytearray(path.read_bytes())
    payload[offset + member.compress_size - 1] ^= 1
    path.write_bytes(payload)
    result = rag.answer_from_sources(object(), "A2 ?", plan())
    assert local_rag[0].call_count == 2
    assert not result["evidence"]["retrievals"][0]["document_cache_hit"]


def test_missing_a2_mention_is_unknown_not_ineligible(local_rag, fiche):
    fiche["record"]["technical_sections"][2]["text"] = "La moto est accessible aux permis : A"
    result = rag.answer_from_sources(object(), "Mention A2 ?", plan())
    assert "non retrouvée" in result["answer"] and "ne prouve pas une incompatibilité" in result["answer"]
    assert any(m.get("field") == "a2_mention" for m in result["evidence"]["missing"])
    assert "73 ch" in result["answer"]


def test_legal_certificate_is_missing_even_when_source_mentions_a2(local_rag):
    result = rag.answer_from_sources(object(), "Prouve mon bridage A2", plan(legal_proof_required=True))
    assert result["route"] == "rag_partial"
    assert any(m["kind"] == "authority" for m in result["evidence"]["missing"])
    assert "je ne certifie pas" in result["answer"]


def test_required_source_outside_top5_is_explicitly_added(local_rag, fiche):
    fiche["record"]["technical_sections"] = [{"section": str(n), "text": "Roue : 17 pouces"} for n in range(6)] + fiche["record"]["technical_sections"][1:]
    result = rag.answer_from_sources(object(), "Puissance et A2", plan())
    passages = result["evidence"]["sources"][0]["passages"]
    assert any(p["selection_reason"] == "required_field" and p["section"] == "Moteur" for p in passages)
    assert all(c["source_passages_available"] for c in result["evidence"]["sources"][0]["coverage"].values())


def test_unmatched_spec_row_is_not_claimed_as_a_source_passage(local_rag, fiche):
    fiche["record"]["spec_rows"][0]["value"] = "Invented 120 ch"
    result = rag.answer_from_sources(object(), "A2 puissance", plan())
    assert "Invented 120" not in result["answer"]
    assert any(m.get("field") == "power_ch" for m in result["evidence"]["missing"])


def test_embedding_load_is_pinned_and_local_only(monkeypatch):
    import sentence_transformers
    loader = Mock()
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", loader)
    embedder._get_model.cache_clear()
    try:
        embedder._get_model()
        assert loader.call_args.kwargs["local_files_only"] is True
        assert loader.call_args.kwargs["revision"] == embedder.MODEL_REVISION
    finally:
        embedder._get_model.cache_clear()


def jev_choices(fields=("license", "power_ch"), intent="source_facts"):
    return {"answers": {"identity_binding": {"choice": "recognized", "confidence": .99},
                        "intent": {"choice": intent, "confidence": .99},
                        **{"field_" + f: {"choice": "yes" if f in fields else "no", "confidence": .99} for f in rag_router.FIELDS}}}


@pytest.fixture
def connected(monkeypatch, local_rag):
    monkeypatch.setenv("BIKEFINDER_JEV_ROUTER", "1")
    monkeypatch.setenv("BIKEFINDER_JEV_RAG", "1")
    monkeypatch.setattr(rag_router.legacy, "entities", lambda conn, q:
                        ([{"brand": "Honda", "model": "Example"}] if "Example" in q else [], []))
    monkeypatch.setattr(rag_router, "classify_sources", lambda *args: (jev_choices(), 1))
    monkeypatch.setattr(rag_router, "check_source_coverage", lambda q, fields, row, docs:
                        {"fields": {f: "complete" for f in fields}, "jev_calls": 0})
    monkeypatch.setattr(loop, "_run_agent_ollama", Mock(side_effect=AssertionError("Generator must not run")))


def test_real_agent_dispatches_to_rag_and_records_evidence(connected):
    answer, history = loop.run_agent(object(), None, "Honda Example 2025 : A2 et puissance ?", [], provider="ollama")
    assert "73 ch" in answer and history[-1]["_catalog_route"] == "rag_sources"
    assert history[-1]["_catalog_evidence"]["retrieval_executed"]
    assert history[-1]["_catalog_jev_calls"] == 1


def test_followup_replaces_year_without_using_previous_source(connected):
    _answer, history = loop.run_agent(object(), None, "Honda Example 2025 : A2 ?", [], provider="ollama")
    answer, new_history = loop.run_agent(object(), None, "Et en 2024, pour A2 ?", history, provider="ollama")
    assert "2024" in answer and "73 ch" not in answer
    assert not new_history[-1]["_catalog_evidence"]["retrieval_executed"]


def test_missing_year_never_defaults_to_latest(connected):
    result = rag_router.route_question(object(), "Honda Example pour A2 ?")
    assert result["route"] == "clarification" and "millésime" in result["answer"]


def test_jev_failure_has_no_remote_provider_fallback(connected, monkeypatch):
    monkeypatch.setattr(rag_router, "classify_sources", Mock(side_effect=RuntimeError("unavailable")))
    answer, history = loop.run_agent(object(), None, "Honda Example 2025 A2 ?", [], provider="ollama")
    assert "indisponible" in answer and history[-1]["_catalog_route"] == "rag_error"


def test_closed_classifier_rejects_unprovided_choices(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake")
    monkeypatch.setenv("BIKEFINDER_RAG_ROUTER_CACHE", str(tmp_path))
    body = jev_choices(); body["answers"]["intent"]["choice"] = "certified_yes"
    response = Mock(); response.json.return_value = body
    post = Mock(return_value=response)
    monkeypatch.setattr(rag_router.requests, "post", post)
    with pytest.raises(ValueError, match="Invalid closed"):
        rag_router.classify_sources("A2 ?", [], {})
    assert post.call_args.args[0] == rag_router.legacy.URL
    assert post.call_args.kwargs["json"]["model"] == rag_router.legacy.MODEL
    assert not list(tmp_path.glob("*.json"))


def test_unrecognized_edition_does_not_become_the_base_model(connected, local_rag):
    result = rag_router.route_question(object(), "Honda Example édition imaginaire 2025 pour A2")
    assert result["route"] == "clarification" and not result["evidence"]["retrieval_executed"]
    local_rag[0].assert_not_called()


@pytest.mark.parametrize("question", [
    "Honda Example 2025, édition imaginaire pour A2",
    "édition imaginaire : Honda Example 2025 pour A2",
])
def test_edition_outside_model_year_is_not_substituted(connected, local_rag, question):
    result = rag_router.route_question(object(), question)
    assert result["route"] == "clarification" and not result["evidence"]["retrieval_executed"]
    local_rag[0].assert_not_called()


def test_excluded_variant_is_not_an_additional_requested_edition(connected):
    result = rag_router.route_question(object(), "Honda Example 2025 pour A2 ; pas la version sans ABS")
    assert result["evidence"]["sources"][0]["model"] == "Example"


def test_low_jev_identity_score_cannot_override_exact_sql_source(connected, monkeypatch):
    raw = jev_choices(); raw["answers"]["identity_binding"]["confidence"] = .32
    monkeypatch.setattr(rag_router, "classify_sources", lambda *args: (raw, 1))
    result = rag_router.route_question(object(), "Honda Example 2025 : A2 et puissance ?")
    assert result["evidence"]["sources"][0]["object_id"] == "exact"
    assert result["evidence"]["identity_interpretation"]["confidence"] == .32
    assert result["evidence"]["legal_certification"] is False


@pytest.mark.parametrize("metric", ["puissance", "chevaux", "bourrins", "ch", "cv"])
def test_jev_cannot_drop_an_explicit_source_column(connected, monkeypatch, metric):
    monkeypatch.setattr(rag_router, "classify_sources", lambda *args: (jev_choices(["license"]), 1))
    result = rag_router.route_question(object(), f"Honda Example 2025 : A2 et {metric} ?")
    assert "power_ch" in result["plan"]["fields"] and "73 ch à 8 500" in result["answer"]


@pytest.mark.parametrize("item", ["poignées chauffantes", "ABS", "shifter", "TPMS", "équipements"])
def test_jev_cannot_drop_requested_equipment(connected, monkeypatch, item):
    monkeypatch.setattr(rag_router, "classify_sources", lambda *args: (jev_choices(["license"]), 1))
    monkeypatch.setattr(rag_router, "check_source_coverage", lambda q, fields, row, docs:
                        {"fields": {f: "missing" if f == "equipment" else "complete" for f in fields}, "jev_calls": 0})
    result = rag_router.route_question(object(), f"Honda Example 2025 pour A2 : {item} de série ?")
    assert "equipment" in result["plan"]["fields"]
    assert any(m.get("field") == "equipment" for m in result["evidence"]["missing"])


def test_two_aliases_on_same_mention_require_variant_clarification(connected, monkeypatch, local_rag):
    monkeypatch.setattr(rag_router.legacy, "entities", lambda *args:
                        ([{"brand": "Honda", "model": "Example"}, {"brand": "Honda", "model": "Example Special"}], []))
    result = rag_router.route_question(object(), "Honda Example 2025 pour A2")
    assert result["route"] == "clarification" and not result["evidence"]["retrieval_executed"]
    local_rag[0].assert_not_called()


def test_unrelated_equipment_does_not_cover_a_requested_missing_item(local_rag):
    check = lambda *args: {"fields": {"equipment": "missing"}, "jev_calls": 1}
    result = rag.answer_from_sources(object(), "A2 : poignées chauffantes de série ?", plan(["equipment"]), check)
    assert "Non documenté" in result["answer"] and "ABS en option" not in result["answer"]
    assert any(m.get("field") == "equipment" for m in result["evidence"]["missing"])
    assert not result["evidence"]["sources"][0]["coverage"]["equipment"]["covered"]


def test_partial_subfact_keeps_available_source_and_marks_gap(local_rag):
    check = lambda *args: {"fields": {"equipment": "partial"}, "jev_calls": 1}
    result = rag.answer_from_sources(object(), "ABS et poignées chauffantes pour A2 ?", plan(["equipment"]), check)
    assert "ABS en option" in result["answer"] and "Un détail demandé reste non documenté" in result["answer"]


def test_comparison_followup_keeps_existing_exact_year_pairs():
    models = [{"brand": "Honda", "model": "Example", "year": 2024}, {"brand": "Honda", "model": "Example", "year": 2025}]
    bound, problem = rag_router.bind_years("Et leurs mentions A2 ?", models, {"models": models})
    assert bound == models and problem is None

"""The local writer can only publish claims bound to retrieved evidence."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from bikefinder_rag.agent import rag_synthesis as synthesis


@pytest.fixture
def retrieved():
    return {"answer": "Les données originales : puissance 47,5 ch. Source.",
            "route": "rag_partial", "plan": {"a2_context": True},
            "evidence": {"retrieval_executed": True, "legal_certification": False,
                "sources": [{"object_id": "exact", "brand": "Honda", "model": "Example", "year": 2025,
                    "source_url": "https://source.test/exact", "source_sha256": "hash",
                    "coverage": {"power_ch": {"requested_facts_status": "complete"}},
                    "passages": [{"id": "exact:section:1", "original_text": "Puissance : 47,5 ch. ABS en option.", "section": "Moteur"}]}],
                "missing": [{"kind": "field", "object_id": "exact", "field": "a2_mention", "message": "Mention A2 non retrouvée"}]}}


@pytest.fixture
def writer(monkeypatch):
    monkeypatch.setenv("BIKEFINDER_RAG_SYNTHESIS", "1")
    generate = Mock(return_value=({"claims": [{"text": "La fiche indique une puissance de 47,5 ch.", "sources": ["P1"]}]},
                                  {"model": "mistral-small3.2:latest", "eval_count": 35}))
    check = Mock(return_value={"accepted": True, "jev_calls": 1})
    monkeypatch.setattr(synthesis, "generate", generate)
    monkeypatch.setattr(synthesis, "check_claims", check)
    return generate, check


def test_writer_consumes_only_retrieved_passages_and_keeps_gaps(writer, retrieved):
    result = synthesis.compose("Explique la puissance pour A2", retrieved)
    assert "La fiche indique une puissance" in result["answer"]
    assert "https://source.test/exact" in result["answer"]
    assert "Mention A2 non retrouvée" in result["answer"]
    assert "pas des documents officiels" in result["answer"]
    assert result["route"] == "rag_mistral_partial"
    assert result["generation"]["published"] is True
    assert result["generation"]["eval_count"] == 35
    payload = writer[0].call_args.args[1]
    assert payload[0]["passage_id"] == "exact:section:1"
    assert payload[0]["text"] == retrieved["evidence"]["sources"][0]["passages"][0]["original_text"]
    assert result["evidence"] is retrieved["evidence"]


@pytest.mark.parametrize("claims", [
    [{"text": "Elle développe 150 ch.", "sources": ["P1"]}],
    [{"text": "Elle développe 47,5 kW.", "sources": ["P1"]}],
    [{"text": "ABS de série.", "sources": ["P1"]}],
    [{"text": "Elle développe 47,5 ch.", "sources": ["Invented"]}],
    [{"text": "Elle développe 47,5 ch.", "sources": []}],
    [{"text": "Source : https://invented.test", "sources": ["P1"]}],
    [{"text": "Source [ici](javascript:alert(1))", "sources": ["P1"]}],
    [{"text": "", "sources": ["P1"]}],
    [],
])
def test_invalid_claims_are_never_published(writer, retrieved, claims):
    writer[0].return_value = ({"claims": claims}, {"model": "mistral"})
    result = synthesis.compose("Explique", retrieved)
    assert result["route"] == "rag_mistral_fallback"
    assert retrieved["answer"] in result["answer"]
    assert not result["generation"]["published"]
    writer[1].assert_not_called()


def test_numbers_are_bound_to_cited_fiche_not_other_model(writer, retrieved):
    other = deepcopy(retrieved["evidence"]["sources"][0])
    other["object_id"] = "other"
    other["passages"][0]["original_text"] = "Puissance : 150 ch."
    retrieved["evidence"]["sources"].append(other)
    writer[0].return_value = ({"claims": [{"text": "Puissance de 150 ch.", "sources": ["P1"]}]}, {})
    assert not synthesis.compose("Compare", retrieved)["generation"]["published"]


@pytest.mark.parametrize("verdict", [{"accepted": False, "jev_calls": 1}, {"accepted": False, "jev_calls": 0}])
def test_failed_semantic_gate_keeps_literal_answer(writer, retrieved, verdict):
    writer[1].return_value = verdict
    result = synthesis.compose("ABS de série ?", retrieved)
    assert not result["generation"]["published"]
    assert retrieved["answer"] in result["answer"]
    assert result["jev_calls"] == verdict["jev_calls"]


def test_partial_publication_keeps_verified_prose_and_removes_bad_claim(writer, retrieved):
    writer[0].return_value = ({"claims": [
        {"text": "La fiche indique une puissance de 47,5 ch.", "sources": ["P1"]},
        {"text": "Le dispositif améliore le confort.", "sources": ["P1"]}]}, {})
    writer[1].return_value = {"accepted": False, "verified_claim_indices": [0], "coverage_verified": False, "jev_calls": 1}
    result = synthesis.compose("Puissance et confort ?", retrieved)
    assert result["generation"]["mode"] == "mixed"
    assert result["generation"]["removed_claims"] == 1
    assert "améliore le confort" not in result["answer"]
    assert "La fiche indique une puissance" in result["answer"]
    assert retrieved["answer"] in result["answer"]
    assert "Rédaction partielle" in result["answer"]


def test_timeouts_have_explicit_source_fallback(writer, retrieved):
    writer[0].side_effect = TimeoutError("local timeout")
    result = synthesis.compose("Explique", retrieved)
    assert not result["generation"]["published"]
    assert result["generation"]["error"] == "TimeoutError"
    assert "n’a pas abouti" in result["answer"]
    assert retrieved["answer"] in result["answer"]


def test_no_generation_without_identity_and_passages(writer, retrieved):
    retrieved["evidence"]["retrieval_executed"] = False
    assert synthesis.compose("Example 2024 ?", retrieved) is retrieved
    writer[0].assert_not_called()


def test_source_only_switch_keeps_old_path(writer, retrieved, monkeypatch):
    monkeypatch.setenv("BIKEFINDER_RAG_SYNTHESIS", "0")
    assert synthesis.compose("Explique", retrieved) is retrieved
    writer[0].assert_not_called()


def test_busy_writer_returns_sources_immediately(writer, retrieved):
    assert synthesis.SLOT.acquire(blocking=False)
    try:
        result = synthesis.compose("Explique", retrieved)
    finally:
        synthesis.SLOT.release()
    assert not result["generation"]["published"]
    assert result["generation"]["error"] == "busy"
    writer[0].assert_not_called()


@pytest.mark.parametrize("host", ["https://remote.test", "http://localhost.remote.test:11434", "http://user:pw@localhost:11434", "http://127.0.0.1:11434/redirect", "ftp://localhost"])
def test_ollama_remote_configuration_is_rejected(host):
    with pytest.raises(ValueError):
        synthesis.local_url(host)


def test_langchain_uses_local_mistral_no_tracing_and_non_streaming_timeout(monkeypatch):
    import langchain_ollama
    fake = Mock()
    fake.invoke.return_value.content = '{"claims":[{"text":"Puissance : 47,5 ch.","sources":["P1"]}]}'
    fake.invoke.return_value.response_metadata = {"model": "mistral-small3.2", "eval_count": 20, "done_reason": "stop"}
    constructor = Mock(return_value=fake)
    monkeypatch.setattr(langchain_ollama, "ChatOllama", constructor)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral-small3.2")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    payload, metadata = synthesis.generate("Nouvelle question", [{"id": "P1", "text": "Puissance : 47,5 ch."}], {})
    assert payload["claims"] and metadata["eval_count"] == 20
    assert constructor.call_args.kwargs["base_url"] == "http://127.0.0.1:11434"
    assert constructor.call_args.kwargs["client_kwargs"]["trust_env"] is False
    assert constructor.call_args.kwargs["client_kwargs"]["follow_redirects"] is False
    assert constructor.call_args.kwargs["num_predict"] == 700
    assert fake.invoke.call_args.kwargs["stream"] is False
    assert fake.invoke.call_args.kwargs["config"]["callbacks"] == []


def test_real_langchain_invoke_does_not_enable_langsmith_from_environment(monkeypatch):
    import ollama
    from langchain_core.tracers.langchain import LangChainTracer
    tracer = Mock(side_effect=AssertionError("External tracing must remain disabled"))
    monkeypatch.setattr(LangChainTracer, "__init__", tracer)
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral-small3.2")
    monkeypatch.setattr(ollama.Client, "chat", Mock(return_value={
        "model": "mistral-small3.2", "done": True, "done_reason": "stop", "eval_count": 25,
        "message": {"role": "assistant", "content": '{"claims":[{"text":"47,5 ch","sources":["P1"]}]}'}}))
    payload, metadata = synthesis.generate("Puissance ?", [{"id": "P1", "text": "47,5 ch"}], {})
    assert payload["claims"] and metadata["eval_count"] == 25
    tracer.assert_not_called()


def test_claim_gate_uses_only_closed_jev_choices(monkeypatch):
    from bikefinder_rag.agent import rag_router
    decisions = Mock(return_value=({"answers": {k: {"choice": "supported", "confidence": .98}
                                  for k in ["claim_0", "answer_coverage"]}}, 1))
    monkeypatch.setattr(rag_router, "closed_decisions", decisions)
    result = synthesis.check_claims("Question", [{"text": "ABS de série", "sources": ["P1"]}],
                                    [{"id": "P1", "text": "ABS en option"}])
    assert result["accepted"]
    questions = decisions.call_args.args[1]
    assert set(questions["claim_0"]["criteria"]) == {"supported", "unsupported"}
    assert "option" in questions["claim_0"]["instructions"]


def test_numbers_handle_decimal_format_year_pairs_and_license_tokens():
    assert synthesis.numbers("Ninja 500 2025, 4,30 mkg, 6 000 tr/min, A2") == synthesis.numbers("Ninja 500 (2025), 4.3 mkg, 6000 tr/min")


def test_passage_identifier_is_not_numeric_evidence(writer, retrieved):
    retrieved["evidence"]["sources"][0]["passages"][0]["id"] = "exact:section:150"
    writer[0].return_value = ({"claims": [{"text": "Puissance : 150 ch.", "sources": ["P1"]}]}, {})
    assert not synthesis.compose("Puissance ?", retrieved)["generation"]["published"]


def test_unattributed_a2_verdict_is_rejected_before_jev(writer, retrieved):
    writer[0].return_value = ({"claims": [{"text": "Cette moto est compatible A2.", "sources": ["P1"]}]}, {})
    assert not synthesis.compose("A2 ?", retrieved)["generation"]["published"]
    writer[1].assert_not_called()


def test_omitted_requested_fact_fails_semantic_gate(monkeypatch):
    from bikefinder_rag.agent import rag_router
    monkeypatch.setattr(rag_router, "closed_decisions", lambda *args: ({"answers": {
        "claim_0": {"choice": "supported", "confidence": .98},
        "answer_coverage": {"choice": "unsupported", "confidence": .98}}}, 1))
    assert not synthesis.check_claims("ABS et puissance ?", [{"text": "47,5 ch", "sources": ["P1"]}],
                                     [{"id": "P1", "text": "47,5 ch. ABS en option."}])["accepted"]


def test_uncertain_completeness_is_visible_without_hiding_verified_claims(writer, retrieved):
    writer[1].return_value = {"accepted": True, "coverage_verified": False, "jev_calls": 1}
    result = synthesis.compose("Explique", retrieved)
    assert result["generation"]["published"]
    assert "Couverture non vérifiée" in result["answer"]
    assert result["route"] == "rag_mistral_partial"


def test_quantities_preserve_original_units_and_equivalent_decimal_format():
    assert synthesis.quantities("4,30 mkg ; 14 litres ; 47.5ch") == synthesis.quantities("4.3 mkg ; 14 l ; 47,5 ch")
    assert synthesis.quantities("47,5 kW") != synthesis.quantities("47,5 ch")
    assert synthesis.quantities("80 x 62.1 mm") == synthesis.quantities("80 mm et 62,1 mm")


def test_semantic_gate_must_reject_a_status_attached_to_the_wrong_fact(writer, retrieved):
    source = retrieved["evidence"]["sources"][0]
    source["passages"] = [
        {"id": "transmission", "section": "Transmission", "original_text": "Boîte à 6 rapports, manuelle"},
        {"id": "equipment", "section": "Équipement de série", "original_text": "ABS"}]
    writer[0].return_value = ({"claims": [{"text": "Boîte à 6 rapports de série.", "sources": ["P1", "P2"]}]}, {})
    writer[1].return_value = {"accepted": False, "jev_calls": 1}
    assert not synthesis.compose("Boîte de série ?", retrieved)["generation"]["published"]
    writer[1].assert_called_once()


def test_jev_failure_fails_closed(monkeypatch):
    from bikefinder_rag.agent import rag_router
    monkeypatch.setattr(rag_router, "closed_decisions", Mock(side_effect=RuntimeError("unavailable")))
    assert not synthesis.check_claims("Question", [{"text": "ABS", "sources": ["P1"]}], [{"id": "P1", "text": "ABS"}])["accepted"]

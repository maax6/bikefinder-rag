from copy import deepcopy
from unittest.mock import Mock

import pytest

from bikefinder_rag.agent import catalog_research
from bikefinder_rag.agent import jev_router
from bikefinder_rag.catalog import research
from bikefinder_rag.embeddings import embedder


QUESTION = "Sur les goldwing honda et sur les RT BMW c'est à partir de quelle année les boites automatiques ?"


def test_local_planner_discovers_year_and_keeps_both_families(monkeypatch):
    calls = []
    class Catalog:
        def execute(self, name, arguments):
            calls.append((name, arguments))
            if name == "lookup_models":
                return {"scope_id": "S" + str(len(calls)), "brand": arguments["brand"],
                        "model_query": arguments["model_query"], "fiches": 2, "variants": []}
            return {"scope_id": arguments["scope_id"], "passages": [], "searched_fiches": 2}

        def result(self, question):
            return {"answer": "Sources du catalogue", "route": "catalog_research_sources",
                    "plan": {"operation": "research"},
                    "evidence": {"retrieval_executed": True, "sources": [], "missing": []}}

        def incomplete(self):
            return ["Passages non recherchés"] if len(calls) < 4 else []

    plans = iter([
        {"calls": [
            {"tool": "lookup_models", "arguments": {"brand": "Honda", "model_query": "goldwing"}},
            {"tool": "lookup_models", "arguments": {"brand": "BMW", "model_query": "RT"}}], "ready_to_answer": False},
        {"calls": [
            {"tool": "search_passages", "arguments": {"scope_id": "S1", "query": "boîte automatique DCT", "mode": "earliest_mention", "terms": ["DCT"]}},
            {"tool": "search_passages", "arguments": {"scope_id": "S2", "query": "boîte automatique", "mode": "semantic"}}], "ready_to_answer": True},
    ])
    observed_results = []
    def planner(question, history, results):
        observed_results.append(deepcopy(results))
        return next(plans), {"model": "mistral-small3.2:latest"}
    def writer(question, result):
        return {**result, "answer": "Réponse locale sourcée", "generation": {"published": True}}
    result = catalog_research.answer_question(None, QUESTION, [], catalog=Catalog(), planner=planner, writer=writer)
    assert result["answer"] == "Réponse locale sourcée"
    assert [a["brand"] for name, a in calls if name == "lookup_models"] == ["Honda", "BMW"]
    assert all("year" not in a for name, a in calls if name == "lookup_models")
    assert len([r for r in observed_results[1] if "tool" in r]) == 2
    assert result["research"]["local_planner_calls"] == 2
    assert result["research"]["tool_calls"] == 4


@pytest.fixture
def tools(monkeypatch, tmp_path):
    def fiche(id, brand, model, year, text):
        return {"id": id, "brand": brand, "model": model, "year": year,
                "source_url": "https://source.test/" + id, "source_sha256": id + "-hash",
                "record": {"technical_sections": [{"section": "Transmission", "text": text}]}}
    rows = [fiche("manual", "Honda", "GL 1800 GOLDWING", 2016, "Boîte manuelle à 6 rapports"),
            fiche("first", "Honda", "GL 1800 GOLDWING Tour DCT", 2018, "Boîte robotisée DCT à 7 rapports"),
            fiche("later", "Honda", "GL 1800 GOLDWING DCT", 2020, "Boîte robotisée DCT à 7 rapports"),
            fiche("bmw", "BMW", "R 1300 RT", 2025, "Boîte manuelle à 6 rapports ; shifter en option")]
    sql_calls = []
    def database(conn, sql, params):
        sql_calls.append((sql, params))
        if sql.startswith("SELECT DISTINCT brand"):
            return [{"brand": "Honda"}, {"brand": "BMW"}]
        return deepcopy([r for r in rows if r["brand"].lower() == params[0]])
    monkeypatch.setattr(research, "_rows", database)
    monkeypatch.setattr(jev_router, "entities", lambda *args: ([], []))
    monkeypatch.setenv("BIKEFINDER_RESEARCH_INDEX", str(tmp_path / "missing"))
    monkeypatch.setenv("BIKEFINDER_RAG_CACHE", str(tmp_path))
    monkeypatch.setattr(embedder, "embed_texts", Mock(side_effect=lambda texts: [[1.] + [0.] * 1023 for _ in texts]))
    monkeypatch.setattr(embedder, "embed_text", Mock(return_value=[1.] + [0.] * 1023))
    return research.CatalogResearch(object(), QUESTION), sql_calls


def test_earliest_search_scans_all_years_and_returns_exact_source(tools):
    catalog, sql_calls = tools
    scope = catalog.execute("lookup_models", {"brand": "Honda", "model_query": "Gold Wing"})
    result = catalog.execute("search_passages", {"scope_id": scope["scope_id"], "query": "boîte automatique",
                                                "section": "Transmission", "mode": "earliest_mention", "terms": ["DCT"]})
    assert result["searched_fiches"] == 3
    assert result["earliest_matching_mention_year"] == 2018
    assert any(p["object_id"] == "first" and p["original_text"] == "Boîte robotisée DCT à 7 rapports" for p in result["passages"])
    evidence = catalog.result(QUESTION)["evidence"]
    first = next(s for s in evidence["sources"] if s["object_id"] == "first")
    assert first["source_url"] == "https://source.test/first"
    assert first["year"] == 2018
    assert any("BMW" in gap["message"] for gap in evidence["missing"])
    assert "year >=" not in sql_calls[-1][0] and "year <=" not in sql_calls[-1][0]


def test_generic_field_terms_do_not_hide_the_discriminating_property(tools):
    catalog, _ = tools
    scope = catalog.execute("lookup_models", {"brand": "Honda", "model_query": "Gold Wing"})
    result = catalog.execute("search_passages", {"scope_id": scope["scope_id"], "query": "boîte automatique",
        "section": "Transmission", "mode": "earliest_mention", "terms": ["transmission", "boîte", "automatique", "DCT"]})
    assert result["earliest_matching_mention_year"] == 2018
    assert any(p["object_id"] == "first" for p in result["passages"])


def test_missing_automation_is_unknown_and_manual_sources_remain_citable(tools):
    catalog, sql_calls = tools
    scope = catalog.execute("lookup_models", {"brand": "BMW", "model_query": "RT"})
    assert r"\mrt\M" in sql_calls[-1][1]  # short tokens must not match 'Sport'
    result = catalog.execute("search_passages", {"scope_id": scope["scope_id"], "query": "boîte automatique",
                                                "mode": "earliest_mention", "terms": ["ASA", "robotisée"]})
    assert result["earliest_matching_mention_year"] is None
    assert "ne prouve pas l'absence" in result["missing"][0]
    assert "manuelle" in result["passages"][0]["original_text"]
    assert catalog.result(QUESTION)["evidence"]["legal_certification"] is False


@pytest.mark.parametrize("arguments", [
    {"brand": "Honda", "model_query": "Goldwing", "min_year": 2018},
    {"brand": "Honda", "model_query": "Africa Twin"},
    {"brand": "Yamaha", "model_query": "Goldwing"},
    {"brand": "Honda", "model_query": "Goldwing", "sql": "DROP TABLE technical_fiches"},
])
def test_planner_cannot_invent_years_identities_or_sql(tools, arguments):
    catalog, sql_calls = tools
    before = len(sql_calls)
    with pytest.raises(ValueError):
        catalog.execute("lookup_models", arguments)
    assert len(sql_calls) == before


def test_unknown_tool_scope_does_not_substitute_another_scope(tools):
    catalog, _ = tools
    with pytest.raises(ValueError):
        catalog.execute("search_passages", {"scope_id": "Invented", "query": "boîte"})


def test_explicit_edition_cannot_be_erased(monkeypatch):
    monkeypatch.setattr(research, "_rows", lambda *args: [])
    monkeypatch.setattr(jev_router, "entities", lambda *args: ([], []))
    catalog = research.CatalogResearch(object(), "Honda Gold Wing édition Galaxie : transmission ?")
    with pytest.raises(ValueError, match="edition/variant"):
        catalog.execute("lookup_models", {"brand": "Honda", "model_query": "Gold Wing"})


def test_agent_entrypoint_reaches_research_before_year_clarification(monkeypatch):
    from bikefinder_rag.agent import loop, rag_router
    monkeypatch.setenv("BIKEFINDER_JEV_ROUTER", "1")
    monkeypatch.setenv("BIKEFINDER_JEV_RAG", "1")
    monkeypatch.setenv("BIKEFINDER_CATALOG_RESEARCH", "1")
    monkeypatch.setattr(rag_router.legacy, "entities", lambda *args: ([], ["Honda", "BMW"]))
    observed = Mock(return_value={"answer": "2018, avec source ; BMW reste non établi", "route": "research",
                                 "research": {"tool_calls": 4}, "evidence": {"retrieval_executed": True}})
    monkeypatch.setattr(catalog_research, "answer_question", observed)
    answer, history = loop.run_agent(object(), None, QUESTION, [], provider="ollama")
    assert "2018" in answer and "Quel millésime" not in answer
    assert history[-1]["_catalog_research"]["tool_calls"] == 4
    assert observed.call_args.args[1] == QUESTION


def test_one_honda_family_cannot_silently_cover_another_honda_family(tools):
    catalog, _ = tools
    catalog.expected_models = [{"brand": "Honda", "model": "GL 1800 GOLDWING"},
                               {"brand": "Honda", "model": "CRF 1100 L AFRICA TWIN"}]
    scope = catalog.execute("lookup_models", {"brand": "Honda", "model_query": "Gold Wing"})
    catalog.execute("search_passages", {"scope_id": scope["scope_id"], "query": "boîte"})
    assert any("AFRICA TWIN" in missing for missing in catalog.incomplete())


def test_expired_research_budget_never_starts_a_writer(monkeypatch):
    now = [0.]
    monkeypatch.setenv("CATALOG_RESEARCH_TIMEOUT_SECONDS", "10")
    monkeypatch.setattr(catalog_research.time, "perf_counter", lambda: now[0])
    class Catalog:
        def result(self, question):
            return {"answer": "Sources récupérées", "evidence": {"sources": [], "missing": []}}
    def planner(*args):
        now[0] = 11.
        return {"calls": [], "ready_to_answer": True}, {}
    writer = Mock()
    result = catalog_research.answer_question(None, QUESTION, catalog=Catalog(), planner=planner, writer=writer)
    writer.assert_not_called()
    assert result["generation"]["error"] == "research_budget_exhausted"
    assert "Budget de recherche épuisé" in result["answer"]


def test_short_family_name_cannot_be_taken_from_inside_an_unrelated_word(tools):
    catalog, calls = tools
    catalog.input_text = "Sur les BMW, à partir de quelle année les boîtes automatiques ?"
    before = len(calls)
    with pytest.raises(ValueError):
        catalog.execute("lookup_models", {"brand": "BMW", "model_query": "RT"})
    assert len(calls) == before


def test_equipment_property_is_not_removed_as_a_generic_field_name(tools):
    catalog, _ = tools
    scope = catalog.execute("lookup_models", {"brand": "Honda", "model_query": "Gold Wing"})
    result = catalog.execute("search_passages", {"scope_id": scope["scope_id"], "query": "ABS", "mode": "earliest_mention", "terms": ["ABS"]})
    assert result["effective_terms"] == ["ABS"]


def test_edition_in_one_family_does_not_block_the_other_family(tools):
    catalog, _ = tools
    catalog.question = catalog.input_text = "Honda Gold Wing édition Tour et BMW RT : quelles transmissions ?"
    result = catalog.execute("lookup_models", {"brand": "BMW", "model_query": "RT"})
    assert result["fiches"] == 1

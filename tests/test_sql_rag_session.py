import json
from copy import deepcopy

import pytest

from test_sql_rag_service import service
from bikefinder_rag.agent.sql_rag_adapters import Completion, ToolCall
from bikefinder_rag.agent.sql_rag_session import CatalogSession, bounded_result, parse_final
from bikefinder_rag.agent.sql_rag_context import compact_result, evidence_ids
from bikefinder_rag.catalog.sql_rag_service import canonical


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.histories = []

    def complete(self, messages, timeout):
        self.histories.append(deepcopy(messages))
        return next(self.replies)

    def metadata(self):
        return {"provider": "scripted_test", "model": "fixture", "settings": {}}


def call(name, args, cid="call1"):
    return Completion("", [ToolCall(cid, name, args)], {"role": "assistant", "content": "", "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": canonical(args)}}]},
        {"input_tokens": 2, "output_tokens": 1, "cost_usd": None}, "fixture")


def answer(evidence="a:row:0"):
    return Completion(json.dumps({"answer": "La selle est à 785 mm.", "claims": [{"text": "La selle est à 785 mm.", "evidence_ids": [evidence]}], "missing": [], "needs_clarification": False}),
                      [], {"role": "assistant", "content": "final"}, {"input_tokens": 4, "output_tokens": 3, "cost_usd": None}, "fixture")


def test_full_tool_loop_delivers_real_evidence_and_preserves_history(service):
    model = ScriptedModel([call("get_fiches", {"object_ids": ["a"], "fields": ["seat_height_mm"], "sections": [], "equipment_names": []}), answer(), answer()])
    session = CatalogSession(service, model, "System")
    result = session.ask("Quelle hauteur ?")
    assert result["status"] == "completed"
    assert result["calls"][0]["result"]["payload"]["fiches"][0]["measures"]["seat_height_mm"]["value"] == 785
    assert result["judgments"]["citations_valid"] is True
    assert result["judgments"]["claims_supported"] is None
    assert result["usage"]["input_tokens"] == 6
    assert result["timing"]["ttft_seconds"] is None
    follow = session.ask("Et rappelle celle-ci.")
    assert follow["status"] == "completed"
    assert len([m for m in model.histories[-1] if m["role"] == "user"]) == 2


def test_invented_reference_is_rejected_even_if_prose_looks_correct(service):
    model = ScriptedModel([call("get_fiches", {"object_ids": ["a"], "fields": ["seat_height_mm"], "sections": [], "equipment_names": []}), answer("invented")])
    result = CatalogSession(service, model, "System").ask("Question")
    assert result["status"] == "error"
    assert result["answer"] == ""
    assert "not delivered" in result["error"]
    assert result["format_repairs"] == []
    assert len(model.histories) == 2


def test_round_budget_does_not_run_an_unbounded_model_loop(service):
    model = ScriptedModel([call("describe_catalog", {})] * 10)
    result = CatalogSession(service, model, "System", rounds=2).ask("Question")
    assert result["status"] == "error"
    assert len(model.histories) == 2
    assert len(result["calls"]) == 1


def test_context_reduction_is_disclosed_and_cannot_leak_removed_evidence(service):
    source = service.execute("get_fiches", {"object_ids": ["a", "b", "c"]})
    reduced = bounded_result(source, 1000)
    assert reduced["status"] == "partial"
    assert reduced["coverage"]["truncation_reason"] == "context_budget"
    assert len(json.dumps(reduced, ensure_ascii=False, separators=(",", ":"))) <= 1000
    assert source["status"] == "ok"  # original receipt remains intact


def test_invalid_tool_arguments_are_returned_to_model_and_can_be_corrected(service):
    model = ScriptedModel([call("query_catalog", {"mode": "count", "sql": "DROP TABLE fiches"}),
                           call("get_fiches", {"object_ids": ["a"], "fields": ["seat_height_mm"], "sections": [], "equipment_names": []}, "call2"), answer()])
    result = CatalogSession(service, model, "System").ask("Question")
    assert result["status"] == "completed"
    assert result["calls"][0]["result"]["status"] == "invalid_arguments"
    assert service.execute("describe_catalog", {})["payload"]["fiche_count"] == 3


def test_exact_json_fence_is_accepted_but_prose_is_not_repaired():
    assert parse_final("```json\n" + answer().text + "\n```")["answer"] == "La selle est à 785 mm."
    with pytest.raises(ValueError):
        parse_final("Une réponse de mémoire : " + answer().text)


def test_terminal_answer_closes_native_tool_exchange_for_next_user_turn(service):
    terminal = call("submit_answer", json.loads(answer().text), "terminal1")
    model = ScriptedModel([call("get_fiches", {"object_ids": ["a"], "fields": ["seat_height_mm"], "sections": [], "equipment_names": []}), terminal, answer()])
    session = CatalogSession(service, model, "System")
    assert session.ask("Hauteur ?")["status"] == "completed"
    assert session.messages[-1]["name"] == "submit_answer"
    assert session.ask("Rappelle la hauteur.")["status"] == "completed"


def equipment_list_result():
    rows, proofs = [], []
    aggregate = {"evidence_id": "aggregate:8", "kind": "aggregate", "count": 8,
                 "criteria": {"scope": {"brand": "Fixture", "min_year": 2020, "max_year": 2020},
                              "equipment_filters": [{"name": "ABS", "status": "standard"},
                                                    {"name": "shifter", "status": "standard"}]},
                 "contributing_ids": [f"m{i}" for i in range(8)]}
    proofs.append(aggregate)
    for i in range(8):
        oid, url = f"m{i}", f"https://example.com/m{i}"
        equipment = []
        for name, text, section in [("ABS", "Assistance au freinage : ABS", "Équipement de série"),
                                    ("shifter", "boîte à 6 rapports, manuelle - shifter de série", "Transmission")]:
            eid = f"{oid}:equipment:{name}"
            entry = {"name": name, "status": "standard", "evidence_ids": [eid],
                     "decision": {"case_id": oid + name, "object_id": oid, "equipment": name,
                                  "status": "standard", "stage": "code_literal_evidence", "market": None,
                                  "source_url": url, "input_hash": "h" * 64,
                                  "reasons": ["explicit_source_fact; model uncertainty does not remove the original fact"],
                                  "passages": [{"id": f"{oid}:source:{name}", "section": section, "text": text}]}}
            equipment.append(entry)
            proofs.append({"evidence_id": eid, "kind": "source_row", "object_id": oid,
                           "source_url": url, "source_sha256": "h" * 64, "equipment": deepcopy(entry)})
        rows.append({"identity": {"id": oid, "brand": "Fixture", "model": "Bike " + str(i), "year": 2020,
                                  "source_url": url, "source_sha256": "h" * 64},
                     "measures": {}, "equipment": equipment, "passages": []})
    return {"status": "ok", "snapshot_id": "fixture", "payload": {"rows": rows, "total_matches": 8,
            "aggregate_evidence_id": "aggregate:8", "unknown_exclusions": []}, "evidence": proofs, "missing": [],
            "coverage": {"requested_scope": aggregate["criteria"]["scope"], "searched_fiches": 8,
                         "searched_passages": None, "exhaustive": True, "truncation_reason": None},
            "pagination": {"returned": 8, "total": 8, "next_cursor": None}, "timing_ms": 1}


def structured_answer(text, refs):
    value = {"answer": text, "claims": [{"text": text, "evidence_ids": refs}],
             "missing": [], "needs_clarification": False}
    return Completion(canonical(value), [], {"role": "assistant", "content": canonical(value)},
                      {"input_tokens": 2, "output_tokens": 2, "cost_usd": None}, "fixture")


def test_lossless_compaction_keeps_all_eight_equipped_models_and_original_source_qualifications():
    raw = equipment_list_result()
    saved = deepcopy(raw)
    view = bounded_result(raw, 24000)
    assert raw == saved
    assert view["status"] == "ok"
    assert not view["view"]["content_omitted"]
    assert len(view["payload"]["rows"]) == 8
    assert view["evidence"][0]["count"] == 8
    assert view["evidence"][0]["contributing_ids"] == [f"m{i}" for i in range(8)]
    assert len(canonical(view)) < len(canonical(raw))
    assert len(canonical(view)) <= 24000
    assert len(view["classification_policies"]) == 1
    for row in view["payload"]["rows"]:
        oid = row["identity"]["id"]
        assert view["sources"][oid] == {"brand": "Fixture", "model": "Bike " + oid[1:], "year": 2020,
                                       "source_url": "https://example.com/" + oid}
        assert all(e["status"] == "standard" for e in row["equipment"])
    indexed = {p["evidence_id"]: p for p in view["evidence"]}
    for proof in [p for p in view["evidence"] if "equipment" in p]:
        decision = proof["equipment"]["decision"]
        original = next(p for p in saved["evidence"] if p["evidence_id"] == proof["evidence_id"])
        source_passages = [{"id": indexed[p["evidence_id"]]["evidence_id"],
                            "section": indexed[p["evidence_id"]]["section"],
                            "text": indexed[p["evidence_id"]]["text"]} for p in decision["passages"]]
        assert source_passages == original["equipment"]["decision"]["passages"]
        policy = view["classification_policies"][decision["policy_id"]]
        assert policy["stage"] == "code_literal_evidence"
        assert policy["market"] is None


def test_partial_pages_keep_global_count_and_never_leave_dangling_source_references():
    # Full page membership and newly citable original proofs are essential
    # metadata. Give them room while forcing a reduction of the detailed rows.
    budget = len(canonical(compact_result(equipment_list_result()))) * 2 // 3
    result = bounded_result(equipment_list_result(), budget, protected_evidence={"m0:equipment:ABS"})
    assert len(canonical(result)) <= budget
    assert result["status"] == "partial"
    assert result["payload"]["total_matches"] == 8
    assert result["pagination"]["total"] == 8
    assert result["pagination"]["returned"] == len(result["payload"]["rows"])
    assert len(result["payload"]["rows"]) < 8
    delivered = {p["evidence_id"] for p in result["evidence"]}
    assert evidence_ids(result["payload"]) <= delivered
    assert "m0:equipment:ABS" in delivered
    assert "m0" in {r["identity"]["id"] for r in result["payload"]["rows"]}
    for row in result["payload"]["rows"]:
        assert row["identity"]["id"] in result["sources"]


def test_multi_turn_eight_row_equipment_list_and_filtered_count_fit_the_same_context_cap():
    class ListAndCountService:
        def __init__(self):
            self.args = []

        def execute(self, name, args):
            self.args.append(deepcopy(args))
            if args["mode"] == "list":
                return equipment_list_result()
            assert args["scope"]["object_ids"] == [f"m{i}" for i in range(8)]
            result = equipment_list_result()
            result["payload"].update(rows=[], total_matches=3, aggregate_evidence_id="aggregate:3")
            result["evidence"] = [{"evidence_id": "aggregate:3", "kind": "aggregate", "count": 3,
                                   "criteria": deepcopy(args), "contributing_ids": ["m0", "m1", "m2"]}]
            result["pagination"].update(returned=0, total=3)
            return result

    svc = ListAndCountService()
    list_refs = [p["evidence_id"] for p in equipment_list_result()["evidence"]]
    model = ScriptedModel([call("query_catalog", {"mode": "list"}, "list-8"),
                           structured_answer("Les huit modèles disposent de ces deux équipements de série.", list_refs),
                           call("query_catalog", {"mode": "count", "scope": {"object_ids": [f"m{i}" for i in range(8)]},
                                                  "numeric_filters": [{"field": "seat_height_mm", "op": "<", "value": 850}]}, "count-3"),
                           structured_answer("Trois modèles de la sélection ont une selle sous le seuil.", ["aggregate:3"])])
    session = CatalogSession(svc, model, "System")
    first = session.ask("Liste ces modèles avec leurs équipements sourcés.")
    second = session.ask("Combien parmi cette sélection ont une selle sous le seuil ?")
    assert first["status"] == second["status"] == "completed"
    assert first["calls"][0]["result"]["payload"]["total_matches"] == 8
    assert second["calls"][0]["result"]["payload"]["total_matches"] == 3
    assert first["context"]["retained_characters"] <= 32000
    assert second["context"]["retained_characters"] <= 32000
    retained_list = json.loads(next(m["content"] for m in model.histories[-1]
                                   if m["role"] == "tool" and m["call_id"] == "list-8"))
    assert len(retained_list["payload"]["rows"]) == 8
    new_refs = {f"m{i}:identity" for i in range(8)} | {f"m{i}:source:{name}" for i in range(8) for name in ("ABS", "shifter")}
    assert {p["evidence_id"] for p in retained_list["evidence"]} == set(list_refs) | new_refs
    assert [m["call_id"] for m in model.histories[-1] if m["role"] == "tool"] == ["list-8", "count-3"]


def test_history_reduction_preserves_call_ids_accepted_citations_and_discloses_omissions():
    class StaticService:
        def execute(self, name, args):
            return equipment_list_result()

    model = ScriptedModel([call("query_catalog", {"mode": "list"}, "first-page"),
                           structured_answer("Le premier modèle a l'ABS de série.", ["m0:equipment:ABS"]),
                           structured_answer("Le premier modèle a toujours l'ABS de série.", ["m0:equipment:ABS"])])
    session = CatalogSession(StaticService(), model, "System", context_characters=16000)
    assert session.ask("Le premier modèle a-t-il l'ABS ?")["status"] == "completed"
    receipt = session.ask("Rappelle la source du premier modèle.")
    assert receipt["status"] == "completed"
    events = receipt["context"]["compression_events"]
    assert any(e["kind"] == "history_page_reduction" and e["call_id"] == "first-page" for e in events)
    history_page = next(m for m in model.histories[-1] if m["role"] == "tool")
    assert history_page["call_id"] == "first-page"
    reduced = json.loads(history_page["content"])
    assert reduced["coverage"]["truncation_reason"] == "context_budget"
    assert "m0:equipment:ABS" in {p["evidence_id"] for p in reduced["evidence"]}
    assert reduced["sources"]["m0"]["source_url"] == "https://example.com/m0"


def test_one_schema_repair_is_bounded_and_records_every_paid_model_response(service):
    bad = Completion("La selle mesure 785 mm.", [], {"role": "assistant", "content": "La selle mesure 785 mm."},
                     {"input_tokens": 3, "output_tokens": 2, "cost_usd": None}, "fixture")
    model = ScriptedModel([call("get_fiches", {"object_ids": ["a"], "fields": ["seat_height_mm"], "sections": []}),
                           bad, answer()])
    receipt = CatalogSession(service, model, "System").ask("Hauteur ?")
    assert receipt["status"] == "completed"
    assert len(receipt["format_repairs"]) == 1
    assert len(receipt["model_responses"]) == 3
    assert receipt["usage"]["input_tokens"] == 9
    feedback = json.loads(model.histories[-1][-1]["content"])
    assert feedback["status"] == "answer_format_rejected"
    assert "785" not in canonical(feedback)


def test_second_malformed_final_is_rejected_without_unbounded_format_retries(service):
    bad = Completion("Broken", [], {"role": "assistant", "content": "Broken"}, {}, "fixture")
    model = ScriptedModel([bad, bad, answer()])
    receipt = CatalogSession(service, model, "System").ask("Hauteur ?")
    assert receipt["status"] == "error"
    assert len(model.histories) == 2
    assert len(receipt["format_repairs"]) == 1


def test_malformed_native_terminal_does_not_poison_repair_history_or_orphan_a_tool_id(service):
    broken = '{"answer":"truncated'
    bad = Completion("", [ToolCall("bad-terminal", "submit_answer", broken)],
                     {"role": "assistant", "tool_calls": [{"id": "bad-terminal", "type": "function",
                       "function": {"name": "submit_answer", "arguments": broken}}]}, {}, "fixture", "length")
    model = ScriptedModel([call("get_fiches", {"object_ids": ["a"], "fields": ["seat_height_mm"], "sections": []}),
                           bad, answer()])
    receipt = CatalogSession(service, model, "System").ask("Hauteur ?")
    assert receipt["status"] == "completed"
    assert receipt["model_responses"][1]["native"] == bad.native
    assert receipt["format_repairs"][0]["invalid_native_terminal_removed_from_history"]
    assert not any(m.get("call_id") == "bad-terminal" for m in model.histories[-1])
    assert not any(m.get("native") == bad.native for m in model.histories[-1])


def test_three_large_tool_exchanges_fit_total_budget_and_preserve_native_pairing():
    raw = equipment_list_result()
    for proof in raw["evidence"][1:]:
        proof["equipment"]["decision"]["passages"][0]["text"] += " Original factual context." * 20

    class StaticService:
        def execute(self, name, args):
            return deepcopy(raw)

    references = [p["evidence_id"] for p in raw["evidence"]]
    model = ScriptedModel([call("query_catalog", {"mode": "list"}, "page-1"),
                           call("query_catalog", {"mode": "list"}, "page-2"),
                           call("query_catalog", {"mode": "list"}, "page-3"),
                           structured_answer("La dernière sélection comporte huit modèles équipés.", references)])
    receipt = CatalogSession(StaticService(), model, "System").ask("Vérifie cette sélection.")
    assert receipt["status"] == "completed"
    assert len(receipt["calls"]) == 3
    assert receipt["context"]["retained_characters"] <= 32000
    history = model.histories[-1]
    tool_ids = {m["call_id"] for m in history if m["role"] == "tool"}
    native_ids = {c["id"] for m in history if m.get("native") for c in m["native"].get("tool_calls", [])}
    assert tool_ids == native_ids == {"page-1", "page-2", "page-3"}
    last = json.loads(next(m["content"] for m in history if m.get("call_id") == "page-3"))
    assert len(last["payload"]["rows"]) == 8
    assert not last["view"]["content_omitted"]
    assert any(e["kind"] == "history_page_reduction" for e in receipt["context"]["compression_events"])


def test_format_repair_cannot_execute_further_catalogue_queries(service):
    bad = Completion("Broken", [], {"role": "assistant", "content": "Broken"}, {}, "fixture")
    model = ScriptedModel([bad, call("describe_catalog", {})])
    receipt = CatalogSession(service, model, "System").ask("Question")
    assert receipt["status"] == "error"
    assert receipt["calls"] == []
    assert "Formatting repair" in receipt["error"]


def test_compact_views_are_idempotent_and_keep_ranges_and_entire_passage_text(service):
    raw = service.execute("get_fiches", {"object_ids": ["c"], "fields": ["seat_height_mm"], "sections": ["Transmission"]})
    view = compact_result(raw)
    assert compact_result(view) == view
    fiche = view["payload"]["fiches"][0]
    assert fiche["measures"]["seat_height_mm"]["value"] is None
    assert fiche["original_rows"][0]["value"] == "réglable 790 à 810 mm"
    assert fiche["passages"] == [{"evidence_id": "c:section:0"}]
    proof = next(p for p in view["evidence"] if p["evidence_id"] == "c:section:0")
    assert proof["text"] == "manuelle à 5 rapports"
    assert view["sources"][proof["object_id"]]["model"] == "CB 1500 F"


def test_repeated_history_reductions_accumulate_omissions_and_keep_one_notice():
    first = bounded_result(equipment_list_result(), 7000)
    second = bounded_result(first, 4000)
    assert second["view"]["omissions"]["rows"] > first["view"]["omissions"]["rows"]
    assert len([m for m in second["missing"] if m.get("subject") == "tool_response" and m.get("field") == "context"]) == 1


def test_original_equipment_source_passage_is_citable_when_its_text_was_delivered():
    # Haiku Q24 cited a row present in equipment.decision.passages, which used
    # to be rejected merely because it was not duplicated at evidence[] root.
    class EquipmentSourceService:
        def execute(self, name, args):
            return equipment_list_result()

    model = ScriptedModel([
        call("query_catalog", {"mode": "list"}),
        structured_answer("Le premier modèle indique l'ABS de série.", ["m0:source:ABS"]),
    ])
    receipt = CatalogSession(EquipmentSourceService(), model, "System").ask("Quel équipement indique cette fiche ?")
    assert receipt["status"] == "completed", receipt["error"]
    delivered = receipt["calls"][0]["delivered_result"]
    proof = next(p for p in delivered["evidence"] if p["evidence_id"] == "m0:source:ABS")
    assert proof["object_id"] == "m0"
    assert proof["text"] == "Assistance au freinage : ABS"
    assert delivered["sources"]["m0"]["source_url"] == "https://example.com/m0"


def test_bare_known_object_id_gets_one_identifier_format_repair_without_auto_citation(service):
    wrong = json.loads(answer().text)
    wrong["claims"][0]["evidence_ids"] = ["a"]
    model = ScriptedModel([
        call("get_fiches", {"object_ids": ["a"], "fields": ["seat_height_mm"], "sections": []}),
        call("submit_answer", wrong, "bad-reference"),
        call("submit_answer", json.loads(answer().text), "good-reference"),
    ])
    receipt = CatalogSession(service, model, "System").ask("Quelle hauteur indique cette fiche ?")
    assert receipt["status"] == "completed", receipt["error"]
    assert len(receipt["calls"]) == 1
    assert len(receipt["format_repairs"]) == 1
    assert receipt["format_repairs"][0]["kind"] == "citation_identifier"
    assert receipt["final"]["claims"][0]["evidence_ids"] == ["a:row:0"]
    feedback = json.loads(model.histories[-1][-1]["content"])
    assert feedback["status"] == "answer_format_rejected"
    assert "785" not in canonical(feedback)
    assert len(canonical(feedback)) <= 1024
    assert model.histories[-1][-1]["call_id"] == "bad-reference"


def test_unknown_row_reference_is_not_treated_as_a_known_object_identifier(service):
    model = ScriptedModel([
        call("get_fiches", {"object_ids": ["a"], "fields": ["seat_height_mm"], "sections": []}),
        answer("a:row:999"), answer(),
    ])
    receipt = CatalogSession(service, model, "System").ask("Quelle hauteur indique cette fiche ?")
    assert receipt["status"] == "error"
    assert receipt["format_repairs"] == []
    assert len(model.histories) == 2


def test_identifier_repair_shares_the_single_repair_limit_and_cannot_query_again(service):
    wrong = structured_answer("La selle est documentée.", ["a"])
    model = ScriptedModel([
        call("get_fiches", {"object_ids": ["a"], "fields": ["seat_height_mm"], "sections": []}),
        wrong, wrong, answer(),
    ])
    receipt = CatalogSession(service, model, "System").ask("Quelle hauteur ?")
    assert receipt["status"] == "error"
    assert len(receipt["format_repairs"]) == 1
    assert len(model.histories) == 3

    querying = ScriptedModel([
        call("get_fiches", {"object_ids": ["a"], "fields": ["seat_height_mm"], "sections": []}),
        wrong, call("describe_catalog", {}),
    ])
    rejected = CatalogSession(service, querying, "System").ask("Quelle hauteur ?")
    assert rejected["status"] == "error"
    assert len(rejected["calls"]) == 1
    assert "Formatting repair" in rejected["error"]


def test_identifier_repair_cannot_exceed_the_model_round_budget(service):
    model = ScriptedModel([
        call("get_fiches", {"object_ids": ["a"], "fields": ["seat_height_mm"], "sections": []}),
        structured_answer("La selle est documentée.", ["a"]), answer(),
    ])
    receipt = CatalogSession(service, model, "System", rounds=2).ask("Quelle hauteur ?")
    assert receipt["status"] == "error"
    assert len(model.histories) == 2
    assert receipt["format_repairs"] == []


def test_followup_mistyped_selection_id_is_rejected_and_recoverable_from_original_history(service):
    selection = {"object_ids": ["a", "b", "c"]}
    numeric = [{"field": "seat_height_mm", "op": "<", "value": 850}]
    initial_args = {"mode": "list", "scope": selection}
    count_args = {"mode": "count", "scope": selection, "numeric_filters": numeric}
    list_args = {"mode": "list", "scope": selection, "numeric_filters": numeric, "fields": ["seat_height_mm"]}
    initial = service.execute("query_catalog", initial_args)
    counted = service.execute("query_catalog", count_args)
    malformed = deepcopy(list_args)
    malformed["scope"] = {"object_ids": ["a", "mistyped-b", "c"]}
    model = ScriptedModel([
        call("query_catalog", initial_args, "original-selection"),
        structured_answer("La sélection comporte trois fiches.", [initial["payload"]["aggregate_evidence_id"]]),
        call("query_catalog", count_args, "correct-count"),
        call("query_catalog", malformed, "mistyped-selection"),
        call("query_catalog", list_args, "recovered-selection"),
        structured_answer("Deux fiches de cette sélection sont sous 850 mm.", [counted["payload"]["aggregate_evidence_id"]]),
    ])
    session = CatalogSession(service, model, "System")
    assert session.ask("Liste ces fiches.")["status"] == "completed"
    follow = session.ask("Parmi celles-ci, combien sont sous 850 mm ?")
    assert follow["status"] == "completed", follow["error"]
    rejected = follow["calls"][1]["delivered_result"]
    assert rejected["status"] == "invalid_arguments"
    assert rejected["payload"]["unknown_object_ids"] == ["mistyped-b"]
    assert "total_matches" not in rejected["payload"]
    assert rejected["evidence"] == []
    assert follow["calls"][2]["result"]["payload"]["total_matches"] == 2
    assert follow["calls"][2]["result"]["payload"]["unknown_exclusions"][0]["unknown_in_requested_scope"] == 1
    retained = json.loads(next(m["content"] for m in model.histories[-1] if m.get("call_id") == "original-selection"))
    assert retained["payload"]["page_scope"]["object_ids"] == selection["object_ids"]
    assert follow["context"]["retained_characters"] <= 32000


def test_context_detail_reduction_preserves_the_numeric_sort_field():
    raw = equipment_list_result()
    for i, row in enumerate(raw["payload"]["rows"]):
        oid = row["identity"]["id"]
        for field, value, qualifier_length in [("seat_height_mm", 800 + i, 45), ("weight_wet_kg", 200 + i, 15)]:
            eid = f"{oid}:measure:{field}"
            row["measures"][field] = {"value": value, "evidence_ids": [eid]}
            raw["evidence"].append({"evidence_id": eid, "kind": "source_row", "object_id": oid,
                "row": {"section": "Châssis", "label": field, "value": str(value) + " qualification" * qualifier_length}})

    class BroadListService:
        def execute(self, name, args):
            return deepcopy(raw)

    budget = len(canonical(compact_result(raw))) - 1500
    model = ScriptedModel([
        call("query_catalog", {"mode": "list", "sort": [{"field": "seat_height_mm", "direction": "asc"}]}),
        structured_answer("Les huit fiches sont triées par hauteur de selle.", ["aggregate:8"]),
    ])
    receipt = CatalogSession(BroadListService(), model, "System", result_characters=budget).ask("Trie les fiches par hauteur de selle.")
    assert receipt["status"] == "completed", receipt["error"]
    view = receipt["calls"][0]["delivered_result"]
    assert len(view["payload"]["rows"]) == 8
    assert [r["measures"]["seat_height_mm"]["value"] for r in view["payload"]["rows"]] == list(range(800, 808))
    assert "weight_wet_kg" in view["view"]["fields_omitted"]
    assert view["view"]["omissions"]["measure_fields"] == len(view["view"]["fields_omitted"])
    assert view["view"]["protected_fields"] == ["seat_height_mm"]
    assert len(canonical(view)) <= budget

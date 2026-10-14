"""Model-facing context must keep identities and citation targets unambiguous."""
from copy import deepcopy
import json

import pytest

from bikefinder_rag.agent.sql_rag_context import bounded_result, compact_result


def result_fixture(count=2):
    objects = [(f"{index + 1:016x}", f"Roadster variant {index + 1}") for index in range(count)]
    rows, evidence = [], []
    for oid, model in objects:
        source = "https://example.test/" + oid
        equipment = {"name": "ABS", "status": "standard", "evidence_ids": [oid + ":equipment:ABS"],
                     "decision": {"stage": "literal_source", "reasons": ["Explicit source fact"], "market": None,
                                  "passages": [{"id": oid + ":row:3", "section": "Équipement de série", "text": "ABS de série"}]}}
        rows.append({"identity": {"id": oid, "brand": "Fixture", "model": model, "year": 2020,
                                  "source_url": source, "source_sha256": "h" * 64},
                     "measures": {}, "equipment": [deepcopy(equipment)], "passages": []})
        evidence.append({"evidence_id": oid + ":equipment:ABS", "kind": "source_row", "object_id": oid,
                         "source_url": source, "source_sha256": "h" * 64, "equipment": equipment})
    return {"status": "ok", "snapshot_id": "fixture", "payload": {"rows": rows, "total_matches": count},
            "evidence": evidence, "missing": [], "coverage": {"requested_scope": {}, "searched_fiches": count,
            "searched_passages": None, "exhaustive": True, "truncation_reason": None},
            "pagination": {"returned": count, "total": count, "next_cursor": None}, "timing_ms": 1}


def test_action_object_id_keeps_exact_model_and_year_in_the_same_identity():
    raw = result_fixture()
    view = compact_result(raw)
    for row, original in zip(view["payload"]["rows"], raw["payload"]["rows"]):
        identity = row["identity"]
        assert identity["model"] == original["identity"]["model"]
        assert identity["brand"] == original["identity"]["brand"]
        assert identity["year"] == original["identity"]["year"]
        assert identity["id"] == original["identity"]["id"]


def test_source_identity_is_explicitly_citable_but_not_a_numeric_or_equipment_proof():
    raw = result_fixture()
    view = compact_result(raw)
    proofs = {proof["evidence_id"]: proof for proof in view["evidence"]}
    for row in view["payload"]["rows"]:
        oid = row["identity"]["id"]
        assert row["identity"]["evidence_id"] == oid + ":identity"
        identity_proof = proofs[oid + ":identity"]
        assert identity_proof["claim_scope"] == "identity_only"
        assert identity_proof["object_id"] == oid
        assert "equipment" not in identity_proof and "row" not in identity_proof and "text" not in identity_proof


def test_equipment_source_passage_id_really_delivered_is_citable_without_losing_its_original_text():
    raw = result_fixture()
    view = compact_result(raw)
    proofs = {proof["evidence_id"]: proof for proof in view["evidence"]}
    for original in raw["evidence"]:
        source = original["equipment"]["decision"]["passages"][0]
        promoted = proofs[source["id"]]
        assert promoted["object_id"] == original["object_id"]
        assert promoted["text"] == source["text"]
        assert promoted["section"] == source["section"]
        assert promoted["origin_equipment_evidence_ids"] == [original["evidence_id"]]
        assert proofs[original["evidence_id"]]["equipment"]["decision"]["passages"] == [{"evidence_id": source["id"]}]


def test_citation_object_id_and_human_subject_are_colocated_without_joining_source_tables():
    raw = result_fixture()
    view = compact_result(raw)
    names = {row["identity"]["id"]: row["identity"] for row in raw["payload"]["rows"]}
    for proof in view["evidence"]:
        identity = names[proof["object_id"]]
        assert proof["subject"] == f"{identity['brand']} {identity['model']} ({identity['year']})"


def test_context_reduction_keeps_original_page_members_without_claiming_the_page_is_the_whole_catalogue():
    raw = result_fixture()
    raw["payload"]["total_matches"] = raw["pagination"]["total"] = 100
    raw["pagination"]["next_cursor"] = "next-page"
    view = compact_result(raw)
    page = view["payload"]["page_scope"]
    assert page["object_ids"] == [r["identity"]["id"] for r in raw["payload"]["rows"]]
    assert page["returned"] == 2 and page["total_matches"] == 100
    assert page["all_matches_in_page"] is False
    assert view["pagination"]["next_cursor"] == "next-page"


def test_original_complete_page_scope_remains_after_a_fiche_detail_is_removed():
    raw = result_fixture()
    raw["evidence"][0]["equipment"]["decision"]["passages"][0]["text"] += " Explicit source wording." * 180
    full = compact_result(raw)
    reduced = bounded_result(raw, len(json.dumps(full, ensure_ascii=False, separators=(",", ":"))) - 4000)
    assert len(reduced["payload"]["rows"]) < len(raw["payload"]["rows"])
    assert reduced["payload"]["page_scope"]["object_ids"] == [r["identity"]["id"] for r in raw["payload"]["rows"]]
    assert reduced["payload"]["page_scope"]["all_matches_in_page"] is True
    assert reduced["view"]["content_omitted"] and not reduced["coverage"]["exhaustive"]


def test_identity_id_collision_cannot_rebind_an_existing_proof_to_another_object():
    raw = result_fixture()
    first, second = [row["identity"]["id"] for row in raw["payload"]["rows"]]
    raw["evidence"].append({"evidence_id": first + ":identity", "kind": "source_row", "object_id": second})
    with pytest.raises(ValueError, match="Identity citation collides"):
        compact_result(raw)


def test_equipment_source_promotion_rejects_cross_object_ids_and_arbitrary_nested_ids():
    raw = result_fixture()
    first, second = [row["identity"]["id"] for row in raw["payload"]["rows"]]
    decision = raw["evidence"][0]["equipment"]["decision"]
    decision["passages"][0]["id"] = second + ":unreceived-source"
    decision["model_metadata"] = {"id": first + ":arbitrary-note", "section": "Moteur", "text": "unrelated note"}
    view = compact_result(raw)
    known = {p["evidence_id"] for p in view["evidence"]}
    assert second + ":unreceived-source" not in known
    assert first + ":arbitrary-note" not in known
    assert view["evidence"][0]["equipment"]["decision"]["passages"][0]["text"] == "ABS de série"


def test_conflicting_source_text_for_same_nested_id_stays_unpromoted_and_explicit():
    raw = result_fixture()
    parent = raw["evidence"][0]
    conflict = deepcopy(parent)
    conflict["evidence_id"] = parent["object_id"] + ":equipment:other"
    conflict["equipment"]["decision"]["passages"][0]["text"] = "ABS optionnel"
    raw["evidence"].append(conflict)
    view = compact_result(raw)
    nested = parent["equipment"]["decision"]["passages"][0]["id"]
    assert nested not in {p["evidence_id"] for p in view["evidence"]}
    assert nested in view["view"]["non_promoted_equipment_source_ids"]
    decisions = [p["equipment"]["decision"] for p in view["evidence"]
                 if "equipment" in p and p["object_id"] == parent["object_id"]]
    assert {d["passages"][0]["text"] for d in decisions} >= {"ABS de série", "ABS optionnel"}


def test_existing_original_row_proof_is_reused_only_if_same_object_section_and_exact_text():
    raw = result_fixture()
    parent = raw["evidence"][0]
    nested = parent["equipment"]["decision"]["passages"][0]
    raw["evidence"].append({"evidence_id": nested["id"], "kind": "source_row", "object_id": parent["object_id"],
                            "row": {"label": "", "section": nested["section"], "value": nested["text"]}})
    view = compact_result(raw)
    proof = next(p for p in view["evidence"] if p["evidence_id"] == nested["id"])
    assert proof["kind"] == "source_row" and proof["row"]["value"] == "ABS de série"
    assert len([p for p in view["evidence"] if p["evidence_id"] == nested["id"]]) == 1


def test_parent_source_reference_closure_is_retained_when_other_fiche_details_are_pruned():
    raw = result_fixture()
    parent = raw["evidence"][0]
    nested = parent["equipment"]["decision"]["passages"][0]
    raw["evidence"][1]["equipment"]["decision"]["passages"][0]["text"] += " Source words." * 500
    reduced = bounded_result(raw, 6000, protected_evidence={nested["id"]})
    proofs = {p["evidence_id"]: p for p in reduced["evidence"]}
    assert proofs[nested["id"]]["text"] == nested["text"]
    assert parent["evidence_id"] in proofs
    assert reduced["sources"][parent["object_id"]]["source_url"] == parent["source_url"]
    for proof in proofs.values():
        decision = proof.get("equipment", {}).get("decision")
        if decision:
            assert all(p["evidence_id"] in proofs for p in decision["passages"] if "evidence_id" in p)


def test_original_rows_are_deduplicated_only_against_proofs_of_the_same_fiche():
    raw = result_fixture()
    row = {"label": "Hauteur de selle", "section": "Châssis", "value": "réglable 790 à 810 mm"}
    raw["payload"]["rows"][0]["original_rows"] = [deepcopy(row)]
    oid = raw["payload"]["rows"][1]["identity"]["id"]
    raw["evidence"].append({"evidence_id": oid + ":row:10", "kind": "source_row", "object_id": oid, "row": row})
    view = compact_result(raw)
    assert view["payload"]["rows"][0]["original_rows"] == [row]


def test_older_interned_views_cannot_be_silently_reinterpreted_as_complete_raw_tool_results():
    raw = result_fixture()
    raw["view"] = {"format": "catalogue-compact-v1"}
    with pytest.raises(ValueError, match="requires the original tool receipt"):
        compact_result(raw)


def test_duplicate_existing_citation_ids_with_conflicting_facts_are_rejected():
    raw = result_fixture()
    duplicate = deepcopy(raw["evidence"][0])
    duplicate["equipment"]["status"] = "optional"
    raw["evidence"].append(duplicate)
    with pytest.raises(ValueError, match="Conflicting source proofs"):
        compact_result(raw)


def test_complete_page_scope_is_irreducible_rather_than_silently_dropping_members():
    raw = result_fixture()
    with pytest.raises(ValueError, match="remaining context budget"):
        bounded_result(raw, 500)


def wide_result_fixture():
    raw = result_fixture(8)
    fields = {"seat_height_mm": "mm", "displacement_ccm": "cc", "power_ch": "ch", "torque_nm": "Nm",
              "weight_dry_kg": "kg", "weight_wet_kg": "kg", "autonomy_km": "km", "catalog_price_eur": "EUR"}
    for index, row in enumerate(raw["payload"]["rows"]):
        oid = row["identity"]["id"]
        for field, unit in fields.items():
            eid, number = oid + ":measure:" + field, 800 + index
            row["measures"][field] = {"value": number, "unit": unit, "evidence_ids": [eid],
                                      "qualification": "dated_catalogue_price" if field == "catalog_price_eur" else None}
            raw["evidence"].append({"evidence_id": eid, "kind": "source_row", "object_id": oid,
                                    "row": {"label": field, "section": "Specifications", "value": f"{number} {unit}"}})
    raw["evidence"].insert(0, {"evidence_id": "aggregate:page", "kind": "aggregate", "count": 8,
                               "criteria": {"equipment_filters": [{"name": "ABS", "status": "standard"}]}})
    raw["payload"]["aggregate_evidence_id"] = "aggregate:page"
    return raw


def test_wide_equipment_list_omits_uniform_secondary_numeric_columns_before_whole_models():
    raw = wide_result_fixture()
    reduced = bounded_result(raw, 24000)
    assert len(reduced["payload"]["rows"]) == 8
    assert reduced["view"]["content_omitted"]
    assert reduced["view"]["fields_omitted"]
    column_sets = [set(row["measures"]) for row in reduced["payload"]["rows"]]
    assert all(columns == column_sets[0] for columns in column_sets)
    for row in reduced["payload"]["rows"]:
        assert row["equipment"][0]["status"] == "standard"
    proofs = {p["evidence_id"]: p for p in reduced["evidence"]}
    for original in raw["evidence"]:
        if "equipment" in original:
            assert original["evidence_id"] in proofs
            assert original["equipment"]["decision"]["passages"][0]["id"] in proofs
    assert len(json.dumps(reduced, ensure_ascii=False, separators=(",", ":"))) <= 24000


def test_numeric_filter_and_missing_criteria_fields_cannot_be_removed_to_save_context():
    raw = wide_result_fixture()
    raw["evidence"][0]["criteria"].update(numeric_filters=[{"field": "seat_height_mm", "op": "<", "value": 850}],
                                          missing_fields=["weight_dry_kg"])
    reduced = bounded_result(raw, 20000)
    for row in reduced["payload"]["rows"]:
        assert row["measures"]["seat_height_mm"]["value"] >= 800
        assert "weight_dry_kg" in row["measures"]
    assert {"seat_height_mm", "weight_dry_kg"} <= set(reduced["view"]["protected_fields"])


def test_cited_measure_and_explicit_sort_field_stay_protected_across_repeated_reductions():
    raw = wide_result_fixture()
    protected_id = raw["payload"]["rows"][0]["measures"]["power_ch"]["evidence_ids"][0]
    first = bounded_result(raw, 24000, protected_fields=["torque_nm"], protected_evidence={protected_id})
    second = bounded_result(first, 18000, protected_evidence={protected_id})
    assert {"power_ch", "torque_nm"} <= set(second["view"]["protected_fields"])
    assert "power_ch" not in second["view"]["fields_omitted"]
    assert "torque_nm" not in second["view"]["fields_omitted"]
    assert any(p["evidence_id"] == protected_id for p in second["evidence"])
    for row in second["payload"]["rows"]:
        assert "power_ch" in row["measures"] and "torque_nm" in row["measures"]


def test_sort_field_protection_is_recorded_even_when_the_initial_result_fits():
    raw = wide_result_fixture()
    first = bounded_result(raw, 100000, protected_fields=["torque_nm"])
    assert not first["view"]["content_omitted"]
    assert first["view"]["protected_fields"] == ["torque_nm"]
    second = bounded_result(first, 20000)
    assert "torque_nm" not in second["view"]["fields_omitted"]
    assert all("torque_nm" in row["measures"] for row in second["payload"]["rows"])
    assert second["view"]["omissions"]["measure_fields"] == len(second["view"]["fields_omitted"])

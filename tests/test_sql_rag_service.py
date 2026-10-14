import json
import sqlite3

import pytest

from bikefinder_rag.catalog.sql_rag_service import CatalogService, identity_match, prepare_catalog, standard_identity_match


@pytest.fixture
def service(tmp_path):
    source = tmp_path / "source.sqlite3"
    c = sqlite3.connect(source)
    c.execute("CREATE TABLE objects(id TEXT,url TEXT,brand TEXT,model TEXT,year INTEGER,source_sha256 TEXT,record TEXT)")
    c.execute("CREATE TABLE equipment(object_id TEXT,equipment TEXT,status TEXT,decision TEXT)")
    specs = [
        ("a", "CB 500 F", 2020, "785 mm", "471 cc", "DCT à 7 rapports"),
        ("b", "CB 500 F Sport", 2020, "800 mm", "500 cc", "manuelle à 6 rapports"),
        ("c", "CB 1500 F", 2018, "réglable 790 à 810 mm", "1500 cc", "manuelle à 5 rapports"),
    ]
    for oid, model, year, seat, displacement, text in specs:
        record = {"spec_rows": [{"section": "Châssis", "label": "Hauteur de selle", "value": seat},
                               {"section": "Moteur", "label": "", "value": displacement}],
                  "technical_sections": [{"section": "Transmission", "text": text}]}
        c.execute("INSERT INTO objects VALUES(?,?,?,?,?,?,?)", [oid, "https://example.com/" + oid, "Honda", model, year, oid * 64, json.dumps(record)])
    c.executemany("INSERT INTO equipment VALUES(?,?,?,?)", [("a", "ABS", "standard", "{}"), ("b", "ABS", "optional", "{}"), ("c", "ABS", "unknown", "{}"), ("a", "shifter", "standard", "{}")])
    c.commit()
    c.close()
    prepared = tmp_path / "projection.sqlite3"
    prepare_catalog(source, prepared)
    svc = CatalogService(source, prepared)
    yield svc
    svc.close()


def test_exact_count_and_unknown_are_not_absence(service):
    result = service.execute("query_catalog", {"mode": "count", "equipment_filters": [{"name": "shifter", "status": "unknown"}]})
    assert result["payload"]["total_matches"] == 2  # no row for b/c is unknown
    absent = service.execute("query_catalog", {"mode": "count", "equipment_filters": [{"name": "shifter", "status": "explicitly_absent"}]})
    assert absent["payload"]["total_matches"] == 0
    numeric = service.execute("query_catalog", {"mode": "count", "numeric_filters": [{"field": "seat_height_mm", "op": "<", "value": 800}]})
    assert numeric["payload"]["total_matches"] == 1
    assert numeric["payload"]["unknown_exclusions"][0]["unknown_in_requested_scope"] == 1


@pytest.mark.parametrize("mode", ["count", "list"])
def test_mistyped_scope_id_cannot_silently_reduce_a_verified_count(service, mode):
    # Reproduce the count -> list handoff from Luna Q37 with one altered ID.
    criteria = {"scope": {"object_ids": ["a", "b"]},
                "numeric_filters": [{"field": "seat_height_mm", "op": "<", "value": 801}]}
    verified = service.execute("query_catalog", {**criteria, "mode": "count"})
    assert verified["payload"]["total_matches"] == 2
    wrong_scope = {**criteria, "scope": {"object_ids": ["a", "bx"]}, "mode": mode}
    result = service.execute("query_catalog", wrong_scope)
    assert result["status"] == "invalid_arguments"
    assert result["payload"]["unknown_object_ids"] == ["bx"]
    assert "total_matches" not in result["payload"]
    assert result["evidence"] == []
    assert result["coverage"]["exhaustive"] is False


@pytest.mark.parametrize("tool,arguments", [
    ("query_catalog", {"mode": "count"}),
    ("resolve_models", {"query": "Honda"}),
    ("search_passages", {"mode": "literal", "query": "DCT", "literal_terms": ["DCT"]}),
    ("search_passages", {"mode": "hybrid", "query": "DCT"}),
])
def test_missing_scoped_ids_are_reported_before_count_resolution_or_retrieval(service, tool, arguments):
    result = service.execute(tool, {**arguments, "scope": {"object_ids": ["not-a-catalogue-id"]}})
    assert result["status"] == "invalid_arguments"
    assert result["payload"]["unknown_object_ids"] == ["not-a-catalogue-id"]
    assert result["payload"]["argument"] == "arguments.scope.object_ids"
    assert "next_action" in result["payload"]
    assert result["evidence"] == []
    assert result["coverage"]["searched_fiches"] == 0


def test_valid_scope_with_unknown_numeric_value_preserves_unknown_exclusion(service):
    result = service.execute("query_catalog", {"mode": "count", "scope": {"object_ids": ["c"]},
                                               "numeric_filters": [{"field": "seat_height_mm", "op": "<", "value": 801}]})
    assert result["status"] == "ok"
    assert result["payload"]["total_matches"] == 0
    assert result["payload"]["unknown_exclusions"][0]["unknown_in_requested_scope"] == 1
    assert result["coverage"]["searched_fiches"] == 1


def test_pagination_bound_to_criteria_and_full_count(service):
    args = {"mode": "list", "page_size": 1, "sort": [{"field": "model", "direction": "asc"}]}
    first = service.execute("query_catalog", args)
    assert first["payload"]["total_matches"] == 3
    cursor = first["pagination"]["next_cursor"]
    second = service.execute("query_catalog", {"mode": "list", "cursor": cursor})
    assert second["status"] == "ok"
    assert first["payload"]["rows"][0]["identity"]["id"] != second["payload"]["rows"][0]["identity"]["id"]
    altered = service.execute("query_catalog", {"mode": "list", "cursor": cursor, "scope": {"min_year": 2020}})
    assert altered["status"] == "invalid_arguments"
    count = service.execute("query_catalog", {"mode": "count", "page_size": 1})
    assert count["payload"]["total_matches"] == 3


def test_registered_selectors_normalize_without_changing_proof_or_mutating_arguments(service):
    args = {"mode": "count", "equipment_filters": [{"name": "Quick Shifter", "status": "standard"}]}
    result = service.execute("query_catalog", args)
    exact = service.execute("query_catalog", {"mode": "count", "equipment_filters": [{"name": "shifter", "status": "standard"}]})
    assert args["equipment_filters"][0]["name"] == "Quick Shifter"
    assert result["payload"]["total_matches"] == 1
    assert result["payload"]["aggregate_evidence_id"] == exact["payload"]["aggregate_evidence_id"]
    fiche = service.execute("get_fiches", {"object_ids": ["a"], "sections": [" transmission "], "equipment_names": ["abs"]})
    assert fiche["status"] == "ok"
    assert [p["section"] for p in fiche["payload"]["fiches"][0]["passages"]] == ["Transmission"]
    assert fiche["payload"]["fiches"][0]["equipment"][0]["name"] == "ABS"
    service.section_names.append("Équipement de série")
    normalized = service._normalize_selectors({"sections": ["EQUIPEMENT   DE SERIE"]})
    assert normalized["sections"] == ["Équipement de série"]


def test_equivalent_selector_spelling_is_accepted_with_original_cursor(service):
    # Use a scope matching more than one record, so the continuation is real.
    first = service.execute("query_catalog", {"mode": "list", "page_size": 1, "equipment_filters": [{"name": "Quickshifter", "status": "unknown"}]})
    cursor = first["pagination"]["next_cursor"]
    assert cursor
    following = service.execute("query_catalog", {"mode": "list", "cursor": cursor, "equipment_filters": [{"name": "quick-shifter", "status": "unknown"}]})
    assert following["status"] == "ok"
    assert following["payload"]["total_matches"] == 2
    assert following["payload"]["rows"][0]["identity"]["id"] != first["payload"]["rows"][0]["identity"]["id"]
    changed = service.execute("query_catalog", {"mode": "list", "cursor": cursor, "equipment_filters": [{"name": "ABS", "status": "unknown"}]})
    assert changed["status"] == "invalid_arguments"


def test_unknown_and_ambiguous_selectors_return_actionable_unsearched_error(service):
    result = service.execute("get_fiches", {"object_ids": ["a"], "sections": ["gearbox"], "equipment_names": ["autopilot"]})
    assert result["status"] == "invalid_arguments"
    assert result["coverage"]["exhaustive"] is False
    assert result["coverage"]["searched_fiches"] == 0
    assert result["payload"]["allowed_values"]["sections"] == ["Transmission"]
    assert result["payload"]["invalid_values"][0]["suggested_values"] == []
    # Two registered names collapsing to one spelling must never be selected arbitrarily.
    service.equipment_names.extend(["TCS", "tcs"])
    exact = service.execute("get_fiches", {"object_ids": ["a"], "equipment_names": ["TCS"]})
    assert exact["status"] == "ok"
    ambiguous = service.execute("get_fiches", {"object_ids": ["a"], "equipment_names": ["TcS"]})
    assert ambiguous["status"] == "invalid_arguments"
    assert ambiguous["payload"]["invalid_values"][0]["suggested_values"] == ["TCS", "tcs"]
    duplicate = service.execute("get_fiches", {"object_ids": ["a"], "equipment_names": ["ABS", "abs"]})
    assert duplicate["status"] == "invalid_arguments"


def test_resolution_preserves_numeric_identity_and_short_variants(service):
    assert identity_match("Z 650", "Kawasaki Z 650 2020")
    assert not identity_match("RT", "BMW R 1250 R Sport 2020")
    assert identity_match("RT", "BMW R1250RT 2020")
    assert identity_match("CB500F", "Honda CB 500 F Sport 2020")
    assert not identity_match("CB500F", "Honda CB 500 FOUR 1975")
    assert not identity_match("500", "Honda CB 1 500 2000")
    result = service.execute("resolve_models", {"query": "Honda CB500F 2020"})
    assert {r["id"] for r in result["payload"]["candidates"]} == {"a", "b"}
    fictional = service.execute("resolve_models", {"query": "Honda CB 500 F ZXQ-999 2020"})
    assert fictional["status"] == "not_found"
    exact = service.execute("resolve_models", {"query": "CB-1500 F"})
    assert [r["id"] for r in exact["payload"]["candidates"]] == ["c"]


@pytest.mark.parametrize("query,target,expected", [
    ("Gold Wing", "Honda GL 1800 GOLDWING Tour DCT/Airbag", True),
    ("Goldwing", "Honda GL 1800 Gold Wing Tour DCT/Airbag", True),
    ("Gold-Wing", "Honda GL 1800 Gold Wing Tour", True),
    ("Gold Wing", "Triumph 900 Street Twin Gold Line", False),
    ("Wing", "Triumph 900 Street Twin Gold Line", False),
    ("Goldwing", "Honda Gold 1800 Wing", False),
    ("RoadKing", "Harley-Davidson ROAD KING", True),
    ("CB500F", "Honda CB 500 F Sport 2020", True),
    ("CB500F", "Honda CB 500 FOUR 1975", False),
    ("RT", "BMW R 1250 R Sport 2020", False),
    ("RT", "BMW R1250RT 2020", True),
])
def test_natural_compounds_and_model_codes_keep_original_word_boundaries(query, target, expected):
    assert identity_match(query, target) is expected


def test_family_name_matching_never_creates_words_across_unrelated_boundaries(tmp_path):
    source = tmp_path / "families.sqlite3"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE objects(id TEXT,url TEXT,brand TEXT,model TEXT,year INTEGER,source_sha256 TEXT,record TEXT)")
    conn.execute("CREATE TABLE equipment(object_id TEXT,equipment TEXT,status TEXT,decision TEXT)")
    record = json.dumps({"spec_rows": [], "technical_sections": [{"section": "Transmission", "text": "manuelle"}]})
    for oid, brand, model, year in [("gold-old", "Honda", "GL 1800 GOLDWING", 2017),
                                   ("gold-dct", "Honda", "GL 1800 GOLDWING Tour DCT/Airbag", 2018),
                                   ("street", "Triumph", "900 Street Twin Gold Line", 2021)]:
        conn.execute("INSERT INTO objects VALUES(?,?,?,?,?,?,?)", [oid, f"https://example.com/{oid}", brand,
                                                                  model, year, oid * 10, record])
    conn.commit()
    conn.close()
    projection = tmp_path / "family-projection.sqlite3"
    prepare_catalog(source, projection)
    svc = CatalogService(source, projection)
    try:
        # Exact replay of the unbranded family resolution and split-token scope.
        result = svc.execute("resolve_models", {"query": "Gold Wing"})
        assert result["payload"]["total_candidates"] == 2
        assert {row["brand"] for row in result["payload"]["candidates"]} == {"Honda"}
        scoped = svc.execute("query_catalog", {"mode": "count", "scope": {"model_tokens": ["gold", "wing"]}})
        assert scoped["payload"]["total_matches"] == 2
    finally:
        svc.close()


def test_standard_resolution_requires_full_designation_and_never_replaces_unknown_variant(service):
    result = service.execute("resolve_models", {"query": "Honda CB500F standard 2020"})
    assert result["status"] == "ok"
    assert [candidate["id"] for candidate in result["payload"]["candidates"]] == ["a"]
    assert result["payload"]["resolution"]["normalization"] == "standard_to_exact_base_designation"
    for query in ["Honda CB standard 2020", "Honda CB500F standard ZXQ-FICTIVE-999 2020", "Honda CB500FOUR standard 2020"]:
        missing = service.execute("resolve_models", {"query": query})
        assert missing["status"] == "not_found"
        assert missing["payload"]["candidates"] == []
        assert "changes the requested identity" in missing["payload"]["next_action"]
    assert standard_identity_match("BMW R1250RT standard 2020", "BMW", "R 1250 RT", 2020)
    assert not standard_identity_match("BMW RT standard 2020", "BMW", "R 1250 R Sport", 2020)
    assert not standard_identity_match("Honda CB500F standard 2020", "Honda", "CB 500 FOUR", 2020)
    wrong_scope = service.execute("resolve_models", {"query": "Honda CB500F standard", "scope": {"min_year": 2018, "max_year": 2018}})
    assert wrong_scope["status"] == "not_found"


def test_compare_has_sourced_calculation_and_unknown_ranges(service):
    result = service.execute("compare_fiches", {"object_ids": ["a", "b", "c"], "fields": ["seat_height_mm"]})
    assert result["payload"]["deltas"][0]["second_minus_first"] == 15
    assert result["payload"]["deltas"][1]["second_minus_first"] is None
    assert "réglable" in result["payload"]["matrix"][2]["original_rows"][0]["value"]
    assert result["payload"]["deltas"][0]["evidence_ids"] == ["a:row:0", "b:row:0"]


def test_narrow_field_request_preserves_range_and_omits_unrelated_sections(service):
    result = service.execute("get_fiches", {"object_ids": ["c"], "fields": ["seat_height_mm"]})
    fiche = result["payload"]["fiches"][0]
    assert fiche["measures"]["seat_height_mm"]["value"] is None
    assert fiche["original_rows"][0]["value"] == "réglable 790 à 810 mm"
    assert fiche["passages"] == []
    assert fiche["equipment"] == []
    assert len(fiche["original_rows"]) == 1


def test_literal_search_is_exhaustive_scoped_and_preserves_source(service):
    result = service.execute("search_passages", {"query": "DCT", "mode": "literal", "literal_terms": ["DCT"], "order": "year_asc"})
    assert result["payload"]["retrieval"]["total_literal_matches"] == 1
    assert result["payload"]["passages"][0]["text"] == "DCT à 7 rapports"
    assert result["coverage"]["searched_passages"] == 3
    no_result = service.execute("search_passages", {"query": "DCT", "mode": "literal", "literal_terms": ["DCT"], "scope": {"object_ids": ["b"]}})
    assert no_result["status"] == "not_found"
    assert no_result["coverage"]["searched_fiches"] == 1


def test_missing_literal_terms_and_wrong_enum_give_specific_repair_guidance(service):
    missing = service.execute("search_passages", {"query": "DCT", "mode": "literal"})
    assert missing["status"] == "invalid_arguments"
    assert missing["payload"]["argument"] == "arguments.literal_terms"
    assert "Supply literal_terms" in missing["payload"]["next_action"]
    assert missing["evidence"] == []
    invalid = service.execute("query_catalog", {"mode": "count", "equipment_filters": [{"name": "ABS", "status": "yes"}]})
    assert invalid["status"] == "invalid_arguments"
    assert invalid["payload"]["allowed_values"] == ["standard", "optional", "explicitly_absent", "unknown"]


@pytest.mark.parametrize("tool,args", [
    ("drop_table", {}), ("query_catalog", {"mode": "count", "sql": "DELETE FROM fiches"}),
    ("query_catalog", {"mode": "count", "numeric_filters": [{"field": "seat_height_mm", "op": "<", "value": float('nan')}]}),
    ("query_catalog", {"mode": "count", "page_size": True}),
    ("query_catalog", {"mode": "count", "scope": {"min_year": 2025, "max_year": 2010}}),
    ("query_catalog", {"mode": "count", "equipment_filters": [{"name": "invented", "status": "standard"}]}),
    ("search_passages", {"mode": "literal", "query": "a"}),
    ("search_passages", {"mode": "hybrid", "query": "a", "literal_terms": ["a"]}),
    ("get_fiches", {"object_ids": ["a", "a"]}),
])
def test_invalid_requests_cannot_bypass_tool_contract(service, tool, args):
    assert service.execute(tool, args)["status"] == "invalid_arguments"
    assert service.execute("describe_catalog", {})["payload"]["fiche_count"] == 3


def test_source_and_projection_remain_read_only(service):
    with pytest.raises(sqlite3.OperationalError):
        service.conn.execute("DELETE FROM fiches")
    missing = service.execute("get_fiches", {"object_ids": ["a", "unknown"]})
    assert missing["status"] == "partial"
    assert [f["identity"]["id"] for f in missing["payload"]["fiches"]] == ["a"]
    with pytest.raises(FileExistsError):
        prepare_catalog(service.snapshot, service.projection)

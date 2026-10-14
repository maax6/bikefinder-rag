#!/usr/bin/env python3
"""Verify the common tools on the real frozen corpus, without a model judge."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from check_sql_rag_comparison import check
from prepare_sql_rag_comparison import DEFAULT_OUT, DEFAULT_SNAPSHOT
from bikefinder_rag.catalog.sql_rag_service import CatalogService, digest, prepare_catalog

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECTION = ROOT / "data/technical/sql-rag-service-v2/catalog.sqlite3"


def verify(pack, projection, output, *, hybrid=True):
    if output.exists():
        raise FileExistsError("Preserve earlier validation receipts")
    check(pack)
    protocol = json.loads((pack / "protocol.json").read_text())
    source = Path(protocol["corpus"]["snapshot"])
    if not projection.exists():
        prepare_catalog(source, projection)
    started = time.perf_counter()
    service = CatalogService(source, projection, index=protocol["retrieval"]["prepared_index"] if hybrid else None)
    preparation_seconds = time.perf_counter() - started
    refs = {r["id"]: r["expected"] for r in json.loads((pack / "references.private.json").read_text())["cases"]}
    observations = []

    def call(name, args, *, case=None):
        result = service.execute(name, args)
        if result["status"] not in {"ok", "partial", "ambiguous", "not_found", "invalid_arguments"}:
            raise AssertionError(f"Tool unavailable: {name} {result['payload']}")
        observations.append({"case": case, "tool": name, "arguments": args, "result": result})
        return result

    try:
        described = call("describe_catalog", {})
        assert described["payload"]["fiche_count"] == protocol["corpus"]["counts"]["fiches"]
        assert described["payload"]["passage_count"] == protocol["corpus"]["counts"]["passages"]
        arguments = [
            {"scope": {"brand": "Yamaha", "min_year": 2020, "max_year": 2020}, "equipment_filters": [{"name": "ABS", "status": "standard"}, {"name": "shifter", "status": "standard"}]},
            {"scope": {"brand": "Honda", "min_year": 2020, "max_year": 2020}, "equipment_filters": [{"name": "ABS", "status": "standard"}]},
            {"scope": {"brand": "BMW", "min_year": 2020, "max_year": 2020}, "equipment_filters": [{"name": "régulateur de vitesse", "status": "optional"}]},
            {"scope": {"min_year": 2020, "max_year": 2020}, "numeric_filters": [{"field": "seat_height_mm", "op": "<", "value": 800}]},
            {"scope": {"min_year": 2020, "max_year": 2020}, "numeric_filters": [{"field": "displacement_ccm", "op": ">=", "value": 450}, {"field": "displacement_ccm", "op": "<=", "value": 700}], "equipment_filters": [{"name": "ABS", "status": "standard"}]},
            {"scope": {"brand": "Yamaha", "min_year": 2020, "max_year": 2020}, "equipment_filters": [{"name": "ABS", "status": "unknown"}]},
            {"scope": {"brand": "Honda", "min_year": 2020, "max_year": 2020}, "missing_fields": ["weight_wet_kg"]},
            {"scope": {"brand": "BMW", "min_year": 2018, "max_year": 2020}, "numeric_filters": [{"field": "displacement_ccm", "op": ">=", "value": 1000}]},
        ]
        for n, args in enumerate(arguments, 1):
            cid = f"Q{n:02d}"
            counted = call("query_catalog", {**args, "mode": "count", "page_size": 1}, case=cid)
            assert counted["payload"]["total_matches"] == refs[cid]["count"]
            page_args = {**args, "mode": "list", "page_size": 50}
            ids = []
            while True:
                page = call("query_catalog", page_args, case=cid)
                ids.extend(r["identity"]["id"] for r in page["payload"]["rows"])
                cursor = page["pagination"]["next_cursor"]
                if cursor is None:
                    break
                page_args = {"mode": "list", "cursor": cursor}
            assert ids == refs[cid]["matching_ids"]
        for n in range(9, 23):
            cid = f"Q{n:02d}"
            expected = refs[cid]["evidence"]
            ids = [r["id"] for r in expected]
            fields = list(expected[0]["values"])
            result = call("compare_fiches" if n >= 17 else "get_fiches", {"object_ids": ids, "fields": fields,
                **({"sections": list({p["section"] for r in expected for p in r["passages"]}), "equipment_names": list({e["equipment"] for r in expected for e in r["equipment"]})} if n < 17 else {})}, case=cid)
            actual = result["payload"]["matrix" if n >= 17 else "fiches"]
            assert len(actual) == len(expected)
            for a, e in zip(actual, expected):
                assert a["identity"]["id"] == e["id"]
                assert {k: v["value"] for k, v in a["measures"].items()} == e["values"]
                for equip in e["equipment"]:
                    assert next(v["status"] for v in a["equipment"] if v["name"] == equip["equipment"]) == equip["status"]
            if n >= 17:
                assert {d["field"]: d["second_minus_first"] for d in result["payload"]["deltas"]} == refs[cid]["delta_second_minus_first"]
        for cid in ["Q23", "Q24", "Q25", "Q26", "Q28"]:
            for e in refs[cid]["evidence"]:
                result = call("get_fiches", {"object_ids": [e["id"]], "fields": [], "equipment_names": [], "sections": list({p["section"] for p in e["passages"]})}, case=cid)
                actual = {p["id"]: p["text"] for p in result["payload"]["fiches"][0]["passages"]}
                assert actual == {p["id"]: p["text"] for p in e["passages"]}
        chronology = call("search_passages", {"query": "DCT", "mode": "literal", "literal_terms": ["DCT"], "sections": ["Transmission"],
            "scope": {"brand": "Honda", "model_tokens": ["Gold Wing"]}, "order": "year_asc"}, case="Q27")
        assert chronology["payload"]["passages"][0]["year"] == refs["Q27"]["earliest_documented_year"]
        assert chronology["payload"]["retrieval"]["total_literal_matches"] == refs["Q27"]["matching_fiches"]
        for cid, query, scope in [("Q29", "Gold Wing", {"brand": "Honda", "min_year": 2018, "max_year": 2018}),
                ("Q30", "CB 500 F", {"brand": "Honda"}), ("Q31", "Z 650", {"brand": "Kawasaki", "min_year": 2020, "max_year": 2020}),
                ("Q32", "R 1250 RT", {"brand": "BMW", "min_year": 2020, "max_year": 2020})]:
            expected_ids = {r["id"] for r in refs[cid]["identities"]}
            found = []
            request = {"query": query, "scope": scope, "page_size": 50}
            while True:
                result = call("resolve_models", request, case=cid)
                found.extend(r["id"] for r in result["payload"]["candidates"])
                cursor = result["pagination"]["next_cursor"]
                if not cursor:
                    break
                request = {"query": query, "cursor": cursor}
            assert set(found) == expected_ids
        assert call("query_catalog", {"mode": "count", "numeric_filters": [{"field": "current_used_price", "op": "<", "value": 5000}]}, case="Q33")["status"] == "invalid_arguments"
        assert call("resolve_models", {"query": "Honda CB 500 F ZXQ-FICTIVE-999 2020"}, case="Q34")["status"] == "not_found"
        assert call("resolve_models", {"query": "Kawasaki Z 650 2020"}, case="Q35")["status"] == "ambiguous"
        call("get_fiches", {"object_ids": [refs["Q36"]["evidence"][0]["id"]], "sections": ["Infos pratiques"], "fields": [], "equipment_names": []}, case="Q36")
        refined = {**arguments[0], "numeric_filters": [{"field": "seat_height_mm", "op": "<", "value": 850}], "mode": "count"}
        assert call("query_catalog", refined, case="Q37")["payload"]["total_matches"] == refs["Q37"]["turns"][1]["total"]
        call("compare_fiches", {"object_ids": [r["id"] for r in refs["Q38"]["turns"][1]["evidence"]], "fields": ["seat_height_mm"]}, case="Q38")
        e = refs["Q39"]["turns"][1]["evidence"][0]
        result = call("get_fiches", {"object_ids": [e["id"]], "fields": [], "sections": [], "equipment_names": ["ABS"]}, case="Q39")
        assert result["payload"]["fiches"][0]["equipment"][0]["status"] == e["equipment"][0]["status"]
        page = call("query_catalog", {"mode": "list", "scope": {"brand": "Honda", "min_year": 2020, "max_year": 2020}, "page_size": 5,
            "sort": [{"field": "model", "direction": "asc"}]}, case="Q40")
        following = call("query_catalog", {"mode": "list", "cursor": page["pagination"]["next_cursor"]}, case="Q40")
        assert [r["identity"]["id"] for r in page["payload"]["rows"]] == refs["Q40"]["turns"][0]["matching_ids"]
        assert [r["identity"]["id"] for r in following["payload"]["rows"]] == refs["Q40"]["turns"][1]["matching_ids"]
        warmup_seconds = None
        if hybrid:
            t = time.perf_counter()
            service.index.encoder("Préparation de la recherche locale dans le catalogue.")
            warmup_seconds = time.perf_counter() - t
            result = call("search_passages", {"query": "boîte DCT robotisée et marche arrière", "mode": "hybrid", "scope": {"object_ids": ["c0a73ac3d40825ff"]}, "sections": ["Transmission"]}, case="hybrid_scope")
            assert result["payload"]["passages"][0]["id"] == "c0a73ac3d40825ff:section:2"
        assert digest(source) == protocol["corpus"]["sha256"]
        report = {"status": "passed", "created_utc": datetime.now(timezone.utc).isoformat(), "basis": "Actual common tool calls checked against frozen internal catalogue references, not model answer correctness",
            "covered_cases": sorted({r["case"] for r in observations if r["case"] and r["case"].startswith("Q")}),
            "tools": sorted({r["tool"] for r in observations}), "validated_index_passages": service.index.validated_passages if hybrid else None,
            "preparation_seconds": preparation_seconds, "embedding_warmup_seconds": warmup_seconds,
            "source_sha256": service.snapshot_id, "source_unchanged": True,
            "implementation_sha256": {str(p.relative_to(ROOT)): digest(p) for p in [
                ROOT / "src/bikefinder_rag/catalog/sql_rag_service.py", ROOT / "src/bikefinder_rag/catalog/sql_rag_retrieval.py",
                ROOT / "src/bikefinder_rag/agent/sql_rag_contract.py"]},
            "observations": observations}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return {k: v for k, v in report.items() if k != "observations"}
    finally:
        service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--projection", type=Path, default=DEFAULT_PROJECTION)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sql-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.pack, args.projection, args.out, hybrid=not args.sql_only), ensure_ascii=False, indent=2))

#!/usr/bin/env python3
"""Replay recorded tool regressions locally, without requesting a new answer."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from bikefinder_rag.agent.sql_rag_context import bounded_result
from bikefinder_rag.catalog.sql_rag_service import CatalogService, digest


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "eval_results/technical/sql-rag-cheap-models-20261014/pilot-v3.json"
PACK = ROOT / "eval_results/technical/sql-rag-comparison-20261014-v5"


def check(run, output, pack=PACK):
    if output.exists():
        raise FileExistsError("Preserve previous regression verification receipts")
    run_hash = digest(run)
    report = json.loads(run.read_text())
    assert digest(pack / "manifest.json") == report["protocol"]["pack_manifest_sha256"]
    corpus = json.loads((pack / "protocol.json").read_text())["corpus"]
    assert corpus["sha256"] == report["protocol"]["source_sha256"]
    source = Path(corpus["snapshot"])
    projection = ROOT / "data/technical/sql-rag-service-v2/catalog.sqlite3"
    assert digest(source) == corpus["sha256"]
    service = CatalogService(source, projection)
    checks = []

    def recorded(model, case, turn=1):
        session = next(r for r in report["results"] if r["model"] == model and r["case_id"] == case)
        return next(t for t in session["turns"] if t["turn"] == turn)

    def execute(call):
        return service.execute(call["name"], deepcopy(call["arguments"]))

    try:
        luna = recorded("openai/gpt-6-luna", "Q37", 2)
        counted, mistyped = luna["calls"]
        correct = execute(counted)
        rejected = execute(mistyped)
        assert correct["payload"]["total_matches"] == 3
        assert rejected["status"] == "invalid_arguments"
        assert "total_matches" not in rejected["payload"] and not rejected["evidence"]
        assert not rejected["coverage"]["exhaustive"] and rejected["coverage"]["searched_fiches"] == 0
        recovery_args = deepcopy(mistyped["arguments"])
        # Use the exact earlier selection, not a fuzzy correction of the bad ID.
        recovery_args["scope"] = deepcopy(counted["arguments"]["scope"])
        recovered = service.execute(mistyped["name"], recovery_args)
        assert recovered["status"] == "ok" and recovered["payload"]["total_matches"] == 3
        assert len(recovered["payload"]["rows"]) == 3
        checks.append({"id": "luna-Q37-scope", "status": "passed", "before": {
            "status": mistyped["result"]["status"], "matches": mistyped["result"]["payload"]["total_matches"],
            "searched_fiches": mistyped["result"]["coverage"]["searched_fiches"]},
            "after": {"mistyped_scope": rejected, "correct_count": correct["payload"]["total_matches"],
                      "recovered_selection": recovered["payload"]["rows"]}})

        haiku = recorded("anthropic/claude-haiku-5.5", "Q27")
        family_call = next(c for c in haiku["calls"] if c["name"] == "resolve_models")
        family = execute(family_call)
        members = list(family["payload"]["candidates"])
        cursor = family["pagination"]["next_cursor"]
        while cursor:
            page = service.execute("resolve_models", {"query": family_call["arguments"]["query"], "cursor": cursor})
            assert page["status"] in {"ok", "ambiguous"}
            members.extend(page["payload"]["candidates"])
            cursor = page["pagination"]["next_cursor"]
        assert len(members) == family["pagination"]["total"] == 64
        assert {m["brand"] for m in members} == {"Honda"}
        natural = service.execute("query_catalog", {"mode": "count", "scope": {"model_tokens": ["gold", "wing"]}})
        assert natural["payload"]["total_matches"] == 64
        checks.append({"id": "gold-wing-family", "status": "passed", "before_count": family_call["result"]["pagination"]["total"],
            "after_count": len(members), "brands": sorted({m["brand"] for m in members}),
            "natural_scope_count": natural["payload"]["total_matches"]})

        haiku = recorded("anthropic/claude-haiku-5.5", "Q24")
        equipment_call = next(c for c in haiku["calls"] if c["name"] == "get_fiches" and c["result"]["status"] == "ok")
        raw = execute(equipment_call)
        view = bounded_result(raw, 24000)
        eid = "c0a73ac3d40825ff:row:12"
        original = next(p for proof in equipment_call["result"]["evidence"]
                        for p in ((proof.get("equipment") or {}).get("decision") or {}).get("passages", []) if p["id"] == eid)
        promoted = next(p for p in view["evidence"] if p["evidence_id"] == eid)
        assert promoted["text"] == original["text"] and promoted["section"] == original["section"]
        assert promoted["object_id"] == "c0a73ac3d40825ff"
        assert view["sources"][promoted["object_id"]]["source_url"]
        checks.append({"id": "haiku-Q24-original-row-citation", "status": "passed",
            "proof": promoted, "note": "Previously nested source text is now an explicit citable proof; no new source text."})

        lite = recorded("google/gemini-3.5-flash-lite", "Q37")
        query = next(c for c in lite["calls"] if c["name"] == "query_catalog")
        view = bounded_result(execute(query), 24000)
        expected_ids = {r["identity"]["id"] + ":identity" for r in query["result"]["payload"]["rows"]}
        proofs = {p["evidence_id"]: p for p in view["evidence"]}
        assert expected_ids <= proofs.keys()
        assert all(proofs[eid]["claim_scope"] == "identity_only" for eid in expected_ids)
        assert all(r["identity"]["model"] and r["identity"]["year"] == 2020 for r in view["payload"]["rows"])
        checks.append({"id": "flash-lite-Q37-identity-citations", "status": "passed", "identity_proofs": len(expected_ids),
            "note": "Identity-only proof availability is verified; this does not establish equipment claims or model answer correctness."})

        qwen = recorded("qwen/qwen3.5-flash-02-23", "Q37")
        query = next(c for c in qwen["calls"] if c["name"] == "query_catalog")
        raw = execute(query)
        view = bounded_result(raw, 24000)
        original_ids = [r["identity"]["id"] for r in raw["payload"]["rows"]]
        assert len(original_ids) == 8
        assert view["payload"]["page_scope"]["object_ids"] == original_ids
        assert view["payload"]["page_scope"]["all_matches_in_page"]
        assert len(view["payload"]["rows"]) == len(original_ids), "Reduce optional numeric details before dropping members of the selection"
        original_fields = set().union(*(r["measures"].keys() for r in raw["payload"]["rows"]))
        delivered_fields = set().union(*(r["measures"].keys() for r in view["payload"]["rows"]))
        omitted_fields = original_fields - delivered_fields
        assert omitted_fields <= set(view["view"].get("fields_omitted", []))
        expected_equipment = {eid for r in raw["payload"]["rows"] for e in r["equipment"] for eid in e["evidence_ids"]}
        assert expected_equipment <= {p["evidence_id"] for p in view["evidence"]}
        if omitted_fields:
            assert view["status"] == "partial" and view["view"]["content_omitted"]
        assert len(json.dumps(view, ensure_ascii=False, separators=(",", ":"), sort_keys=True)) <= 24000
        checks.append({"id": "qwen-Q37-selection-survives-detail-truncation", "status": "passed",
            "before_rows": len(query["delivered_result"]["payload"]["rows"]), "after_rows": len(view["payload"]["rows"]),
            "omitted_measure_fields": sorted(omitted_fields),
            "page_scope": view["payload"]["page_scope"], "view_status": view["status"],
            "note": "The recorded model is not re-run; its factual mistakes remain historical observations."})

        assert digest(run) == run_hash and digest(source) == corpus["sha256"]
        result = {"status": "passed", "created_utc": datetime.now(timezone.utc).isoformat(),
            "basis": "Local replay of recorded tool requests; not a third paid benchmark or evidence of new model scores",
            "new_cloud_requests": 0, "baseline_run_sha256": run_hash, "source_sha256": corpus["sha256"],
            "source_unchanged": True, "model_answers_regenerated": False, "checks": checks,
            "implementation_sha256": {str(p.relative_to(ROOT)): digest(p) for p in [
                ROOT / "src/bikefinder_rag/catalog/sql_rag_service.py", ROOT / "src/bikefinder_rag/agent/sql_rag_context.py",
                ROOT / "src/bikefinder_rag/agent/sql_rag_session.py", ROOT / "src/bikefinder_rag/agent/sql_rag_output.py", Path(__file__)]}}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return {k: v for k, v in result.items() if k != "checks"}
    finally:
        service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=RUN)
    parser.add_argument("--pack", type=Path, default=PACK)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.run, args.out, args.pack), ensure_ascii=False, indent=2))

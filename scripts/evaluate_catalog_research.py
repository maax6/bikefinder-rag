"""Check actual allowlisted Gradio receipts and their original SQL source rows."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

from dotenv import load_dotenv
from gradio_client import Client

from bikefinder_rag.catalog.enriched import _rows
from bikefinder_rag.db.client import get_connection


def evaluate(url, questions, traces, out, case_id=None):
    if out.exists():
        raise FileExistsError("Choose a fresh output; keep prior observations")
    load_dotenv()
    results = []
    with get_connection() as conn:
        conn.execute("SET default_transaction_read_only = on")
        for case in json.loads(questions.read_text())["cases"]:
            if case_id and case["id"] != case_id:
                continue
            before = set(traces.glob("*.json"))
            client = Client(url, verbose=False)
            started = time.perf_counter()
            visible = client.predict(case["question"], [], "", api_name="/chat")
            if isinstance(visible, tuple):
                visible = visible[0]
            content = visible[-1]["content"]
            answer = "\n".join(p["text"] for p in content if p.get("type") == "text") if isinstance(content, list) else content
            elapsed = time.perf_counter() - started
            receipts = [json.loads(p.read_text()) for p in set(traces.glob("*.json")) - before]
            receipts = [r for r in receipts if r["question"] == case["question"] and r["answer"] == answer]
            if len(receipts) != 1:
                raise ValueError("Actual frontend answer must match exactly one server receipt")
            receipt = receipts[0]
            research = receipt.get("_catalog_research") or {}
            evidence = receipt.get("_catalog_evidence") or {}
            sources = evidence.get("sources", [])
            verified = []
            for source in sources:
                rows = _rows(conn, "SELECT id,brand,model,year,source_url,source_sha256,record FROM technical_fiches WHERE id=%s", [source["object_id"]])
                valid = len(rows) == 1 and all(rows[0][k] == source[k] for k in ["brand", "model", "year", "source_url", "source_sha256"])
                if valid:
                    sections = rows[0]["record"].get("technical_sections", [])
                    valid = all(any(p["section"] == s["section"] and p["original_text"] == s["text"] for s in sections) for p in source["passages"])
                verified.append(valid)
            checks = {"actual_frontend_receipt": True, "all_passages_match_live_sql": all(verified),
                      "no_year_input_required": not bool(re.search(r"Quel millésime souhaites-tu|Précise le millésime", answer, re.I))}
            if case["kind"] == "research":
                checks.update(local_planner=research.get("local_planner_calls", 0) >= 1,
                              actual_tools=research.get("tool_calls", 0) >= len(case["brands"]),
                              local_writer=(receipt.get("_catalog_generation") or {}).get("published") is True,
                              requested_families=all(any(s["brand"] == b for s in sources) for b in case["brands"]),
                              cited_families=all(any(s["brand"] == b and s["source_url"] in answer for s in sources) for b in case["brands"]),
                              missing_visible=bool(evidence.get("missing")) and "Preuves manquantes" in answer)
                if "Honda" in case["brands"]:
                    checks["documented_honda_2018_cited"] = any(s["object_id"] == "c0a73ac3d40825ff" and s["source_url"] in answer for s in sources)
                    checks["honda_dct_year_answered"] = "2018" in answer and bool(re.search(r"DCT|robotis", answer, re.I))
                    generation = receipt.get("_catalog_generation") or {}
                    candidates = (generation.get("candidate") or {}).get("claims", [])
                    context_ids = [s["object_id"] for s in sources for _ in s["passages"]]
                    gate = generation.get("proof_check") or {}
                    accepted = gate.get("verified_claim_indices", [])
                    checks["honda_2018_in_verified_local_prose"] = any(
                        i in accepted and "2018" in c.get("text", "") and re.search(r"DCT|robotis", c.get("text", ""), re.I)
                        and any(p.startswith("P") and p[1:].isdigit() and 0 < int(p[1:]) <= len(context_ids)
                                and context_ids[int(p[1:])-1] == "c0a73ac3d40825ff" for p in c.get("sources", []))
                        for i, c in enumerate(candidates))
                if "BMW" in case["brands"]:
                    checks["bmw_automation_gap_specific"] = any("BMW" in m.get("message", "") and any(t in m.get("message", "") for t in ["Aucune mention", "ne suffisent pas"]) for m in evidence.get("missing", []))
            elif case["kind"] == "unknown_identity":
                checks.update(no_substitution=not sources, explicit_gap="Preuves manquantes" in answer)
            else:
                checks.update(sql_control="8 fiches" in answer, no_research=not research)
            result = {**case, "seconds": elapsed, "checks": checks, "receipt": receipt}
            results.append(result)
            out.parent.mkdir(parents=True, exist_ok=True)
            report = {"timestamp": datetime.now(timezone.utc).isoformat(), "front_url": url,
                      "method": "Actual fresh Gradio session matched to its allowlisted server receipt; passages checked against read-only live SQL; targeted root-authored cases, not an independent benchmark", "results": results}
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"id": case["id"], "seconds": round(elapsed, 2), "checks": checks, "answer": answer}, ensure_ascii=False), flush=True)
    return all(all(r["checks"].values()) for r in results) and bool(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:7863/")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--traces", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case")
    args = parser.parse_args()
    raise SystemExit(0 if evaluate(args.url, args.questions, args.traces, args.out, args.case) else 1)

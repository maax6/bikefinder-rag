"""Evaluate actual Gradio answers: useful requested facts, citations and total time."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from gradio_client import Client

from bikefinder_rag.catalog.enriched import _rows, folded
from bikefinder_rag.db.client import get_connection


def facts(answer):
    # A date in a hyperlink is not a date answered to the user.
    answer = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", answer)
    answer = re.sub(r"https?://\S+", "", answer)
    text = folded(answer)
    for word, number in {"six": "6", "sept": "7", "septembre": "septembre"}.items():
        text = re.sub(r"\b" + word + r"\b", number, text)
    patterns = {
        "manual6": r"manuell.{0,45}6\s*(?:rapports?|vitesses?)|6\s*(?:rapports?|vitesses?).{0,45}manuell",
        "dct7": r"(?:dct|double embrayage).{0,65}7\s*(?:rapports?|vitesses?)|7\s*(?:rapports?|vitesses?).{0,65}(?:dct|double embrayage)",
        "honda2018": r"2018", "bmw2025": r"2025", "announce2017": r"2017",
        "asa_optional": r"asa.{0,100}(?:option|optionnel)|(?:option|optionnel).{0,100}asa",
        "asa_auto": r"(?:asa|bmw|rt).{0,180}(?:automati|automatis)|(?:automati|automatis).{0,100}asa",
        "asa_clutch": r"embrayage.{0,45}automatis|automatis.{0,45}embrayage",
        "asa_manual": r"manuel", "choice_honda": r"(?:choix|choisir|ou|deux|egalement|disponibl)",
        "fr_june2025": r"juin\s+2025", "us2026": r"2026",
        "market_distinction": r"france|francais", "dct_dual_clutch": r"double embrayage",
        "retrofit_unknown": r"(?:ne.{0,40}(?:peux|peut|permet|etabli|prouv|confirm|certifi)|pas.{0,30}(?:etabli|confirm|document)|aucune.{0,35}(?:preuve|source)|sans.{0,20}(?:preuve|confirm))",
        "identity_unknown": r"(?:ne.{0,40}(?:peux|peut|etablir|prouv|confirm)|non document|inconn|aucune.{0,25}(?:source|preuve))",
    }
    result = {k: bool(re.search(p, text, re.S)) for k, p in patterns.items()}
    result["market_distinction"] &= bool(re.search(r"usa|etats.unis|americ", text)) and "2025" in text and "2026" in text
    return result


def verify_sources(conn, evidence, index):
    manifest = json.loads((index / "manifest.json").read_text())
    sources = {s["id"]: s for s in manifest["sources"]}
    for p in evidence.get("passages", []):
        identity = p["identity"]
        if p["kind"] == "manufacturer":
            source = sources[identity["object_id"]]
            content = Path(source["snapshot"]).read_bytes()
            if hashlib.sha256(content).hexdigest() != p["source_sha256"] or p["source_url"] != source["url"]:
                return False
            original = re.sub(r"\s+", " ", BeautifulSoup(content, "html.parser").get_text(" ", strip=True))
            if p["text"] not in original or p["market"] != source["market"] or p["published"] != source["published"]:
                return False
        else:
            rows = _rows(conn, "SELECT id,brand,model,year,source_url,source_sha256,record FROM technical_fiches WHERE id=%s", [identity["object_id"]])
            if len(rows) != 1 or any(rows[0][k] != identity[k] for k in ["brand", "model", "year"]):
                return False
            if any(rows[0][k] != p[k] for k in ["source_url", "source_sha256"]):
                return False
            if not any(s["section"] == p["section"] and s["text"] == p["text"] for s in rows[0]["record"]["technical_sections"]):
                return False
    return True


def evaluate(url, questions, traces, index, out, split, repeats):
    load_dotenv()
    if out.exists():
        raise FileExistsError("Keep earlier experiments; choose a new report")
    cases = [c for c in json.loads(questions.read_text())["cases"] if c["split"] == split]
    results = []
    with get_connection() as conn:
        conn.execute("SET default_transaction_read_only = on")
        for repeat in range(repeats):
            for case in cases:
                before = set(traces.glob("*.json"))
                client = Client(url, verbose=False)
                started = time.perf_counter()
                visible = client.predict(case["question"], [], "", api_name="/chat")
                if isinstance(visible, tuple):
                    visible = visible[0]
                value = visible[-1]["content"]
                answer = "\n".join(p["text"] for p in value if p.get("type") == "text") if isinstance(value, list) else value
                elapsed = time.perf_counter() - started
                receipts = [json.loads(p.read_text()) for p in set(traces.glob("*.json")) - before]
                matched = [r for r in receipts if r["question"] == case["question"] and r["answer"] == answer]
                if len(matched) != 1:
                    raise ValueError("Visible frontend response has no unique actual receipt")
                receipt = matched[0]
                generation = receipt.get("_catalog_generation") or {}
                evidence = receipt.get("_catalog_evidence") or {}
                trace = receipt.get("_catalog_research") or {}
                gate = generation.get("proof_check") or {}
                observed = facts(answer)
                checks = {"actual_frontend_receipt": True, "source_integrity": verify_sources(conn, evidence, index),
                          "under_10_seconds": elapsed < 10,
                          "expected_facts": all(observed[f] for f in case["facts"]),
                          "direct_answer": not bool(re.search(r"une fiche|j.ai (?:trouve|retrouve)|lecture directe|fiches correspondent", answer, re.I)),
                          "zero_local_planner": trace.get("local_planner_calls") == 0}
                if case.get("kind") != "missing":
                    checks.update(local_prose=generation.get("published") is True,
                                  complete_verified_prose=gate.get("accepted") is True,
                                  one_local_writer=trace.get("local_writer_calls") == 1,
                                  live_jev_no_cache=receipt.get("_catalog_jev_calls") == 1,
                                  cited_manufacturer=all(any(p["identity"]["brand"] == b and p["kind"] == "manufacturer" and p["source_url"] in answer for p in evidence.get("passages", [])) for b in case["brands"]))
                elif "identity_unknown" in case["facts"]:
                    checks["no_substitution"] = not evidence.get("passages")
                results.append({**case, "repeat": repeat, "seconds": elapsed, "checks": checks, "observed_facts": observed, "receipt": receipt})
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "url": url,
                    "questions_sha256": hashlib.sha256(questions.read_bytes()).hexdigest(), "split": split,
                    "method": "Actual new Gradio sessions matched to observed receipts; source text/identity checked locally; root-authored targeted questions; first holdout run preserved; no cached Jev gate",
                    "results": results}, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps({"id": case["id"], "repeat": repeat, "seconds": round(elapsed, 3),
                    "failed": [k for k, v in checks.items() if not v], "answer": answer,
                    "error": generation.get("error_detail")}, ensure_ascii=False), flush=True)
    return all(all(r["checks"].values()) for r in results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:7864/")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--traces", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--split", choices=["dev", "holdout"], required=True)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    raise SystemExit(0 if evaluate(args.url, args.questions, args.traces, args.index, args.out, args.split, args.repeats) else 1)

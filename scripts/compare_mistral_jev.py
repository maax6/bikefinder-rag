"""Small development comparison: local Mistral, cloud Mistral and Jev workflow.

All paid requests share a total ceiling including conservative unknown usage.
Jev uses its existing decision API/renderer, not the conversational tool API.
References are deliberately not loaded here; completed answers require review.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time

from dotenv import load_dotenv
import requests

from bikefinder_rag.agent.sql_rag_adapters import OllamaAdapter, OpenRouterAdapter
from bikefinder_rag.agent.sql_rag_session import CatalogSession
from bikefinder_rag.catalog.sql_rag_service import CatalogService, digest

ROOT = Path(__file__).resolve().parents[1]
CASES = ["Q01", "Q10", "Q17", "Q24", "Q27", "Q31", "Q34", "Q37"]


class Spending:
    def __init__(self, maximum, save):
        if not math.isfinite(maximum) or maximum <= 0:
            raise ValueError("A finite positive total budget is required")
        self.maximum, self.save = maximum, save
        self.records = []
        self.halted = False

    @property
    def debit(self):
        return sum(r["debit_usd"] for r in self.records)

    def reserve(self, model, payload, input_rate, output_rate, max_output):
        if self.halted:
            raise RuntimeError("Reservation violation stopped all further requests")
        # Conservative byte allowance includes histories, tools and results.
        bound = 2 * len(json.dumps(payload, ensure_ascii=False).encode()) + 4096
        amount = bound * input_rate + max_output * output_rate
        if self.debit + amount > self.maximum:
            raise RuntimeError("Total API cost ceiling would be exceeded; request not sent")
        record = {"model": model, "input_token_bound": bound,
                  "reserved_usd": amount, "debit_usd": amount, "status": "pending"}
        self.records.append(record)
        self.save()
        return record

    def settle(self, record, raw):
        usage = raw.get("usage") or {}
        cost = usage.get("cost")
        record["usage"] = usage
        record["status"] = "response_received"
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and math.isfinite(cost) and cost > record["reserved_usd"]:
            record.update(debit_usd=cost, status="reservation_violation")
            self.halted = True
            self.save()
            raise RuntimeError("Provider cost exceeded its reservation; stop all further requests")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and 0 <= cost <= record["reserved_usd"]:
            record["debit_usd"] = cost
            record["reported_cost_usd"] = cost
        # Missing/invalid costs retain the full reserve, including outputs.
        self.save()


class LimitedCloud(OpenRouterAdapter):
    def __init__(self, model, spending, pricing, pace=0):
        super().__init__(model, max_tokens=2400)
        self.spending = spending
        self.input_rate = float(pricing["prompt"]) * 2
        self.output_rate = float(pricing["completion"]) * 2
        self.pace = pace
        self.last_request = None
        self.settings["minimum_request_gap_seconds"] = pace

    def _post(self, url, payload, headers, timeout):
        delay = max(0, self.pace - (time.monotonic() - self.last_request)) if self.last_request is not None else 0
        if delay >= timeout:
            raise requests.Timeout("Request spacing reached the turn deadline")
        if delay:
            time.sleep(delay)
        timeout -= delay
        self.last_request = time.monotonic()
        payload = deepcopy(payload)
        payload["provider"]["max_price"] = {"prompt": self.input_rate * 1e6,
            "completion": self.output_rate * 1e6, "request": 0}
        record = self.spending.reserve(self.model, payload, self.input_rate,
                                       self.output_rate, payload["max_tokens"])
        raw = super()._post(url, payload, headers, timeout)
        self.spending.settle(record, raw)
        return raw


def main(args):
    if args.out.exists():
        raise FileExistsError("Preserve first runs; choose a new directory")
    args.out.mkdir(parents=True)
    load_dotenv(ROOT / ".env")
    pack = args.pack
    protocol = json.loads((pack / "protocol.json").read_text())
    inputs = json.loads((pack / "model-inputs.json").read_text())["cases"]
    cases = [c for c in inputs if c["id"] in (args.case or CASES)]
    prompt = (pack / "system-prompt.txt").read_text()
    report = {"created_utc": datetime.now(timezone.utc).isoformat(),
              "maximum_total_api_usd": args.budget, "results": [],
              "scope": "Known eight-case development replay, not an independent generalization test",
              "comparability": "Two common-tool agents versus existing Jev decisions + SQL renderer; workflow differences are explicit",
              "pack_sha256": digest(pack / "manifest.json"), "source_sha256": protocol["corpus"]["sha256"],
              "script_sha256": digest(__file__), "timeout_seconds": 30,
              "local_api_cost_usd": 0, "electricity_and_amortization": "not measured"}
    spending = None

    def save():
        if spending is not None:
            report["paid_requests"] = spending.records
            report["conservative_total_debit_usd"] = spending.debit
        (args.out / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    spending = Spending(args.budget, save)
    if args.prior_receipt:
        prior = json.loads(args.prior_receipt.read_text())
        spending.records = deepcopy(prior["paid_requests"])
        report["prior_receipt_sha256"] = digest(args.prior_receipt)
        if spending.debit > args.budget:
            raise ValueError("Prior spending already exceeds the total ceiling")
    net = requests.Session()
    net.trust_env = False
    if not args.local_only:
        inventory = net.get("https://openrouter.ai/api/v1/models", timeout=20)
        inventory.raise_for_status()
        candidate = next(m for m in inventory.json()["data"] if m["id"] == args.cloud_model)
        report["cloud_inventory"] = {k: candidate.get(k) for k in ["id", "pricing", "supported_parameters", "context_length"]}
    save()
    start = time.perf_counter()
    service = CatalogService(protocol["corpus"]["snapshot"], ROOT / "data/technical/sql-rag-service-v2/catalog.sqlite3",
                             index=protocol["retrieval"]["prepared_index"])
    if service.snapshot_id != protocol["corpus"]["sha256"]:
        raise ValueError("Frozen source fingerprint differs")
    service.index.encoder("Préparation de la recherche locale dans le catalogue.")
    report["service_preparation_seconds"] = time.perf_counter() - start
    adapters = [] if args.remote_only else [OllamaAdapter("mistral-small3.2:latest", max_tokens=2400)]
    if not args.local_only:
        adapters.append(LimitedCloud(args.cloud_model, spending, candidate["pricing"], pace=args.pace))
    for adapter in adapters:
        label = adapter.provider + ":" + adapter.model
        if adapter.provider == "ollama":
            report["local_warmup"] = adapter.warmup(prompt)
        for case in cases:
            session = CatalogSession(service, adapter, prompt)
            for question in case["turns"]:
                result = session.ask(question)
                result.update(candidate=label, case_id=case["id"])
                report["results"].append(result)
                save()
                print(json.dumps({"candidate": label, "case": case["id"], "status": result["status"],
                                  "seconds": result["timing"]["full_answer_seconds"]}), flush=True)
                if result["status"] != "completed":
                    break
        adapter.close()
    service.close()
    if args.local_only or args.cloud_only:
        report["status"] = "executed_semantic_review_pending"
        net.close()
        save()
        return
    # Existing Jev workflow, fresh decision cache and no generative cloud path.
    from bikefinder_rag.agent import jev_router as jev
    from bikefinder_rag.db.client import get_connection
    previous_root = jev.ROOT
    previous_post = jev.requests.post
    jev.ROOT = args.out.resolve() / "isolated-cache"

    def guarded_post(url, **kwargs):
        if url != jev.URL:
            raise RuntimeError("Only the Jev decision endpoint is allowed in this workflow")
        record = spending.reserve(jev.MODEL, kwargs["json"], 0.042 / 1e6, 0, 0)
        response = net.post(url, **kwargs)
        if response.status_code == 200:
            spending.settle(record, response.json())
        return response

    jev.requests.post = guarded_post
    conn = None
    try:
        conn = get_connection()
        for case in cases:
            history = []
            for turn, question in enumerate(case["turns"], 1):
                started = time.perf_counter()
                try:
                    routing = jev.route_question(conn, question, history)
                    result = {"routing": routing, "answer": routing.get("answer"),
                              "status": "returned" if routing.get("answer") is not None else "requires_generation"}
                    history.extend([{"role": "user", "content": question},
                        {"role": "assistant", "content": routing.get("answer") or "", "_catalog_plan": routing.get("plan"),
                         "_catalog_pending": routing.get("pending")}])
                except Exception as error:
                    result = {"status": "failed", "error_type": type(error).__name__}
                result.update(candidate="existing-jev-workflow", case_id=case["id"], turn=turn,
                              question=question, full_answer_seconds=time.perf_counter() - started)
                report["results"].append(result)
                save()
                print(json.dumps({k: result[k] for k in ["candidate", "case_id", "status", "full_answer_seconds"]}), flush=True)
                if result["status"] != "returned":
                    break
    finally:
        if conn is not None:
            conn.close()
        jev.requests.post, jev.ROOT = previous_post, previous_root
        net.close()
    report["status"] = "executed_semantic_review_pending"
    save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--budget", type=float, default=.5)
    parser.add_argument("--cloud-model", default="mistralai/mistral-small-2603")
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--remote-only", action="store_true")
    parser.add_argument("--cloud-only", action="store_true")
    parser.add_argument("--prior-receipt", type=Path)
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--pace", type=float, default=0)
    main(parser.parse_args())

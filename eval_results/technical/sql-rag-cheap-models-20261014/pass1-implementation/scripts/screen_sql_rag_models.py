#!/usr/bin/env python3
"""First-pass inexpensive cloud model screening on identical catalogue tasks.

This is an internally authored eight-case development pilot, not the reserved
forty-case benchmark. References are opened only after candidate runs finish.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import random
import re
import statistics
import time

from dotenv import load_dotenv
import requests

from bikefinder_rag.agent.sql_rag_adapters import OpenRouterAdapter
from bikefinder_rag.agent.sql_rag_contract import TOOLS
from bikefinder_rag.agent.sql_rag_output import SUBMIT_ANSWER
from bikefinder_rag.agent.sql_rag_session import CatalogSession
from bikefinder_rag.catalog.sql_rag_service import CatalogService, digest

ROOT = Path(__file__).resolve().parents[1]
MODELS = ["openai/gpt-6-luna", "anthropic/claude-haiku-5.5", "google/gemini-3.8-flash",
          "google/gemini-3.5-flash-lite", "google/gemma-4-26b-a4b-it", "google/gemma-4-31b-it",
          "nvidia/nemotron-3.5-lightning", "qwen/qwen3.5-flash-02-23"]
CASES = ["Q01", "Q10", "Q17", "Q24", "Q27", "Q31", "Q34", "Q37"]


def finite_nonnegative(value):
    """Usage or prices that cannot be trusted never silently become zero."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def valid_tokens(value):
    number = finite_nonnegative(value)
    return int(number) if number is not None and number.is_integer() else None


def effective_prices(pricing, tokens):
    prices = {k: v for k, v in pricing.items() if k != "overrides"}
    for tier in sorted(pricing.get("overrides", []), key=lambda t: int(t["min_prompt_tokens"])):
        if tokens >= int(tier["min_prompt_tokens"]):
            prices.update({k: v for k, v in tier.items() if k != "min_prompt_tokens"})
    for field in ["prompt", "completion"]:
        if finite_nonnegative(prices.get(field)) is None:
            raise ValueError("Captured token prices must be finite and non-negative")
    return prices


def input_rate_ceiling(pricing, tokens):
    prices = effective_prices(pricing, tokens)
    # Automatic cache writes can cost more than ordinary prompt tokens. Budget
    # every billed input token at the worst captured ordinary/cache-write rate.
    fields = ["prompt", "input_cache_read", "input_cache_write", "input_cache_write_1h"]
    rates = [finite_nonnegative(prices[k]) for k in fields if k in prices]
    if any(rate is None for rate in rates):
        raise ValueError("Captured input/cache prices must be finite and non-negative")
    return max(rates)


def least_supported_effort(model):
    reasoning = model.get("reasoning") or {}
    if not reasoning.get("mandatory"):
        return "none"
    supported = reasoning.get("supported_efforts")
    for effort in ["none", "minimal", "low", "medium", "high", "xhigh", "max"]:
        if effort in (supported or []):
            return effort
    raise ValueError("Mandatory reasoning has no declared supported effort")


def safe_error_metadata(response, key):
    """Only a short message/code, never provider headers or whole error bodies."""
    try:
        value = response.json()
    except (ValueError, TypeError):
        return None
    error = value.get("error") if isinstance(value, dict) else None
    if not isinstance(error, dict):
        return None

    def scrub(text):
        if key:
            text = text.replace(key, "[redacted]")
        text = re.sub(r"(?i)Bearer\s+\S+|sk-[A-Za-z0-9_-]+", "[redacted]", text)
        return " ".join(text.split())

    result = {}
    code = error.get("code")
    if isinstance(code, (int, str)) and not isinstance(code, bool):
        result["code"] = scrub(str(code))[:80]
    message = error.get("message")
    if isinstance(message, str):
        # Error text that echoes prompt bodies is not retained; the normal short
        # router descriptions still explain rate limits or invalid parameters.
        result["message"] = scrub(message)[:400]
    return result or None


class InputBudget:
    """One ledger shared by all adapters; pending/unknown requests keep reserves."""
    def __init__(self, maximum, on_update=None, prior_records=None):
        if not math.isfinite(maximum) or maximum <= 0:
            raise ValueError("Input budget must be positive and finite")
        self.maximum, self.on_update = maximum, on_update
        self.records = deepcopy(prior_records or [])
        for index, record in enumerate(self.records):
            if finite_nonnegative(record.get("input_debit_usd")) is None or finite_nonnegative(record.get("input_reservation_usd")) is None:
                raise ValueError("Prior request ledger contains invalid input spending")
            record["prior_request_index"] = record.get("request_index")
            record.update(request_index=index + 1, phase="prior_run")
        self.blocked_requests = 0
        self.exhausted = False
        self.reservation_violation = False
        if self.debit > self.maximum:
            raise ValueError("Prior input spending already exceeds this budget")

    @property
    def debit(self):
        return sum(record["input_debit_usd"] for record in self.records)

    def changed(self):
        if self.on_update:
            self.on_update()

    def reserve(self, model, payload, pricing, *, input_rate_bound=None):
        # Byte-level text tokenization plus a deliberately wide allowance for
        # provider conversion of messages/functions. No question-only estimate:
        # the complete history, all seven wire schemas and tool results count.
        payload_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        upper = 2 * payload_bytes + 4096
        rate = max(input_rate_ceiling(pricing, upper), input_rate_bound or 0)
        amount = upper * rate
        if self.debit + amount > self.maximum:
            self.blocked_requests += 1
            self.exhausted = True
            self.changed()
            raise RuntimeError("Input budget would be exceeded; request not sent")
        record = {"request_index": len(self.records) + 1, "model": model,
            "phase": "current_run",
            "payload_utf8_bytes": payload_bytes, "prompt_token_upper_bound": upper,
            "prompt_rate_per_token": float(effective_prices(pricing, upper)["prompt"]),
            "input_rate_ceiling_per_token": rate, "input_reservation_usd": amount,
            "input_debit_usd": amount, "known_input_at_list_usd": None,
            "billed_input_tokens": None, "output_tokens": None, "output_cost_at_list_usd": None,
            "reported_total_cost_usd": None, "status": "pending", "uncertain": True}
        self.records.append(record)
        # Persist the reserve before the transport runs. A killed process leaves
        # a truthful outstanding reservation in the last saved report.
        self.changed()
        return record

    def settle(self, record, raw, pricing):
        usage = raw.get("usage") or {}
        tokens = valid_tokens(usage.get("prompt_tokens"))
        output = valid_tokens(usage.get("completion_tokens"))
        record.update(status="response_received", request_id=raw.get("id"),
            upstream_provider=raw.get("provider"), billed_input_tokens=tokens,
            output_tokens=output, reported_total_cost_usd=finite_nonnegative(usage.get("cost")),
            raw_usage=deepcopy(usage))
        cost_details = usage.get("cost_details") or {}
        record["provider_reported_input_cost_usd"] = finite_nonnegative(cost_details.get("upstream_inference_prompt_cost"))
        record["provider_reported_output_cost_usd"] = finite_nonnegative(cost_details.get("upstream_inference_completions_cost"))
        if tokens is not None:
            rates = effective_prices(pricing, tokens)
            record["known_input_at_list_usd"] = tokens * float(rates["prompt"])
            record["input_debit_usd"] = tokens * max(input_rate_ceiling(pricing, tokens), record["input_rate_ceiling_per_token"])
            record["uncertain"] = False
            if tokens > record["prompt_token_upper_bound"] or record["input_debit_usd"] > record["input_reservation_usd"] + 1e-12:
                self.reservation_violation = True
                record["reservation_violation"] = True
        else:
            record["status"] = "response_without_input_usage"
        if output is not None:
            # Completion list cost is an estimate, while usage.cost is the
            # actual reported combined bill (including any cache discounts).
            record["output_cost_at_list_usd"] = output * float(effective_prices(pricing, tokens or record["prompt_token_upper_bound"])["completion"])
        self.changed()

    def fail(self, record, status, *, known_unbilled=False, http_status=None):
        record.update(status=status, http_status=http_status, uncertain=not known_unbilled)
        if known_unbilled:
            record["input_debit_usd"] = 0.0
        self.changed()

    def summary(self, phase=None):
        records = [r for r in self.records if phase is None or r.get("phase") == phase]
        return {"max_input_cost_usd": self.maximum, "conservative_input_debit_usd": sum(r["input_debit_usd"] for r in records),
            "known_input_at_list_usd": sum(r["known_input_at_list_usd"] or 0 for r in records),
            "uncertain_input_reservations_usd": sum(r["input_debit_usd"] for r in records if r["uncertain"]),
            "actual_reported_total_cost_usd": sum(r["reported_total_cost_usd"] or 0 for r in records),
            "output_cost_at_list_usd": sum(r["output_cost_at_list_usd"] or 0 for r in records),
            "reported_total_costs_missing": sum(r["reported_total_cost_usd"] is None for r in records),
            "uncertain_requests": sum(r["uncertain"] for r in records), "requests_started": len(records),
            "blocked_requests": self.blocked_requests, "reservation_violation": self.reservation_violation}


class BudgetedOpenRouterAdapter(OpenRouterAdapter):
    """The shared protocol is unchanged; only transport price/budget bounds add."""
    def __init__(self, model, *, pricing, budget, **kwargs):
        super().__init__(model, **kwargs)
        self.pricing, self.budget = deepcopy(pricing), budget
        tiers = [effective_prices(pricing, 0),
                 *[effective_prices(pricing, int(tier["min_prompt_tokens"])) for tier in pricing.get("overrides", [])]]
        # Inventory prices are advertised minima. Allow ordinary provider
        # variation at twice the base rate and any declared context price tier,
        # while reserving spending at that explicit route cap.
        caps = {field: max(Decimal(str(tiers[0][field])) * 2,
                           *[Decimal(str(tier[field])) for tier in tiers]) for field in ["prompt", "completion"]}
        self.price_caps = {field: float(value * 1000000) for field, value in caps.items()}
        self.price_caps["request"] = 0
        cache_factor = max(input_rate_ceiling(tier, 0) / float(tier["prompt"]) if float(tier["prompt"]) else 1 for tier in tiers)
        self.input_rate_bound = float(caps["prompt"]) * cache_factor
        self.settings.update(provider_max_price_usd_per_million=deepcopy(self.price_caps),
                             input_rate_ceiling_per_token=self.input_rate_bound,
                             max_input_cost_usd=budget.maximum)

    def _post(self, url, payload, headers, timeout):
        payload = deepcopy(payload)
        # OpenRouter max_price uses USD per million tokens. Restrict routes to
        # captured bounded rates and reject flat per-request fees. Documentation:
        # https://openrouter.ai/docs/guides/routing/provider-selection#max-price
        payload.setdefault("provider", {})["max_price"] = self.price_caps
        record = self.budget.reserve(self.model, payload, self.pricing, input_rate_bound=self.input_rate_bound)
        try:
            response = self.session.post(url, json=payload, headers=headers, timeout=max(.1, timeout), allow_redirects=False)
        except requests.Timeout:
            self.budget.fail(record, "timeout")
            raise
        except requests.RequestException:
            self.budget.fail(record, "transport_error")
            raise
        if response.status_code != 200:
            # Authentication rejection cannot run inference. Other error codes
            # can mask an upstream request, so keep their reservation.
            record["error_metadata"] = safe_error_metadata(response, self.key)
            self.budget.fail(record, "http_error", known_unbilled=response.status_code in {401, 403}, http_status=response.status_code)
            raise RuntimeError(f"{self.provider} HTTP {response.status_code}")
        try:
            raw = response.json()
            if not isinstance(raw, dict):
                raise ValueError("Provider response is not an object")
        except (ValueError, TypeError):
            self.budget.fail(record, "invalid_json")
            raise RuntimeError("OpenRouter returned invalid JSON") from None
        self.budget.settle(record, raw, self.pricing)
        return raw


def has_number(text, number):
    text = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?:\D|$))", "", text).replace(",", ".")
    return any(abs(float(n) - number) < 1e-6 for n in re.findall(r"(?<!\d)\d+(?:\.\d+)?(?!\d)", text))


def grade(receipt, expected):
    """Mechanical checks are a floor; semantic claim support remains unreviewed."""
    if receipt["status"] != "completed":
        return {"mechanical_checks": False, "semantic_review_required": True}
    text = receipt["answer"]
    final = receipt["final"]
    checks = {"delivered_citations": receipt["judgments"]["citations_valid"] is True}
    if "count" in expected:
        checks["expected_count_mentioned"] = has_number(text, expected["count"])
        checks["aggregate_matches_reference"] = any(e.get("kind") == "aggregate" and e.get("count") == expected["count"] for e in receipt["evidence"])
    if "evidence" in expected:
        known = [n for e in expected["evidence"] for n in e["values"].values() if n is not None]
        checks["expected_values_mentioned"] = all(has_number(text, n) for n in known)
        required_ids = {e["id"] for e in expected["evidence"]}
        cited = {eid for claim in final["claims"] for eid in claim["evidence_ids"]}
        cited_objects = {e.get("object_id", e.get("id")) for e in receipt["evidence"] if e["evidence_id"] in cited and e["kind"] != "aggregate"}
        checks["expected_identities_cited"] = required_ids <= cited_objects
    if "delta_second_minus_first" in expected:
        checks["expected_delta_mentioned"] = all(has_number(text, abs(n)) for n in expected["delta_second_minus_first"].values() if n is not None)
    if "earliest_documented_year" in expected:
        checks["expected_year_mentioned"] = has_number(text, expected["earliest_documented_year"])
        checks["exhaustive_literal_research"] = any(c["name"] == "search_passages" and c["arguments"].get("mode") == "literal" and c["result"]["coverage"]["exhaustive"] for c in receipt["calls"])
    if "identities" in expected:
        wanted = {e["id"] for e in expected["identities"]}
        returned = {c["id"] for call in receipt["calls"] for c in call["result"].get("payload", {}).get("candidates", [])}
        checks["variants_retrieved"] = wanted <= returned
        checks["variant_names_mentioned"] = all(e["model"].casefold() in text.casefold() for e in expected["identities"])
    if "fictional_variant" in expected:
        checks["missing_identity_reported"] = bool(final["missing"]) or final["needs_clarification"]
        checks["no_substitution_claim"] = not final["claims"]
    return {"checks": checks, "mechanical_checks": all(checks.values()), "semantic_review_required": True}


def summarize(results, models):
    summary = []
    for model in models:
        sessions = [s for s in results if s["model"] == model]
        turns = [r for s in sessions for r in s["turns"]]
        elapsed = [r["timing"]["full_answer_seconds"] for r in turns]
        costs = [r["usage"]["cost_usd"] for r in turns]
        requests = [record for r in turns for record in r.get("budget_requests", [])]
        successes = [r["timing"]["full_answer_seconds"] for r in turns if r["status"] == "completed"]
        summary.append({"model": model, "sessions": len(sessions), "turns": len(turns),
            "completed_sessions": sum(all(r["status"] == "completed" for r in s["turns"]) and len(s["turns"]) == s["expected_turns"] for s in sessions),
            "mechanically_passing_sessions": sum(all(g["mechanical_checks"] for g in s.get("grades", [])) and len(s.get("grades", [])) == s["expected_turns"] for s in sessions),
            "median_turn_seconds": statistics.median(elapsed) if elapsed else None,
            "median_successful_turn_seconds": statistics.median(successes) if successes else None,
            "observed_max_turn_seconds": max(elapsed) if elapsed else None,
            "actual_reported_cost_usd": sum(r["reported_total_cost_usd"] or 0 for r in requests),
            "costs_missing": sum(r["reported_total_cost_usd"] is None for r in requests),
            "input_cost_at_list_usd": sum(r["known_input_at_list_usd"] or 0 for r in requests),
            "conservative_input_debit_usd": sum(r["input_debit_usd"] for r in requests),
            "output_cost_at_list_usd": sum(r["output_cost_at_list_usd"] or 0 for r in requests),
            "uncertain_requests": sum(r["uncertain"] for r in requests),
            "semantic_correctness": None})
    return summary


def screen(args):
    if args.out.exists():
        raise FileExistsError("Keep initial screening runs; choose a fresh report")
    load_dotenv(ROOT / ".env")
    protocol = json.loads((args.pack / "protocol.json").read_text())
    manifest = json.loads((args.pack / "manifest.json").read_text())
    for name, sha in manifest["files"].items():
        # Integrity checks do not open reference content into model context.
        if digest(args.pack / name) != sha:
            raise ValueError("Frozen pack changed")
    if json.loads((args.pack / "tools.json").read_text())["tools"] != TOOLS or json.loads((args.pack / "answer-channel.json").read_text()) != SUBMIT_ANSWER:
        raise ValueError("Active interfaces differ from frozen pack")
    verification = json.loads(args.verification.read_text())
    if verification["status"] != "passed" or len(verification["covered_cases"]) != 40 or verification["source_sha256"] != protocol["corpus"]["sha256"] or any(digest(ROOT / p) != sha for p, sha in verification["implementation_sha256"].items()):
        raise ValueError("Real-corpus service verification must pass for this implementation")
    for name, sha in protocol["retrieval"]["file_sha256"].items():
        if digest(Path(protocol["retrieval"]["prepared_index"]) / name) != sha:
            raise ValueError("Frozen retrieval index changed")
    inputs = {c["id"]: c["turns"] for c in json.loads((args.pack / "model-inputs.json").read_text())["cases"]}
    prompt = (args.pack / "system-prompt.txt").read_text()
    inventory = {m["id"]: m for m in json.loads(args.inventory.read_text())}
    models = args.model or MODELS
    cases = args.case or CASES
    if len(set(models)) != len(models) or any(m not in MODELS for m in models):
        raise ValueError("Select only the eight authorized exact model IDs, once each")
    if len(set(cases)) != len(cases) or any(c not in CASES for c in cases):
        raise ValueError("Select only the eight common development cases, once each")
    if any(m not in inventory or "tools" not in inventory[m]["supported_parameters"] for m in models):
        raise ValueError("Model not present in saved tool-capable inventory")
    efforts = {m: least_supported_effort(inventory[m]) for m in models}
    prior = None
    prior_records = []
    if args.prior_run:
        prior = json.loads(args.prior_run.read_text())
        prior_records = prior["request_budget_ledger"]
        if any(r["model"] not in MODELS for r in prior_records):
            raise ValueError("Prior run includes unauthorized model IDs")
        if args.prior_run.resolve() == args.out.resolve():
            raise ValueError("A prior run must remain a separate immutable report")
    service = CatalogService(protocol["corpus"]["snapshot"], args.projection, index=protocol["retrieval"]["prepared_index"])
    if prior and prior["protocol"]["source_sha256"] != service.snapshot_id:
        service.close()
        raise ValueError("Prior run did not use this corpus")
    startup = time.perf_counter()
    service.index.encoder("Préparation de la recherche locale dans le catalogue.")
    schedule = []
    rng = random.Random(20261014)
    for case in cases:
        order = models[:]
        rng.shuffle(order)
        schedule.extend({"model": m, "case": case} for m in order)
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "status": "running", "stage": "first_pass_internal_development_pilot",
        "protocol": {"models": models, "cases": cases, "repeats": 1, "seed": 20261014, "schedule": schedule,
                     "timeout_per_turn_seconds": 30, "rounds_per_turn": 4, "tool_calls_per_turn": 8, "max_input_cost_usd": args.max_input_cost,
                     "budget_scope": "Input only; completion cost tracked separately",
                     "input_reservation_rule": "2*UTF8 serialized payload bytes+4096 tokens at route prompt price cap times worst captured cache multiplier; before every HTTP request",
                     "successful_input_debit_rule": "Actual reported input token count at route prompt price cap times worst captured cache multiplier; missing usage retains reservation",
                     "provider_max_price": "Maximum of2*captured base or worst declared context tier, USD per million tokens; request fee cap0; no model or provider fallback",
                     "source_sha256": service.snapshot_id, "pack_manifest_sha256": digest(args.pack / "manifest.json"),
                     "interface_semantics_identical": True, "reasoning_effort": efforts,
                     "reasoning_policy": "Disable reasoning when optional; lowest supported effort when mandatory",
                     "provider_route": "OpenRouter, no model fallback",
                     "inventory_sha256": digest(args.inventory), "prices": {m: inventory[m]["pricing"] for m in models},
                     "implementation_sha256": {str(p.relative_to(ROOT)): digest(p) for p in [Path(__file__), ROOT / "src/bikefinder_rag/agent/sql_rag_adapters.py", ROOT / "src/bikefinder_rag/agent/sql_rag_session.py", ROOT / "src/bikefinder_rag/catalog/sql_rag_service.py", ROOT / "src/bikefinder_rag/catalog/sql_rag_retrieval.py"]}},
        "embedding_warmup_seconds": time.perf_counter() - startup, "results": []}
    budget = InputBudget(args.max_input_cost, prior_records=prior_records)
    report["prior_input_budget"] = budget.summary("prior_run")
    if args.prior_run:
        report["protocol"]["prior_run"] = {"path": str(args.prior_run.resolve()), "sha256": digest(args.prior_run),
                                          "status": prior["status"], "reason": "Retained configuration preflight costs/reserves count toward the same input cap"}

    def save():
        report["input_budget"] = budget.summary()
        report["current_input_budget"] = budget.summary("current_run")
        report["request_budget_ledger"] = budget.records
        report["actual_reported_cost_usd"] = report["input_budget"]["actual_reported_total_cost_usd"]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.out.with_suffix(args.out.suffix + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(args.out)

    budget.on_update = save
    adapters = {m: BudgetedOpenRouterAdapter(m, pricing=inventory[m]["pricing"], budget=budget, effort=efforts[m]) for m in models}
    report["protocol"]["provider_price_caps_usd_per_million"] = {m: a.price_caps for m, a in adapters.items()}
    save()
    try:
        for planned in schedule:
            model, case = planned["model"], planned["case"]
            session = CatalogSession(service, adapters[model], prompt)
            item = {"model": model, "case_id": case, "expected_turns": len(inputs[case]), "turns": []}
            report["results"].append(item)
            for question in inputs[case]:
                first_request = len(budget.records)
                receipt = session.ask(question)
                receipt["budget_requests"] = deepcopy(budget.records[first_request:])
                item["turns"].append(receipt)
                cost = receipt["usage"]["cost_usd"]
                save()
                print(json.dumps({"model": model, "case": case, "turn": receipt["turn"], "status": receipt["status"], "seconds": round(receipt["timing"]["full_answer_seconds"], 3), "cost_usd": cost, "error": receipt["error"]}, ensure_ascii=False), flush=True)
                if receipt["status"] != "completed":
                    break
            item["budget_debit_usd"] = sum(r["input_debit_usd"] for turn in item["turns"] for r in turn["budget_requests"])
            save()
            if budget.exhausted or budget.reservation_violation:
                report["status"] = "budget_stop" if budget.exhausted else "reservation_violation_stop"
                break
        else:
            report["status"] = "completed"
        # This file is not used by the adapters, sessions or tool service.
        references = {r["id"]: r["expected"] for r in json.loads((args.pack / "references.private.json").read_text())["cases"]}
        for item in report["results"]:
            expected = references[item["case_id"]]
            expected_turns = expected.get("turns", [expected])
            item["grades"] = [grade(receipt, reference) for receipt, reference in zip(item["turns"], expected_turns)]
        report["summary"] = summarize(report["results"], models)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
        return report["summary"]
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        report["summary"] = summarize(report["results"], models)
        save()
        raise
    finally:
        service.close()
        for adapter in adapters.values():
            adapter.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=ROOT / "eval_results/technical/sql-rag-comparison-20261014-v4")
    parser.add_argument("--projection", type=Path, default=ROOT / "data/technical/sql-rag-service-v2/catalog.sqlite3")
    parser.add_argument("--verification", type=Path, default=ROOT / "eval_results/technical/sql-rag-service-20261014/service-verification-v2-final.json")
    parser.add_argument("--inventory", type=Path, default=ROOT / "eval_results/technical/sql-rag-cheap-models-20261014/inventory.json")
    parser.add_argument("--model", action="append")
    parser.add_argument("--case", action="append")
    parser.add_argument("--prior-run", type=Path, help="Carry an earlier run's input charges and unresolved reservations into this same global budget")
    parser.add_argument("--max-input-cost", "--max-cost", dest="max_input_cost", type=float, default=2.0,
                        help="USD ceiling for conservative input accounting only (completion cost recorded separately)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not math.isfinite(args.max_input_cost) or args.max_input_cost <= 0:
        parser.error("--max-input-cost must be positive")
    print(json.dumps(screen(args), ensure_ascii=False, indent=2))

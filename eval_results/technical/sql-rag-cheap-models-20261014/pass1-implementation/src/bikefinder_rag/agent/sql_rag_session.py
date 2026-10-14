"""Shared bounded tool loop and observed receipts for every provider."""
from copy import deepcopy
import json
import resource
import re
import sys
import time

import requests

from bikefinder_rag.catalog.sql_rag_service import canonical, validate
from bikefinder_rag.agent.sql_rag_output import ANSWER_SCHEMA

FINAL_SCHEMA = ANSWER_SCHEMA


def parse_final(text):
    # A Markdown JSON fence is a wire presentation, not another model repair call.
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(\{.*\})\s*```\s*", text, re.S)
    value = json.loads(fenced[1] if fenced else text)
    validate(FINAL_SCHEMA, value, "answer")
    return value


def bounded_result(result, maximum):
    """Deterministic shrinking, disclosed as partial; never clip JSON/text bytes."""
    view = deepcopy(result)
    if len(canonical(view)) <= maximum:
        return view
    view["status"] = "partial"
    view["coverage"].update(exhaustive=False, truncation_reason="context_budget")
    view["missing"].insert(0, {"subject": "tool_response", "field": "context", "reason": "Request smaller pages or selected sections/fields to retrieve omitted evidence"})

    def lists(value, path=()):
        found = []
        if isinstance(value, dict):
            for key, child in value.items():
                found.extend(lists(child, path + (key,)))
        elif isinstance(value, list) and value:
            # Never trim identity arrays/criteria; only content result arrays.
            if path and path[-1] in {"original_rows", "passages", "rows", "fiches", "matrix", "candidates", "equipment_names", "section_names", "evidence"}:
                found.append((len(canonical(value)), path, value))
            elif path == ("missing",) and len(value) > 1:
                found.append((len(canonical(value)), path, value))
            else:
                for i, child in enumerate(value):
                    found.extend(lists(child, path + (i,)))
        return found

    while len(canonical(view)) > maximum:
        options = lists(view)
        if not options:
            raise ValueError("Tool result cannot fit the remaining context budget")
        _, path, values = max(options, key=lambda x: (x[0], repr(x[1])))
        values.pop()
    # Evidence may have been removed; session validates citations only against what remains.
    view["pagination"]["returned"] = min(view["pagination"]["returned"], len(view.get("payload", {}).get("rows", view.get("payload", {}).get("passages", []))))
    return view


class CatalogSession:
    def __init__(self, service, adapter, prompt, *, rounds=4, calls=8, timeout=30, context_characters=32000):
        self.service, self.adapter = service, adapter
        self.messages = [{"role": "system", "content": prompt}]
        self.rounds, self.max_calls, self.timeout, self.context_characters = rounds, calls, timeout, context_characters
        self.evidence = {}
        self.turn = 0

    def ask(self, question):
        started = time.perf_counter()
        deadline = time.monotonic() + self.timeout
        self.turn += 1
        self.messages.append({"role": "user", "content": question})
        calls, model_seconds, tool_seconds, usage, responses = [], 0.0, 0.0, [], []
        remaining_context = self.context_characters
        # Budget covers tool outputs kept from prior turns too; never silently discard history.
        remaining_context -= sum(len(m["content"]) for m in self.messages if m["role"] == "tool")
        status, error, final = "error", None, None
        try:
            for step in range(self.rounds):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Turn deadline reached")
                t = time.perf_counter()
                try:
                    completion = self.adapter.complete(self.messages, deadline - time.monotonic())
                finally:
                    model_seconds += time.perf_counter() - t
                usage.append(completion.usage)
                responses.append({"round": step + 1, "text": completion.text, "native": completion.native,
                    "usage": completion.usage, "model": completion.model, "finish_reason": completion.finish_reason})
                if time.monotonic() >= deadline:
                    raise TimeoutError("Model exceeded turn deadline")
                self.messages.append({"role": "assistant", "content": completion.text, "native": completion.native})
                submission = [c for c in completion.calls if c.name == "submit_answer"]
                if submission and len(completion.calls) != 1:
                    raise ValueError("Terminal answer cannot be submitted alongside another tool")
                if not completion.calls or submission:
                    if completion.finish_reason in {"length", "MAX_TOKENS", "incomplete"}:
                        raise ValueError("Model output truncated")
                    final = parse_final(canonical(submission[0].arguments)) if submission else parse_final(completion.text)
                    cited = {eid for claim in final["claims"] for eid in claim["evidence_ids"]}
                    if cited - self.evidence.keys():
                        raise ValueError("Final answer cites evidence not delivered by tools")
                    if not final["claims"] and not final["missing"] and not final["needs_clarification"]:
                        raise ValueError("Factual answer has no evidence claims")
                    status = "completed"
                    if submission:
                        self.messages.append({"role": "tool", "name": "submit_answer", "call_id": submission[0].id,
                                              "content": '{"status":"format_and_references_accepted"}'})
                    break
                if step == self.rounds - 1 or len(calls) + len(completion.calls) > self.max_calls:
                    raise ValueError("Tool/model-round budget exhausted")
                for call in completion.calls:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Turn deadline reached before tool")
                    t = time.perf_counter()
                    result = self.service.execute(call.name, call.arguments)
                    seconds = time.perf_counter() - t
                    tool_seconds += seconds
                    view = bounded_result(result, remaining_context)
                    serialized = canonical(view)
                    remaining_context -= len(serialized)
                    for proof in view["evidence"]:
                        self.evidence[proof["evidence_id"]] = proof
                    calls.append({"id": call.id, "name": call.name, "arguments": call.arguments, "result": result,
                                  "delivered_result": view, "seconds": seconds})
                    self.messages.append({"role": "tool", "name": call.name, "call_id": call.id, "content": serialized})
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Tool exceeded turn deadline")
        except (TimeoutError, requests.Timeout):
            status, error = "timeout", "Turn deadline or provider timeout reached"
        except (ValueError, TypeError, KeyError, RuntimeError, requests.RequestException) as exc:
            error = str(exc) if not isinstance(exc, requests.RequestException) else type(exc).__name__
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        costs = [u.get("cost_usd") for u in usage]
        cost = sum(costs) if costs and all(c is not None for c in costs) else None
        totals = {key: sum(u[key] for u in usage) if usage and all(u.get(key) is not None for u in usage) else None for key in ["input_tokens", "output_tokens"]}
        # Non-streaming adapter: no invented TTFT or first-useful-result measurement.
        receipt = {"turn": self.turn, "question": question, "status": status, "error": error,
            "answer": final["answer"] if status == "completed" else "", "final": final if status == "completed" else None,
            "calls": calls, "model_responses": responses, "evidence": list(self.evidence.values()),
            "timing": {"full_answer_seconds": time.perf_counter() - started, "model_seconds": model_seconds, "tool_seconds": tool_seconds,
                       "ttft_seconds": None, "first_useful_result_seconds": None},
            "usage": {**totals, "cost_usd": cost, "peak_memory_bytes": int(peak if sys.platform == "darwin" else peak * 1024), "requests": usage},
            "adapter": self.adapter.metadata(),
            "judgments": {"correct": None, "complete": None, "citations_valid": True if status == "completed" else None,
                          "claims_supported": None, "reviewer": None}}
        if status != "completed":
            # A failed session cannot be continued with unanswered native tool calls.
            self.messages = [self.messages[0]]
            self.evidence.clear()
        return receipt

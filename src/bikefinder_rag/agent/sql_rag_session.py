"""Shared bounded tool loop and observed receipts for every provider."""
import json
import resource
import re
import sys
import time

import requests

from bikefinder_rag.catalog.sql_rag_service import canonical, validate
from bikefinder_rag.agent.sql_rag_output import ANSWER_SCHEMA
from bikefinder_rag.agent.sql_rag_context import bounded_result, compact_result

FINAL_SCHEMA = ANSWER_SCHEMA


def parse_final(text):
    # A Markdown JSON fence is a wire presentation, not another model repair call.
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(\{.*\})\s*```\s*", text, re.S)
    value = json.loads(fenced[1] if fenced else text)
    validate(FINAL_SCHEMA, value, "answer")
    return value


class CatalogSession:
    def __init__(self, service, adapter, prompt, *, rounds=6, calls=8, timeout=30,
                 context_characters=32000, result_characters=24000):
        self.service, self.adapter = service, adapter
        self.messages = [{"role": "system", "content": prompt}]
        self.rounds, self.max_calls, self.timeout, self.context_characters = rounds, calls, timeout, context_characters
        self.result_characters = min(result_characters, context_characters)
        self.evidence = {}
        self.accepted_citations = set()
        self.turn = 0

    def _context_size(self):
        return sum(len(m["content"]) for m in self.messages if m["role"] == "tool")

    def _refresh_evidence(self):
        self.evidence = {}
        for message in self.messages:
            if message["role"] == "tool":
                for proof in json.loads(message["content"]).get("evidence", []):
                    self.evidence[proof["evidence_id"]] = proof

    def _request_answer_repair(self, completion, submission, feedback, step, error, kind, repairs):
        """Reject one presentation error without manufacturing facts or sources."""
        native_arguments_valid = bool(submission and isinstance(submission[0].arguments, dict))
        if submission and not native_arguments_valid:
            # Keep the malformed native response in the receipt, but never send
            # invalid arguments or an orphan tool acknowledgement to a provider.
            self.messages[-1] = {"role": "assistant", "content": completion.text or
                "La soumission structurée précédente est invalide; aucune réponse n'a été acceptée."}
        message = {"role": "tool", "name": "submit_answer", "call_id": submission[0].id,
                   "content": canonical(feedback)} if native_arguments_valid else {"role": "user", "content": canonical(feedback)}
        self.messages.append(message)
        repairs.append({"round": step + 1, "error": str(error), "kind": kind,
                        "invalid_native_terminal_removed_from_history": bool(submission and not native_arguments_valid)})

    def _identifier_feedback(self, unknown):
        """Only a known fiche ID in a proof slot is a repairable type mistake.

        Unknown proof IDs are still rejected immediately. A fiche identifier is
        never converted automatically into an identity, numeric or count proof.
        """
        known_objects = {p["object_id"] for p in self.evidence.values() if isinstance(p.get("object_id"), str)}
        if not unknown or not unknown <= known_objects:
            return None
        feedback = {"status": "answer_format_rejected", "error": "Fiche object IDs were used instead of evidence IDs.",
            "invalid_identifiers": sorted(unknown)[:4],
            "instruction": "Dans claims.evidence_ids, copie uniquement les evidence_id exacts des preuves déjà reçues. "
            "Un object_id sert à sélectionner une fiche, pas à prouver un fait. Une preuve identity_only ne prouve que l'identité. "
            "Choisis une preuve adaptée à chaque affirmation; conserve les faits et inconnues déjà obtenus. "
            "Ne lance aucun nouvel outil pour cette réparation de format."}
        # Leave room for the acceptance acknowledgement in the same 1 KiB
        # control reserve. Remove whole identifiers, never clip their strings.
        while len(canonical(feedback)) > 896 and feedback["invalid_identifiers"]:
            feedback["invalid_identifiers"].pop()
        return feedback

    def _compact_history(self, target, events):
        """Reduce earlier pages explicitly, preserving native call IDs/citations.

        Accepted answers, user messages, criteria, counts and cited source text
        stay in history. Omitted uncited rows can be queried again from the base.
        """
        before = self._context_size()
        if before <= target:
            return
        candidates = sorted((m for m in self.messages if m["role"] == "tool"
                             and m["name"] != "submit_answer"), key=lambda m: len(m["content"]), reverse=True)
        for message in candidates:
            excess = self._context_size() - target
            if excess <= 0:
                break
            size = len(message["content"])
            maximum = max(1000, size - excess)
            if maximum >= size:
                continue
            while True:
                try:
                    view = bounded_result(json.loads(message["content"]), maximum,
                                          protected_evidence=self.accepted_citations)
                    break
                except ValueError:
                    # Criteria and protected source rows have a minimum size.
                    # Keep them intact and spread the reduction across pages.
                    if maximum >= size:
                        view = None
                        break
                    maximum = min(size, maximum * 2)
            if view is None or len(canonical(view)) >= size:
                continue
            message["content"] = canonical(view)
            events.append({"kind": "history_page_reduction", "tool": message["name"],
                           "call_id": message["call_id"], "before_characters": size,
                           "after_characters": len(message["content"]),
                           "protected_evidence_ids": sorted(self.accepted_citations),
                           "omissions": view.get("view", {}).get("omissions", {})})
        self._refresh_evidence()

    def ask(self, question):
        started = time.perf_counter()
        deadline = time.monotonic() + self.timeout
        self.turn += 1
        self.messages.append({"role": "user", "content": question})
        calls, model_seconds, tool_seconds, usage, responses = [], 0.0, 0.0, [], []
        compression_events, repairs = [], []
        context_before = self._context_size()
        # Leave half of the same total cap available for a follow-up. If older
        # proof cannot shrink without losing accepted citations, it stays intact.
        self._compact_history(self.context_characters // 2, compression_events)
        status, error, final = "error", None, None
        try:
            for step in range(self.rounds):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Turn deadline reached")
                if step == self.rounds - 1 or len(calls) >= self.max_calls:
                    self.messages.append({"role": "user", "content":
                        "Le budget de recherche est terminé. Réponds maintenant avec submit_answer, "
                        "les preuves déjà fournies et les limites connues. Aucun nouvel appel catalogue."})
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
                    try:
                        if completion.finish_reason in {"length", "MAX_TOKENS", "incomplete"}:
                            raise ValueError("Model output truncated")
                        final = parse_final(canonical(submission[0].arguments)) if submission else parse_final(completion.text)
                    except (ValueError, TypeError) as exc:
                        if repairs or step == self.rounds - 1:
                            raise
                        # Repair only the output presentation/schema. No expected
                        # answers and no additional factual evidence are supplied.
                        feedback = {"status": "answer_format_rejected", "error": str(exc)[:160],
                            "instruction": "Soumets une réponse complète conforme à submit_answer (answer, claims, missing, needs_clarification). "
                            "Conserve les faits déjà obtenus, cite leurs evidence_ids et signale les inconnues. "
                            "Ne lance aucun nouvel outil pour cette réparation de format."}
                        self._request_answer_repair(completion, submission, feedback, step, exc, "schema_or_truncation", repairs)
                        continue
                    cited = {eid for claim in final["claims"] for eid in claim["evidence_ids"]}
                    unknown = cited - self.evidence.keys()
                    if unknown:
                        feedback = self._identifier_feedback(unknown)
                        if feedback is not None and not repairs and step < self.rounds - 1:
                            self._request_answer_repair(completion, submission, feedback, step,
                                "Fiche object IDs used instead of evidence IDs", "citation_identifier", repairs)
                            continue
                        raise ValueError("Final answer cites evidence not delivered by tools")
                    if not final["claims"] and not final["missing"] and not final["needs_clarification"]:
                        raise ValueError("Factual answer has no evidence claims")
                    status = "completed"
                    self.accepted_citations.update(cited)
                    if submission:
                        self.messages.append({"role": "tool", "name": "submit_answer", "call_id": submission[0].id,
                                              "content": '{"status":"format_and_references_accepted"}'})
                    break
                if step == self.rounds - 1 or len(calls) + len(completion.calls) > self.max_calls:
                    raise ValueError("Tool/model-round budget exhausted")
                if repairs:
                    raise ValueError("Formatting repair attempted another catalogue tool")
                for call in completion.calls:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Turn deadline reached before tool")
                    t = time.perf_counter()
                    result = self.service.execute(call.name, call.arguments)
                    seconds = time.perf_counter() - t
                    tool_seconds += seconds
                    compact = compact_result(result)
                    target = min(self.result_characters, len(canonical(compact)))
                    # A small reserve covers the final/repair control receipts;
                    # these acknowledgements also count in retained tool output.
                    self._compact_history(self.context_characters - target - 1024, compression_events)
                    remaining_context = self.context_characters - self._context_size() - 1024
                    sort = call.arguments.get("sort", []) if isinstance(call.arguments, dict) else []
                    protected_fields = {entry["field"] for entry in sort if isinstance(entry, dict)
                                        and isinstance(entry.get("field"), str)} if isinstance(sort, list) else set()
                    view = bounded_result(compact, min(self.result_characters, remaining_context),
                                          protected_fields=protected_fields)
                    serialized = canonical(view)
                    compression_events.append({"kind": "tool_result_view", "tool": call.name, "call_id": call.id,
                        "before_characters": len(canonical(result)), "after_characters": len(serialized),
                        "content_omitted": view["view"]["content_omitted"], "omissions": view["view"].get("omissions", {})})
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
            "context": {"limit_characters": self.context_characters, "per_result_limit_characters": self.result_characters,
                        "before_characters": context_before, "retained_characters": self._context_size(),
                        "compression_events": compression_events}, "format_repairs": repairs,
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
            self.accepted_citations.clear()
        return receipt

#!/usr/bin/env python3
"""Render one or two observed SQL + RAG passes as a portable offline report.

The renderer never calls a model. Semantic judgments are shown only when their
review is bound to the exact input report; missing data remains visible.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
ARTICLE = "https://claude.dev/blog/using-claude-code-the-unreasonable-effectiveness-of-html/"
NAMES = {
    "openai/gpt-6-luna": "GPT-6 Luna",
    "anthropic/claude-haiku-5.5": "Claude Haiku 5.5",
    "google/gemini-3.8-flash": "Gemini 3.8 Flash",
    "google/gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite",
    "google/gemma-4-26b-a4b-it": "Gemma 4 26B A4B",
    "google/gemma-4-31b-it": "Gemma 4 31B",
    "nvidia/nemotron-3.5-lightning": "Nemotron 3.5 Lightning",
    "qwen/qwen3.5-flash-02-23": "Qwen3.5 Flash 02-23",
}
KINDS = {"sql_count": "Comptage SQL", "fiche": "Valeur de fiche", "comparison": "Comparaison",
         "rag": "Recherche de passages", "discovery": "Découverte", "missing": "Donnée absente",
         "conversation": "Conversation", "pagination": "Pagination"}
FAILURE_CAUSES = {
    "rounds": "Limite de tours ou d’appels",
    "context": "Résultat trop volumineux",
    "timeout": "Délai dépassé",
    "http_429": "Limitation API (HTTP 429)",
    "format": "Format ou schéma invalide",
    "citations": "Références rejetées",
    "other": "Autre erreur",
}


def failure_cause(receipt):
    """Group observed execution errors, without inferring semantic correctness."""
    if receipt.get("status") == "completed":
        return None
    error = str(receipt.get("error") or "").casefold()
    if receipt.get("status") == "timeout" or "timeout" in error or "deadline" in error:
        return "timeout"
    if re.search(r"http\s*429\b", error):
        return "http_429"
    if "tool/model-round budget exhausted" in error or "model-round" in error:
        return "rounds"
    if "context budget" in error or "context_budget" in error:
        return "context"
    if "evidence not delivered" in error or "no evidence claims" in error:
        return "citations"
    format_errors = ("expecting value", "expecting property", "expecting ','", "invalid json",
                     "unterminated string", "extra data", "terminal answer", "output truncated",
                     "additional properties", "is required", "must be", "expected object",
                     "expected array", "answer.", "answer:")
    if any(phrase in error for phrase in format_errors):
        return "format"
    return "other"


def median(values):
    values = [value for value in values if isinstance(value, (int, float))]
    return statistics.median(values) if values else None


def normalize(report_path, review_path, pack):
    raw = report_path.read_bytes()
    report = json.loads(raw)
    report_sha = hashlib.sha256(raw).hexdigest()
    review = json.loads(review_path.read_text()) if review_path and review_path.exists() else None
    warnings = []
    if review and review.get("run_sha256") != report_sha:
        warnings.append("La relecture ne correspond pas à cette version du rapport. Ses notes sont masquées.")
        review = None
    protocol = report.get("protocol", {})
    planned_models = protocol.get("models", list(dict.fromkeys(s["model"] for s in report.get("results", []))))
    planned_cases = protocol.get("cases", list(dict.fromkeys(s["case_id"] for s in report.get("results", []))))
    questions = {}
    if pack and (pack / "questions.json").exists():
        questions = {case["id"]: case for case in json.loads((pack / "questions.json").read_text())["cases"]}
    review_models = {model["model"]: model for model in (review or {}).get("models", [])}
    review_turns = {(model["model"], case["case_id"], turn["turn"]): turn
                    for model in (review or {}).get("models", []) for case in model.get("cases", [])
                    for turn in case.get("turns", [])}
    cases = []
    for case_id in planned_cases:
        question = questions.get(case_id, {})
        observed = next((s for s in report.get("results", []) if s["case_id"] == case_id), {})
        turns = question.get("turns", [r["question"] for r in observed.get("turns", [])])
        expected = observed.get("expected_turns", len(turns) or (2 if case_id == "Q37" else 1))
        cases.append({"id": case_id, "kind": KINDS.get(question.get("kind"), question.get("kind", "Question")),
                      "turns": turns, "expected_turns": expected})
    expected_per_model = sum(c["expected_turns"] for c in cases)
    sessions = []
    for session in report.get("results", []):
        turns = []
        # Proofs retained in a conversation remain linked to the metadata actually
        # delivered on earlier turns. A new session starts with an empty lookup.
        source_metadata = {}
        raw_proofs = {}
        for position, receipt in enumerate(session.get("turns", []), start=1):
            index = receipt.get("turn", position)
            judgment = review_turns.get((session["model"], session["case_id"], index))
            category = judgment.get("category") if judgment else ("failure" if receipt.get("status") != "completed" else "unreviewed")
            for call in receipt.get("calls", []):
                delivered = call.get("delivered_result", call.get("result")) or {}
                source_metadata.update(delivered.get("sources", {}))
                raw_proofs.update({p["evidence_id"]: p for p in (call.get("result") or {}).get("evidence", [])
                                   if isinstance(p, dict) and "evidence_id" in p})
            # Compact views retain one source map rather than repeating identities
            # and URLs on every proof. Expand metadata for inspection, not content.
            proof = []
            for delivered_proof in receipt.get("evidence", []):
                identity = source_metadata.get(delivered_proof.get("object_id"), {})
                original = raw_proofs.get(delivered_proof.get("evidence_id"), {})
                enriched = {key: original[key] for key in ("brand", "model", "year", "source_url") if key in original}
                enriched.update(identity)
                enriched.update(delivered_proof)
                proof.append(enriched)
            calls = [{"name": call.get("name"), "arguments": call.get("arguments"),
                      "seconds": call.get("seconds"), "delivered_result": call.get("delivered_result", call.get("result"))}
                     for call in receipt.get("calls", [])]
            turns.append({"turn": index, "question": receipt.get("question", ""),
                          "status": receipt.get("status", "unknown"), "category": category,
                          "failure_cause": failure_cause(receipt),
                          "answer": receipt.get("answer", ""), "error": receipt.get("error"),
                          "final": receipt.get("final"), "evidence": proof, "calls": calls,
                          "model_responses": receipt.get("model_responses", []),
                          "timing": receipt.get("timing", {}), "usage": receipt.get("usage", {}),
                          "budget_requests": receipt.get("budget_requests", []), "review": judgment,
                          "context": receipt.get("context"), "format_repairs": receipt.get("format_repairs", []),
                          "mechanical": session.get("grades", [])[position - 1]
                          if position <= len(session.get("grades", [])) else None})
        expected = session.get("expected_turns", len(turns))
        categories = [turn["category"] for turn in turns]
        if not turns:
            category = "not_started"
        elif len(turns) < expected and report.get("status") == "running":
            category = "pending"
        elif len(turns) < expected or "failure" in categories:
            category = "failure"
        elif "incorrect" in categories:
            category = "incorrect"
        elif "partial" in categories:
            category = "partial"
        elif categories and all(value == "correct" for value in categories):
            category = "correct"
        else:
            category = "unreviewed"
        sessions.append({"model": session["model"], "case_id": session["case_id"],
                         "expected_turns": expected, "category": category, "turns": turns})
    supplied_summary = {s["model"]: s for s in report.get("summary", [])}
    models = []
    for index, model_id in enumerate(planned_models):
        model_sessions = [session for session in sessions if session["model"] == model_id]
        turns = [turn for session in model_sessions for turn in session["turns"]]
        successes = [turn for turn in turns if turn["status"] == "completed"]
        cost_values = [turn["usage"].get("cost_usd") for turn in turns]
        observed_costs = [value for value in cost_values if isinstance(value, (int, float))]
        budget_requests = [request for turn in turns for request in turn["budget_requests"]]
        current_ledger = [request for request in report.get("request_budget_ledger", [])
                          if request.get("model") == model_id and request.get("phase", "current_run") == "current_run"]
        if current_ledger:
            budget_requests = current_ledger
        summary = supplied_summary.get(model_id, {})
        reviewed = review_models.get(model_id)
        reviewed_turns = [turn for turn in turns if turn["review"]]
        score = reviewed.get("quality_score_percent") if reviewed else None
        if score is None and reviewed and "quality_score_percent" not in reviewed and reviewed_turns and expected_per_model:
            score = 100 * sum(turn["review"].get("score", 0) for turn in reviewed_turns) / (2 * expected_per_model)
        actual = summary.get("actual_reported_cost_usd", sum(observed_costs) if observed_costs else None)
        if budget_requests:
            reported = [r.get("reported_total_cost_usd") for r in budget_requests]
            actual = sum(value for value in reported if isinstance(value, (int, float))) if any(isinstance(value, (int, float)) for value in reported) else None
        # These are deliberately called list-price accounting, not invoice splits.
        input_list = summary.get("input_cost_at_list_usd")
        output_list = summary.get("output_cost_at_list_usd")
        input_debit = summary.get("conservative_input_debit_usd")
        if budget_requests:
            input_list = sum(r.get("known_input_at_list_usd", 0) or 0 for r in budget_requests) if input_list is None else input_list
            input_debit = sum(r.get("input_debit_usd", 0) for r in budget_requests) if input_debit is None else input_debit
            output_list = sum(r.get("output_cost_at_list_usd", 0) or 0 for r in budget_requests) if output_list is None else output_list
        models.append({"id": model_id, "name": NAMES.get(model_id, model_id.split("/", 1)[-1]),
                       "provider": model_id.split("/", 1)[0], "color_index": index,
                       "sessions": len(model_sessions), "attempted": len(turns), "expected": expected_per_model,
                       "completed": len(successes), "quality_score": score,
                       "correct": sum(t["category"] == "correct" for t in turns),
                       "partial": sum(t["category"] == "partial" for t in turns),
                       "incorrect": sum(t["category"] == "incorrect" for t in turns),
                       "failure": sum(t["category"] == "failure" for t in turns),
                       "failure_causes": {cause: sum(t["failure_cause"] == cause for t in turns)
                                          for cause in FAILURE_CAUSES},
                       "unreviewed": sum(t["category"] == "unreviewed" for t in turns),
                       "not_attempted": max(0, expected_per_model - len(turns)),
                       "correct_cases": sum(s["category"] == "correct" for s in model_sessions),
                       "median_success_seconds": median([t["timing"].get("full_answer_seconds") for t in successes]),
                       "median_all_seconds": median([t["timing"].get("full_answer_seconds") for t in turns]),
                       "actual_reported_cost": actual, "costs_missing": sum(value is None for value in cost_values),
                       "input_cost_at_list": input_list, "output_cost_at_list": output_list,
                       "input_debit": input_debit,
                       "uncertain_input_reservations": sum(r.get("input_debit_usd", 0) or 0 for r in budget_requests if r.get("uncertain")),
                       "uncertain_requests": summary.get("uncertain_requests", sum(bool(r.get("uncertain")) for r in budget_requests)),
                       "input_tokens": (sum(r.get("billed_input_tokens") or 0 for r in budget_requests)
                                        if budget_requests else sum(t["usage"].get("input_tokens") or 0 for t in turns)),
                       "output_tokens": (sum(r.get("output_tokens") or 0 for r in budget_requests)
                                         if budget_requests else sum(t["usage"].get("output_tokens") or 0 for t in turns)),
                       "prices": protocol.get("prices", {}).get(model_id, {})})
    data = {"title": "Benchmark SQL + RAG", "generated_utc": datetime.now(timezone.utc).isoformat(),
            "started_utc": report.get("started_utc"), "finished_utc": report.get("finished_utc"),
            "status": report.get("status", "unknown"), "stage": report.get("stage"), "warnings": warnings,
            "report_sha256": report_sha, "review_attached": review is not None,
            "failure_cause_labels": FAILURE_CAUSES,
            "reviewer": (review or {}).get("reviewer"), "models": models, "cases": cases, "sessions": sessions,
            "expected_sessions": len(planned_models) * len(cases), "expected_turns": len(planned_models) * expected_per_model,
            "protocol": protocol, "input_budget": report.get("input_budget", {}),
            "current_input_budget": report.get("current_input_budget", report.get("input_budget", {})),
            "prior_input_budget": report.get("prior_input_budget", {}),
            "request_budget_ledger": report.get("request_budget_ledger", []),
            "embedding_warmup_seconds": report.get("embedding_warmup_seconds"),
            "actual_reported_cost_usd": report.get("actual_reported_cost_usd"), "article": ARTICLE}
    return data


def _session_seconds(session):
    """Compare entire cases only when every expected turn was finalized."""
    if not session or len(session["turns"]) != session["expected_turns"]:
        return None
    if not all(turn["status"] == "completed" for turn in session["turns"]):
        return None
    timings = [turn["timing"].get("full_answer_seconds") for turn in session["turns"]]
    if not all(isinstance(value, (int, float)) for value in timings):
        return None
    return sum(timings)


def compare_passes(before, after):
    """Match actual observations; an absent review never creates a quality delta."""
    ranks = {"failure": 0, "incorrect": 0, "partial": 1, "correct": 2}
    case_ids = [case["id"] for case in before["cases"] if any(c["id"] == case["id"] for c in after["cases"])]
    sessions_before = {(s["model"], s["case_id"]): s for s in before["sessions"]}
    sessions_after = {(s["model"], s["case_id"]): s for s in after["sessions"]}
    models_before = {model["id"]: model for model in before["models"]}
    models_after = {model["id"]: model for model in after["models"]}
    warnings = []
    if set(models_before) != set(models_after):
        warnings.append("Les deux passes ne contiennent pas exactement les mêmes modèles ; seules les observations communes sont appariées.")
    if {c["id"] for c in before["cases"]} != {c["id"] for c in after["cases"]}:
        warnings.append("Les panneaux de questions diffèrent ; seuls les cas communs sont comparés.")
    if before["protocol"].get("source_sha256") != after["protocol"].get("source_sha256"):
        warnings.append("L’empreinte de la base diffère entre les passes.")
    models = []
    for model_id, old in models_before.items():
        new = models_after.get(model_id)
        if new is None:
            continue
        cases, old_times, new_times = [], [], []
        for case_id in case_ids:
            left, right = sessions_before.get((model_id, case_id)), sessions_after.get((model_id, case_id))
            old_category, new_category = (left or {}).get("category", "not_started"), (right or {}).get("category", "not_started")
            # Incorrect answers and execution failures both earn zero quality points.
            delta = ranks[new_category] - ranks[old_category] if old_category in ranks and new_category in ranks else None
            change = "improved" if delta is not None and delta > 0 else "regressed" if delta is not None and delta < 0 else "unchanged" if delta == 0 else "unreviewed"
            question_match = True
            for turn in (left or {}).get("turns", []):
                other = next((t for t in (right or {}).get("turns", []) if t["turn"] == turn["turn"]), None)
                if other and turn["question"] != other["question"]:
                    question_match = False
            if not question_match:
                delta, change = None, "question_changed"
            left_time, right_time = _session_seconds(left), _session_seconds(right)
            matched = left_time is not None and right_time is not None and question_match
            if matched:
                old_times.append(left_time)
                new_times.append(right_time)
            cases.append({"id": case_id, "before_category": old_category, "after_category": new_category,
                          "change": change, "quality_delta": delta, "question_match": question_match,
                          "matched_success": matched, "before_seconds": left_time, "after_seconds": right_time,
                          "seconds_delta": right_time - left_time if matched else None})
        score_delta = (new["quality_score"] - old["quality_score"]
                       if new["quality_score"] is not None and old["quality_score"] is not None else None)
        known_delta = (new["actual_reported_cost"] - old["actual_reported_cost"]
                       if new["actual_reported_cost"] is not None and old["actual_reported_cost"] is not None else None)
        models.append({"id": model_id, "name": old["name"], "color_index": old["color_index"],
                       "before": old, "after": new, "cases": cases,
                       "correct_cases_delta": new["correct_cases"] - old["correct_cases"]
                       if before["review_attached"] and after["review_attached"] else None,
                       "quality_score_delta": score_delta,
                       "improved": sum(c["change"] == "improved" for c in cases),
                       "regressed": sum(c["change"] == "regressed" for c in cases),
                       "unchanged": sum(c["change"] == "unchanged" for c in cases),
                       "unreviewed": sum(c["change"] not in {"improved", "regressed", "unchanged"} for c in cases),
                       "matched_cases": len(old_times), "matched_before_seconds": median(old_times),
                       "matched_after_seconds": median(new_times),
                       "matched_seconds_delta": median([b - a for a, b in zip(old_times, new_times)]),
                       "known_cost_delta_usd": known_delta})
    settings = {
        "rounds_per_turn": ("Tours de modèle par question", 4),
        "tool_calls_per_turn": ("Appels d’outils par question", 8),
        "timeout_per_turn_seconds": ("Délai par tour (secondes)", 30),
        "max_tool_result_chars": ("Caractères de résultats d’outils", 32000),
        "max_output_tokens": ("Tokens de sortie par appel", 1200),
        "reasoning_effort": ("Réglages de raisonnement", "none"),
    }
    settings_changes = [{"label": label, "before": before["protocol"].get(key, default),
                         "after": after["protocol"].get(key, default)}
                        for key, (label, default) in settings.items()
                        if before["protocol"].get(key, default) != after["protocol"].get(key, default)]
    return {"models": models, "case_ids": case_ids, "warnings": warnings,
            "settings_changes": settings_changes,
            "pipeline_changes": after["protocol"].get("pipeline_changes", []),
            "same_source": before["protocol"].get("source_sha256") == after["protocol"].get("source_sha256"),
            "all_observed_questions_match": all(c["question_match"] for m in models for c in m["cases"])}


TEMPLATE = r'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>SQL + RAG · Benchmark des modèles</title>
<style>
:root{--ink:#183335;--muted:#617476;--paper:#f7f8f4;--white:#fff;--line:#dce4df;--teal:#09675f;--mint:#e1f2e9;--gold:#c79122;--pink:#b64654;--blue:#6178ac;--shadow:0 14px 40px #1c423409;--radius:18px;font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:var(--paper);font-size:15px;line-height:1.55}
*{box-sizing:border-box}body{margin:0}button,input,select{font:inherit}button,a,input,select,summary{touch-action:manipulation}button{cursor:pointer}button:focus-visible,a:focus-visible,input:focus-visible,summary:focus-visible,svg [tabindex]:focus-visible{outline:3px solid #259581;outline-offset:4px}a{color:var(--teal);text-underline-offset:3px}button{color:inherit}h1,h2,h3,p{margin:0}h1{font-size:clamp(2rem,4vw,3.7rem);font-weight:650;letter-spacing:-.055em;line-height:1.08;max-width:900px}h2{font-size:1.45rem;letter-spacing:-.035em;line-height:1.25}h3{font-size:1rem;letter-spacing:-.015em}p+p{margin-top:12px}.muted{color:var(--muted)}.small{font-size:.82rem}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.wrap{max-width:1430px;margin:auto;padding:0 36px}.topbar{border-bottom:1px solid var(--line);background:#fbfcf9;position:sticky;top:0;z-index:5}.topbar>.wrap{display:flex;align-items:center;justify-content:space-between;gap:20px;padding-top:15px;padding-bottom:15px}.brand{display:flex;align-items:center;gap:10px;font-size:.85rem;font-weight:650}.brand-mark{display:grid;place-items:center;width:32px;height:32px;border-radius:9px;background:var(--ink);color:white;letter-spacing:-2px;font-size:13px;font-weight:500}.top-actions{display:flex;gap:8px}.button{border:1px solid var(--line);border-radius:8px;background:white;padding:7px 12px;font-size:.79rem;text-decoration:none;white-space:nowrap;display:inline-flex;align-items:center;justify-content:center;gap:5px}.button:hover{background:var(--mint);border-color:#a5cbc0}.hero{padding-top:43px;padding-bottom:27px}.eyebrow{font-size:.7rem;font-weight:750;letter-spacing:.14em;text-transform:uppercase;color:var(--teal);display:flex;align-items:center;gap:14px;margin-bottom:16px}.status-pill{font-size:.66rem;font-weight:650;letter-spacing:.045em;text-transform:uppercase;display:inline-flex;align-items:center;gap:6px;background:var(--mint);padding:4px 9px;border-radius:50px;color:var(--teal)}.status-dot{height:6px;width:6px;border-radius:50%;background:currentColor}.hero-desc{color:var(--muted);max-width:800px;margin-top:17px;font-size:1rem}.hero-meta{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-top:20px;font-size:.74rem;color:var(--muted)}.meta-tag{border:1px solid var(--line);border-radius:6px;padding:4px 9px}.nav{display:flex;gap:24px;border-bottom:1px solid var(--line);margin-bottom:27px;overflow:auto}.nav button{background:transparent;border:0;white-space:nowrap;padding:14px 0;font-size:.88rem;color:var(--muted);border-bottom:3px solid transparent}.nav button[aria-selected=true]{color:var(--ink);font-weight:700;border-color:var(--teal)}.tab[hidden]{display:none}.tab{padding-bottom:48px}.notice{padding:13px 18px;background:#fff3d8;border:1px solid #ecd49d;border-radius:10px;margin-bottom:20px;font-size:.83rem;color:#6e551d}.notice:empty{display:none}.filterbar{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-bottom:20px}.filterbar details{position:relative}.filterbar summary{cursor:pointer;list-style:none;border:1px solid var(--line);padding:7px 11px;border-radius:8px;background:white;font-size:.8rem}.filterbar summary::-webkit-details-marker{display:none}.filter-menu{position:absolute;right:0;top:43px;z-index:4;width:290px;background:white;padding:14px;border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}.filter-menu label{display:flex;align-items:center;gap:9px;padding:5px 0;font-size:.83rem}.filter-menu input{accent-color:var(--teal)}.filter-menu .button{margin-top:9px;width:100%}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;flex:0 0 8px;background:var(--teal)}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}.card{background:white;border:1px solid var(--line);border-radius:var(--radius);padding:21px;box-shadow:var(--shadow)}.stat-label{font-size:.75rem;color:var(--muted);margin-bottom:8px}.stat-value{font-size:1.95rem;font-weight:650;letter-spacing:-.055em;line-height:1.2}.stat-note{font-size:.72rem;color:var(--muted);margin-top:7px;max-width:260px}.panel{background:white;border:1px solid var(--line);border-radius:var(--radius);padding:25px;margin-bottom:23px;box-shadow:var(--shadow)}.panel-head{display:flex;align-items:flex-start;justify-content:space-between;gap:25px;margin-bottom:21px}.panel-head p{color:var(--muted);font-size:.8rem;margin-top:6px;max-width:800px}.caption{font-size:.74rem;color:var(--muted);margin-top:14px}.plot-layout{display:grid;grid-template-columns:minmax(0,1fr) 245px;gap:22px}.chart{display:block;width:100%;height:auto;min-height:280px}.legend{display:flex;flex-direction:column;gap:13px;justify-content:center}.legend-item{display:flex;gap:9px;font-size:.8rem;align-items:flex-start}.legend-item small{font-size:.72rem;display:block;color:var(--muted)}.insight{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:24px}.insight-box{background:var(--mint);border-radius:13px;padding:18px 21px}.insight-box:last-child{background:#eff1f8}.insight-box .small{color:var(--muted);margin-top:5px}.table-wrap{overflow:auto}.ranking{border-collapse:collapse;width:100%;font-size:.82rem}.ranking th{text-align:left;color:var(--muted);font-size:.68rem;letter-spacing:.035em;text-transform:uppercase;padding:0 12px 12px;border-bottom:1px solid var(--line);white-space:nowrap}.ranking th:first-child,.ranking td:first-child{padding-left:0}.ranking td{padding:17px 12px;border-bottom:1px solid #edf0ec;white-space:nowrap;vertical-align:middle}.ranking tr:last-child td{border-bottom:0}.ranking th button{background:none;border:0;color:inherit;text-align:inherit;font:inherit;padding:0;letter-spacing:inherit;text-transform:inherit}.model-name{display:flex;align-items:center;gap:9px;font-weight:650}.model-id{display:block;color:var(--muted);font-size:.65rem;margin-top:3px;font-weight:400}.score{font-size:1rem;font-weight:700}.score-track{display:inline-block;width:52px;height:4px;border-radius:4px;background:#e3ebe6;vertical-align:middle;margin-left:8px;overflow:hidden}.score-fill{display:block;height:100%;background:var(--teal)}.failure-count{color:var(--pink);font-size:.7rem}.empty{padding:45px;text-align:center;color:var(--muted);font-size:.86rem}.section-toolbar{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-bottom:20px}.search{width:min(440px,100%);border:1px solid var(--line);border-radius:9px;padding:10px 12px;background:white;outline-offset:0}.key{display:flex;gap:14px;flex-wrap:wrap;font-size:.75rem;color:var(--muted);margin-bottom:18px}.key span{display:inline-flex;gap:6px;align-items:center}.state-dot{width:8px;height:8px;border-radius:50%;display:inline-block;background:#c1c9c3}.state-dot.correct{background:var(--teal)}.state-dot.partial{background:var(--gold)}.state-dot.incorrect{background:var(--pink)}.state-dot.failure{background:#768080}.state-dot.unreviewed{background:#b2bdcd}.matrix{width:100%;border-collapse:separate;border-spacing:0;font-size:.75rem}.matrix th{padding:10px 9px;border-bottom:1px solid var(--line);text-align:center;min-width:105px;font-size:.69rem;white-space:nowrap;color:var(--muted)}.matrix th:first-child{min-width:290px;text-align:left;max-width:440px;width:32%}.matrix td{padding:14px 9px;border-bottom:1px solid #edf0ec;text-align:center}.matrix td:first-child{text-align:left;padding-left:0}.matrix th:first-child{padding-left:0}.question-name{font-size:.8rem;line-height:1.5;font-weight:550}.question-kind{font-size:.65rem;color:var(--muted);margin-bottom:3px}.matrix-button{border:1px solid transparent;background:#f1f4f1;border-radius:8px;padding:9px 9px;min-width:85px;font-size:.68rem;color:var(--muted);width:100%}.matrix-button.correct{background:#e3f3e9;color:var(--teal);border-color:#cae4d5}.matrix-button.partial{background:#fff1d4;color:#8b641b;border-color:#f2dfb6}.matrix-button.incorrect{background:#fae9eb;color:#a13647;border-color:#ebced4}.matrix-button.failure{background:#eff0ef;color:#64716d;border-color:#e0e4e0}.matrix-button.unreviewed{background:#edf0f8;color:#667696;border-color:#dce2ef}.matrix-button:hover{filter:brightness(.97);outline:2px solid currentColor;outline-offset:2px}.matrix-button span{display:block;font-size:.6rem;margin-top:3px;opacity:.9}.cost-bars{display:flex;flex-direction:column;gap:17px}.cost-row{display:grid;grid-template-columns:195px 1fr 125px;gap:17px;align-items:center;font-size:.78rem}.bar-track{height:24px;background:#f0f3ee;border-radius:5px;display:flex;overflow:hidden}.bar-segment{height:100%;min-width:1px}.bar-segment.input{background:#1b8474}.bar-segment.output{background:#89c9b5}.bar-segment.uncertain{background:repeating-linear-gradient(135deg,#e7c786,#e7c786 4px,#f7eacb 4px,#f7eacb 8px)}.cost-number{text-align:right;font-variant-numeric:tabular-nums}.budget-line{display:flex;justify-content:space-between;font-size:.85rem;margin-bottom:11px}.budget-track{height:9px;background:#e4ebe5;border-radius:12px;overflow:hidden}.budget-fill{height:100%;background:var(--teal);min-width:0;max-width:100%}.method-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px}.method-list{padding-left:20px;font-size:.85rem;color:var(--muted)}.method-list li{margin-top:10px}.method-grid h3{margin-bottom:11px}.definition{font-size:.83rem;color:var(--muted)}.hash{word-break:break-all;font-size:.7rem;border:1px solid var(--line);background:#f7f9f6;padding:10px 12px;border-radius:8px;margin-top:8px}.method-chip{display:inline-block;padding:4px 8px;border:1px solid var(--line);border-radius:5px;font-size:.72rem;margin:3px}.footer{padding:22px 0 35px;border-top:1px solid var(--line);font-size:.7rem;color:var(--muted);display:flex;justify-content:space-between;gap:20px}.footer a{color:inherit}dialog{width:min(1060px,calc(100% - 36px));max-height:90vh;border:1px solid var(--line);border-radius:19px;padding:0;color:var(--ink);background:var(--paper);box-shadow:0 30px 90px #0a251530}dialog::backdrop{background:#102a3475;backdrop-filter:blur(4px)}.dialog-head{padding:23px 25px;background:#fff;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;position:sticky;top:0;z-index:2}.dialog-head .muted{font-size:.76rem;margin-top:5px}.close-button{border:1px solid var(--line);background:white;border-radius:8px;width:34px;height:34px;flex:0 0 34px;font-size:1.2rem}.dialog-body{padding:25px}.turn-card{background:white;border:1px solid var(--line);border-radius:13px;padding:21px;margin-bottom:17px}.turn-head{display:flex;gap:12px;justify-content:space-between;align-items:center;margin-bottom:13px}.badge{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);padding:4px 8px;border-radius:6px;white-space:nowrap;font-size:.69rem}.badge.correct{background:var(--mint);color:var(--teal)}.badge.partial{background:#fff0d2;color:#8b641b}.badge.incorrect{background:#fae9eb;color:#a13647}.badge.failure{background:#eff0ef;color:#64716d}.badge.unreviewed{background:#edf0f8;color:#667696}.answer{font-size:.86rem;white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f9f5;border:1px solid #e6ece4;border-radius:9px;padding:15px 17px;margin:13px 0;font-family:inherit;line-height:1.65}.review-note{font-size:.8rem;border-left:3px solid var(--teal);padding:9px 12px;margin:13px 0;background:#f4f8f3}.turn-metrics{display:flex;gap:17px;flex-wrap:wrap;font-size:.72rem;color:var(--muted);margin-top:13px}.source-list{font-size:.77rem;padding-left:20px}.source-list li{margin:10px 0}.source-list .mono{display:block;font-size:.65rem;color:var(--muted);overflow-wrap:anywhere}.evidence-text{white-space:pre-wrap;font-size:.74rem;color:var(--muted);margin-top:5px}.inspect{margin-top:15px;border-top:1px solid var(--line);padding-top:12px}.inspect summary{cursor:pointer;font-size:.75rem;color:var(--teal)}.inspect pre{font-size:.67rem;white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f3;border-radius:8px;padding:14px;max-height:450px;overflow:auto}.checks{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.check{font-size:.66rem;border:1px solid var(--line);padding:4px 7px;border-radius:5px}.check.yes{color:var(--teal);background:#f2faf5}.check.no{color:var(--pink);background:#fef5f5}.screen-reader{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}noscript{display:block;padding:30px;background:#fff1d4}
.failure-table th,.failure-table td{white-space:normal;text-align:center;min-width:78px}.failure-table th:first-child,.failure-table td:first-child{text-align:left;min-width:210px}.failure-table th{font-size:.64rem;text-transform:none}.failure-table td{padding-top:11px;padding-bottom:11px;font-size:.76rem}.failure-total{font-weight:700}.failure-heat{display:inline-block;min-width:26px;padding:3px 5px;border-radius:5px;color:#854746}.failure-zero{color:#b7c2bb}
.pass-picker{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.pass-picker button[aria-pressed=true]{background:var(--ink);color:white;border-color:var(--ink)}.compare-stats .stat-value{font-size:1.7rem}.gain{color:var(--teal)}.loss{color:var(--pink)}.neutral{color:var(--muted)}.delta{display:inline-block;font-weight:700;white-space:nowrap}.compare-table td{vertical-align:top}.compare-table .model-id{max-width:290px;white-space:normal}.compare-table th button{cursor:pointer}.comparison-grid{display:grid;grid-template-columns:1fr 1fr;gap:17px}.comparison-grid .turn-card{min-width:0;margin:0}.comparison-grid .answer{min-height:100px}.comparison-grid pre{white-space:pre-wrap}.comparison-turn{margin-bottom:26px}.comparison-turn>h3{margin-bottom:11px}.comparison-turn .review-note{border-left-width:2px}.receipt-diff{border:1px solid var(--line);border-radius:10px;padding:12px 16px;background:white;margin-bottom:15px}.case-delta{display:flex;gap:7px;align-items:center;justify-content:center;flex-wrap:wrap}.case-delta .small{width:100%}.matrix-button.improved{background:#e3f3e9;color:var(--teal);border-color:#cae4d5}.matrix-button.regressed{background:#fae9eb;color:#a13647;border-color:#ebced4}.protocol-diff{padding-left:20px;font-size:.82rem;color:var(--muted)}.protocol-diff li{margin:8px 0}.paired-note{background:#eff1f8;border-radius:10px;padding:13px 16px;font-size:.8rem;color:#4d5f88;margin-bottom:20px}.compare-settings{font-size:.79rem;border-collapse:collapse;width:100%}.compare-settings td,.compare-settings th{border-bottom:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top}.compare-settings td{white-space:pre-wrap;overflow-wrap:anywhere;max-width:400px}.compare-settings td:first-child{font-weight:600;min-width:160px}.comparison-grid .turn-head{align-items:flex-start;gap:8px}.comparison-grid .turn-metrics{gap:8px 14px}.compare-chart{min-height:280px}.pass-label{color:var(--muted);font-size:.7rem;font-weight:600;letter-spacing:.03em;text-transform:uppercase;margin-bottom:8px}
@media(max-width:800px){.comparison-grid{grid-template-columns:1fr}.filterbar{flex-wrap:wrap}.pass-picker{width:100%;order:-1}.compare-settings td{font-size:.7rem;padding:8px}.compare-stats .stat-value{font-size:1.45rem}}
@media(max-width:1000px){.wrap{padding:0 22px}.cards{grid-template-columns:repeat(2,1fr)}.plot-layout{grid-template-columns:1fr}.legend{display:grid;grid-template-columns:repeat(2,1fr)}.cost-row{grid-template-columns:170px 1fr 95px}.method-grid{grid-template-columns:1fr}.panel{padding:22px}.hero{padding-top:30px}}
@media(max-width:600px){.wrap{padding:0 16px}.topbar>.wrap{gap:8px}.top-actions .button{font-size:.7rem;padding:6px 8px}.brand span:last-child{display:none}.hero{padding-top:25px}.hero-desc{font-size:.9rem}.cards{gap:9px}.card{padding:16px}.stat-value{font-size:1.6rem}.stat-note{font-size:.65rem}.nav{gap:20px}.nav button{font-size:.8rem}.panel{padding:18px 15px;border-radius:13px}.panel-head{gap:12px}.panel-head h2{font-size:1.25rem}.plot-layout{gap:5px}.legend{grid-template-columns:1fr 1fr;gap:10px}.legend-item{font-size:.7rem}.insight{grid-template-columns:1fr;gap:10px}.filterbar{gap:8px;align-items:flex-start}.filterbar>.muted{font-size:.7rem;max-width:55%}.cost-row{grid-template-columns:1fr 80px;gap:5px 12px}.cost-row>.bar-track{grid-row:2;grid-column:1/-1}.cost-row>.cost-number{grid-column:2;grid-row:1}.section-toolbar{align-items:stretch;flex-direction:column}.footer{display:block}.footer>div+div{margin-top:8px}.dialog-head,.dialog-body{padding:17px}.dialog-head h2{font-size:1.15rem}.turn-card{padding:15px}.turn-head{align-items:flex-start}.chart{min-height:210px}.filter-menu{width:270px}.meta-tag{font-size:.65rem}}
@media print{body{background:white;font-size:10pt}.topbar{position:static}.top-actions,.nav,.filterbar,.section-toolbar,.button{display:none!important}.wrap{max-width:none;padding:0 10px}.hero{padding-top:18px}.hero h1{font-size:28pt}.tab[hidden]{display:block}.tab{padding-bottom:8px}.panel,.card,.insight-box{box-shadow:none;break-inside:avoid;border-radius:8px}.panel{padding:15px;margin-bottom:15px}.cards{gap:10px}.plot-layout{grid-template-columns:1fr 210px}.legend{display:flex;font-size:8pt}.table-wrap{overflow:visible}.ranking,.matrix{font-size:8pt}.ranking td{padding:9px 5px}.ranking th{padding:0 5px 8px}.matrix th{min-width:60px;font-size:7pt;white-space:normal}.matrix th:first-child{min-width:200px}.matrix td{padding:8px 4px}.matrix-button{font-size:7pt;padding:6px 3px;min-width:45px}.matrix-button span{font-size:6pt}.method-grid{grid-template-columns:1fr 1fr}.footer{font-size:7pt}.cost-row{font-size:8pt}dialog{display:none!important}a{text-decoration:none;color:inherit}.notice{font-size:8pt}.stat-value{font-size:20pt}.insight{grid-template-columns:1fr 1fr}.chart{min-height:0}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
</style>
</head>
<body>
<header class="topbar"><div class="wrap"><div class="brand"><span class="brand-mark" aria-hidden="true">B/</span><span>BIKEFINDER · LAB</span></div><div class="top-actions"><button class="button" id="export-csv">Exporter CSV</button><button class="button" id="export-json">Données JSON</button><button class="button" id="print-report">Imprimer</button></div></div></header>
<main class="wrap">
<div class="hero"><div class="eyebrow">SQL + RAG / OpenRouter <span class="status-pill" id="run-status"><span class="status-dot"></span><span>Résultats observés</span></span></div><h1><span id="hero-title">Le catalogue sous</span><br><span id="model-count-heading">huit</span><span id="hero-title-end"> regards.</span></h1><p class="hero-desc" id="hero-description">Les mêmes questions et la même base, avec la qualité des réponses, le temps d’attente et le coût retourné par l’API.</p><div class="hero-meta" id="hero-meta"></div></div>
<p style="margin:0 0 20px;font-size:.85rem"><a href="benchmark-finetuning.html">Annexe 01 · Fine-tuning de BGE-M3 : résultats et preuves →</a></p>
<nav class="nav" role="tablist" aria-label="Vues du benchmark"><button id="tab-comparison" role="tab" aria-selected="true" aria-controls="view-comparison" data-tab="comparison">Comparaison des passes</button><button id="tab-overview" role="tab" aria-selected="false" aria-controls="view-overview" data-tab="overview" tabindex="-1">Vue d’ensemble</button><button id="tab-questions" role="tab" aria-selected="false" aria-controls="view-questions" data-tab="questions" tabindex="-1">Questions & réponses</button><button id="tab-costs" role="tab" aria-selected="false" aria-controls="view-costs" data-tab="costs" tabindex="-1">Coûts</button><button id="tab-method" role="tab" aria-selected="false" aria-controls="view-method" data-tab="method" tabindex="-1">Méthode</button></nav>
<div class="notice" id="notice"></div>
<div class="filterbar"><p class="muted small" id="progress"></p><div class="pass-picker" id="pass-picker" role="group" aria-label="Passe affichée dans les autres onglets"></div><details id="model-filter"><summary aria-label="Choisir les modèles affichés">Filtrer les modèles <span id="filter-count"></span> ▾</summary><div class="filter-menu" id="filter-menu"></div></details></div>
<section class="tab" id="view-comparison" role="tabpanel" aria-labelledby="tab-comparison">
<div class="cards compare-stats" id="compare-stats"></div>
<p class="paired-note">Les deux passes évaluent le parcours complet : le modèle, les outils et la gestion du contexte. Les réglages ont changé ; une amélioration ne peut pas être attribuée au seul modèle. La qualité exige une relecture liée à chaque rapport.</p>
<section class="panel"><div class="panel-head"><div><h2>Les améliorations et les reculs</h2><p>Cas entièrement corrects dans chaque passe, score de relecture et coûts connus. Les temps appariés portent exclusivement sur les mêmes cas finalisés dans les deux passes.</p></div></div><div class="table-wrap"><table class="ranking compare-table"><thead><tr><th><button data-compare-sort="name">Modèle ↕</button></th><th><button data-compare-sort="correct_cases_delta">Cas corrects · P1 → P2 ↕</button></th><th><button data-compare-sort="quality_score_delta">Score · évolution ↕</button></th><th><button data-compare-sort="matched_seconds_delta">Temps apparié · évolution ↕</button></th><th><button data-compare-sort="known_cost_delta_usd">Coût connu · évolution ↕</button></th></tr></thead><tbody id="compare-ranking"></tbody></table></div><p class="caption">Le temps affiché est la somme des tours d’un cas, puis la médiane sur les cas communs finalisés. L’évolution est la médiane des différences cas par cas. Le coût connu exclut les retours manquants ; les réservations incertaines restent distinctes.</p></section>
<section class="panel"><div class="panel-head"><div><h2>Le gain de qualité, cas par cas</h2><p>Ouvrez une cellule pour confronter les réponses, les jugements et les appels d’outils. « Score inchangé » peut masquer un changement de nature de l’erreur : les deux états restent affichés.</p></div></div><div class="table-wrap"><table class="matrix" id="compare-matrix"></table></div><p class="caption">L’évolution compare le résultat du cas complet : correct = 2, partiel = 1, incorrect ou échec = 0. Un jugement manquant reste « À relire ». Q37 exige ses deux tours pour être entièrement correct.</p></section>
<section class="panel"><div class="panel-head"><div><h2>Ce qui a changé entre les passes</h2><p id="compare-source-note"></p></div></div><ul class="protocol-diff" id="pipeline-changes"></ul><div class="table-wrap"><table class="compare-settings"><thead><tr><th>Condition</th><th>Passe 1 · initiale</th><th>Passe 2 · améliorée</th></tr></thead><tbody id="settings-changes"></tbody></table></div><p class="caption">Une seule exécution par cas et par passe : ces écarts décrivent les mesures observées, pas une garantie de performance générale. Les changements du routage, du cache et du service distant peuvent aussi modifier les temps et les coûts.</p></section>
<section class="panel"><div class="panel-head"><div><h2>Chaque passe conserve son budget</h2><p>Le nouveau plafond de 2 $ porte uniquement sur l’entrée de la passe 2. Les dépenses de la passe 1 ne lui sont pas imputées.</p></div></div><div class="table-wrap"><table class="ranking"><thead><tr><th>Passe</th><th>Sessions observées</th><th>Tours tentés / prévus</th><th>Coût panel connu</th><th>Entrée comptée</th><th>Réservation incertaine</th></tr></thead><tbody id="compare-budgets"></tbody></table></div><p class="caption" id="compare-budget-note"></p></section>
</section>
<section class="tab" id="view-overview" role="tabpanel" aria-labelledby="tab-overview">
<div class="cards" id="stats"></div><div class="insight" id="insights"></div>
<section class="panel"><div class="panel-head"><div><h2>Qualité et temps d’attente</h2><p>Plus haut : meilleur score de relecture. Plus à gauche : réponse finale plus rapide. Chaque bulle correspond à un modèle.</p></div></div><div class="plot-layout"><svg class="chart" id="scatter" viewBox="0 0 820 380" role="img" aria-labelledby="scatter-title scatter-desc"><title id="scatter-title">Score qualité et temps médian des réponses finalisées</title><desc id="scatter-desc">Les points ne sont affichés que lorsqu’une relecture et une réponse finalisée sont disponibles. Le rayon indique le coût total retourné pour ce modèle.</desc></svg><div class="legend" id="scatter-legend"></div></div><p class="caption">Temps = médiane des réponses finalisées avec un format et des références valides, même si la relecture les juge incomplètes ou fausses. Les délais dépassés sont comptés séparément. Bulle = coût total reçu du modèle, avec les éventuels frais inconnus signalés dans l’onglet Coûts.</p></section>
<section class="panel"><div class="panel-head"><div><h2>Les huit modèles, côte à côte</h2><p>Un score de qualité ne suffit pas : lire aussi les réponses entièrement correctes, les échecs et les cas détaillés. Cliquez sur un titre de colonne pour trier.</p></div></div><div class="table-wrap"><table class="ranking"><thead><tr><th aria-sort="none"><button data-sort="name">Modèle ↕</button></th><th aria-sort="descending"><button data-sort="quality_score">Score qualité ↕</button></th><th aria-sort="none"><button data-sort="correct">Entièrement correctes ↕</button></th><th aria-sort="none"><button data-sort="completed">Finalisées ↕</button></th><th aria-sort="none"><button data-sort="median_success_seconds">Temps médian ↕</button></th><th aria-sort="none"><button data-sort="actual_reported_cost">Coût reçu ↕</button></th></tr></thead><tbody id="ranking-body"></tbody></table></div><p class="caption">Score : 2 points pour une réponse correcte et complète, 1 pour une réponse partielle, 0 pour une réponse fausse, un échec ou un tour attendu non exécuté ; divisé par le maximum prévu. Une réponse finalisée n’est pas automatiquement correcte.</p></section>
<section class="panel"><div class="panel-head"><div><h2>Ce qui bloque les réponses</h2><p id="failure-summary"></p></div></div><div class="table-wrap"><table class="ranking failure-table" id="failure-table"></table></div><p class="caption" id="failure-protocol-caption"></p></section>
</section>
<section class="tab" id="view-questions" role="tabpanel" aria-labelledby="tab-questions" hidden>
<div class="section-toolbar"><div><h2>Voir les réponses et leurs preuves</h2><p class="muted small">Cliquez sur une cellule pour ouvrir la réponse, la relecture et les sources.</p></div><input class="search" id="question-search" type="search" placeholder="Chercher une question, une moto, un identifiant…" aria-label="Filtrer les questions"></div>
<div class="key"><span><i class="state-dot correct"></i>Correct et complet</span><span><i class="state-dot partial"></i>Partiel</span><span><i class="state-dot incorrect"></i>Incorrect</span><span><i class="state-dot failure"></i>Échec</span><span><i class="state-dot unreviewed"></i>À relire</span></div>
<section class="panel"><div class="table-wrap"><table class="matrix" id="matrix"></table></div><p class="caption">La conversation Q37 comporte deux tours. Sa cellule est entièrement correcte seulement si les deux le sont. Une cellule « Non lancé » indique une absence de mesure.</p></section>
</section>
<section class="tab" id="view-costs" role="tabpanel" aria-labelledby="tab-costs" hidden>
<div class="cards" id="cost-stats"></div><section class="panel"><div class="panel-head"><div><h2>Le plafond porte sur l’entrée</h2><p>Les sorties sont suivies séparément. L’entrée est protégée par une borne tarifaire de routage et une marge de cache ; une requête sans retour conserve sa réservation.</p></div></div><div id="budget-meter"></div><p class="caption" id="budget-caption"></p><p class="caption" id="prior-caption"></p></section>
<section class="panel"><div class="panel-head"><div><h2>Répartition du coût par modèle</h2><p>Entrées et sorties au tarif public enregistré. Le montant reçu de l’API peut être inférieur, notamment grâce à son cache ; il ne constitue pas une facture complète lorsqu’un retour manque.</p></div></div><div class="key"><span><i class="dot" style="background:#1b8474"></i>Entrées connues au tarif public</span><span><i class="dot" style="background:#89c9b5"></i>Sorties au tarif public</span><span><i class="dot" style="background:#e7c786"></i>Réservation d’entrée incertaine</span></div><div class="cost-bars" id="cost-bars"></div><p class="caption">Les réservations incertaines ne sont pas des dépenses confirmées. Elles restent comptées pour garantir le plafond malgré un éventuel traitement facturé après un délai dépassé.</p></section>
<section class="panel"><div class="panel-head"><div><h2>Tarifs figés au lancement</h2><p>Dollars américains pour un million de tokens. Les variantes gratuites, batch et alias ne sont pas confondues avec les identifiants testés.</p></div></div><div class="table-wrap"><table class="ranking"><thead><tr><th>Modèle</th><th>Entrée / million</th><th>Sortie / million</th><th>Tokens entrée reçus</th><th>Tokens sortie reçus</th><th>Retours incertains</th></tr></thead><tbody id="price-body"></tbody></table></div><p class="caption" id="price-note"></p></section>
</section>
<section class="tab" id="view-method" role="tabpanel" aria-labelledby="tab-method" hidden>
<section class="panel"><div class="panel-head"><div><h2>Ce que cette comparaison mesure</h2><p>Un petit panel de développement, avec une exécution par cas dans la comparaison finale. Il aide à choisir les candidats d’une évaluation plus large.</p></div></div><div class="method-grid"><div><h3>Le même parcours pour chacun</h3><ol class="method-list"><li>Le modèle reçoit la question, le même prompt et les définitions des outils.</li><li>Il choisit ses appels aux six outils de notre catalogue : résolution de modèles, SQL contrôlé, fiches, comparaison et passages.</li><li>Les résultats nécessaires lui sont envoyés, avec leurs identités, millésimes et références sources.</li><li>Il rend une réponse finale structurée. Le format et l’existence des références sont vérifiés ; la relecture juge ensuite les faits et leur couverture.</li></ol></div><div><h3>Les conditions communes</h3><div id="method-chips"></div><p class="definition" id="reasoning-settings" style="margin-top:13px"></p><p class="definition" style="margin-top:13px">La recherche hybride utilise BGE-M3 et BM25 sur un index figé. Le filtrage des modèles et millésimes intervient avant le classement. Une recherche littérale paginée peut couvrir toutes les fiches d’un périmètre.</p><p class="definition" style="margin-top:13px">L’ordre est mélangé avec une graine fixe. Une session neuve est ouverte pour chaque question ; les tours d’une même conversation partagent leur historique.</p></div></div></section>
<section class="panel"><div class="method-grid"><div><h3>Lire les indicateurs</h3><ul class="method-list"><li><strong>Qualité :</strong> exactitude, bonnes identités et années, couverture de la demande, appui des affirmations et prudence face aux absences.</li><li><strong>Rapidité :</strong> temps complet côté client, outils inclus. La médiane des réponses finalisées exclut les échecs. Aucun temps de premier token n’est inventé : les appels ne sont pas diffusés en continu.</li><li><strong>Coût :</strong> coût total retourné par l’API et comptabilité conservatrice de l’entrée sont distincts.</li><li><strong>Conversation :</strong> la seconde question dépend du résultat de la première ; elle ne reçoit pas la réponse attendue.</li></ul></div><div><h3>Portée des résultats</h3><p class="definition">Le panel et les références ont été créés pour ce projet. Seuls huit cas de développement sont exécutés ici ; l’évaluation complète prévue sur quarante cas avec trois répétitions n’a pas été réalisée. Une seule exécution par cas ne mesure ni la variabilité ni une précision générale sur tout le catalogue. Les contrôles automatiques de nombres et de références servent de vérification minimale. Le score vient d’une relecture par des agents assistants qui consultent les réponses et les preuves livrées. Les identifiants des modèles étaient visibles : cette relecture n’est ni humaine ni menée en aveugle.</p><p class="definition" style="margin-top:13px">Une donnée absente doit rester absente. La mention d’une technologie dans notre base ne certifie pas sa date de lancement. Le périmètre du catalogue et les variantes comptées doivent rester explicites.</p><p class="definition" id="run-history" style="margin-top:13px"></p><p class="definition" style="margin-top:13px">Les modèles sont appelés via OpenRouter, avec un identifiant explicite et sans repli vers un autre modèle. Un refus d’outil, un problème de format ou un délai dépassé reste enregistré comme échec.</p></div></div></section>
<section class="panel"><h3>Un document HTML autonome</h3><p class="definition" style="margin-top:10px">Ce rapport reprend les principes de <a href="https://claude.dev/blog/using-claude-code-the-unreasonable-effectiveness-of-html/" target="_blank" rel="noopener noreferrer">l’article sur l’efficacité du HTML</a> : un fichier unique, une navigation simple, des tableaux triables, un graphique SVG et des détails inspectables. Il s’ouvre hors ligne, s’imprime et exporte ses données. Il ne charge aucune police, bibliothèque ou donnée distante.</p><div style="margin-top:18px"><h3>Traçabilité</h3><p class="small muted" style="margin-top:8px">Empreinte de la base</p><div class="hash mono" id="source-hash"></div><p class="small muted" style="margin-top:12px">Empreinte du rapport observé</p><div class="hash mono" id="report-hash"></div><p class="small muted" style="margin-top:12px">Empreinte du protocole préparé</p><div class="hash mono" id="pack-hash"></div></div></section>
</section>
<footer class="footer"><div>Bikefinder · SQL + RAG · <span id="footer-date"></span></div><div>Mesures observées, sources inspectables, aucune dépendance distante.</div></footer>
</main>
<dialog id="answer-dialog" aria-labelledby="dialog-title"><div class="dialog-head"><div><h2 id="dialog-title"></h2><p class="muted" id="dialog-subtitle"></p></div><button class="close-button" id="close-dialog" aria-label="Fermer le détail">×</button></div><div class="dialog-body" id="dialog-body"></div></dialog>
<noscript>Activez JavaScript pour les filtres, les graphiques et les détails. Les données observées sont intégrées dans ce fichier, sans appel réseau.</noscript>
<script id="benchmark-data" type="application/json">__BENCHMARK_DATA__</script>
<script>
"use strict";
const bundle=JSON.parse(document.getElementById("benchmark-data").textContent);
const passes=bundle.passes||[bundle];let activePass=passes.length-1,data=passes[activePass];
const palette=["#087b68","#b56b42","#5c79b4","#ae548a","#9a9b39","#805eb0","#168b9c","#c68921"];
const labels={correct:"Correct et complet",partial:"Partiel",incorrect:"Incorrect",failure:"Échec",unreviewed:"À relire",not_started:"Non lancé",pending:"En cours"};
const selected=new Set(passes.flatMap(p=>p.models.map(m=>m.id)));let sortKey="quality_score",sortDirection=-1,compareSort="correct_cases_delta",compareDirection=-1;
const $=id=>document.getElementById(id), esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const number=new Intl.NumberFormat("fr-FR",{maximumFractionDigits:1}), int=new Intl.NumberFormat("fr-FR",{maximumFractionDigits:0});
const money=v=>v==null?"—":new Intl.NumberFormat("fr-FR",{minimumFractionDigits:v<.1?4:2,maximumFractionDigits:v<.1?4:2}).format(v)+" $";
const seconds=v=>v==null?"—":number.format(v)+" s";const pct=v=>v==null?"À relire":number.format(v)+" %";
const sum=(xs,key)=>xs.reduce((total,x)=>total+(Number.isFinite(x[key])?x[key]:0),0);
const visible=()=>data.models.filter(m=>selected.has(m.id));
const color=m=>palette[m.color_index%palette.length];
const date=v=>v?new Date(v).toLocaleString("fr-FR",{timeZone:"Europe/Paris",dateStyle:"medium",timeStyle:"short"}):"date non disponible";
const session=(model,caseId)=>data.sessions.find(s=>s.model===model&&s.case_id===caseId);
const json=v=>JSON.stringify(v,null,2);
function card(label,value,note){return `<div class="card"><div class="stat-label">${esc(label)}</div><div class="stat-value">${esc(value)}</div><div class="stat-note">${esc(note)}</div></div>`}
function activateTab(name){document.querySelectorAll("[data-tab]").forEach(b=>{const active=b.dataset.tab===name;b.setAttribute("aria-selected",active);b.tabIndex=active?0:-1});document.querySelectorAll(".tab").forEach(t=>t.hidden=t.id!=="view-"+name)}
document.querySelectorAll("[data-tab]").forEach((b,i,buttons)=>{b.addEventListener("click",()=>activateTab(b.dataset.tab));b.addEventListener("keydown",e=>{if(!["ArrowRight","ArrowLeft","Home","End"].includes(e.key))return;e.preventDefault();let next=e.key==="Home"?0:e.key==="End"?buttons.length-1:(i+(e.key==="ArrowRight"?1:-1)+buttons.length)%buttons.length;buttons[next].focus();activateTab(buttons[next].dataset.tab)})});
function download(name,text,type){const blob=new Blob([text],{type}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)}
$("export-json").addEventListener("click",()=>download("bikefinder-benchmark.json",json(bundle),"application/json"));
$("export-csv").addEventListener("click",()=>{const rows=[["passe","modele","question","tour","statut_execution","jugement","score_qualite_modele","secondes","cout_api_usd","question_texte","reponse","raison_relecture"]];passes.forEach((p,index)=>p.sessions.filter(s=>selected.has(s.model)).forEach(s=>s.turns.forEach(t=>rows.push([index+1,s.model,s.case_id,t.turn,t.status,t.category,p.models.find(m=>m.id===s.model).quality_score,t.timing.full_answer_seconds,t.usage.cost_usd,t.question,t.answer,t.review?.reason]))));const quoted=rows.map(row=>row.map(v=>'"'+((typeof v==="string"&&/^[\t\r\n ]*[=+\-@]/.test(v))?"'"+v:String(v??"")).replaceAll('"','""')+'"').join(",")).join("\r\n");download("bikefinder-benchmark.csv","\ufeff"+quoted,"text/csv;charset=utf-8")});
$("print-report").addEventListener("click",()=>window.print());
function renderHeader(){
$("model-count-heading").textContent=data.models.length===8?"huit":String(data.models.length);
$("hero-title").textContent=passes.length>1?"Deux passes,":"Le catalogue sous";
$("hero-title-end").textContent=passes.length>1?" modèles.":" regards.";
$("hero-description").textContent=passes.length>1?"La même base et les mêmes questions, avant et après l’amélioration des outils et du contexte. Les gains, les reculs et leurs preuves sont réunis dans ce fichier.":"Les mêmes questions et la même base, avec la qualité des réponses, le temps d’attente et le coût retourné par l’API.";
const status=({running:"En cours",completed:"Terminée",budget_stop:"Arrêt au plafond",unknown_cost_stop:"Coût à vérifier"})[data.status]||data.status;
$("run-status").lastElementChild.textContent=(passes.length>1?`Passe ${activePass+1} · `:"")+status;
$("hero-meta").innerHTML=`<span class="meta-tag">${data.models.length} modèles</span><span class="meta-tag">${data.cases.length} cas · ${data.models[0]?.expected??0} tours / modèle</span><span class="meta-tag">${data.expected_sessions} sessions / passe · ${data.expected_turns} tours prévus</span><span class="meta-tag">Passe affichée : ${activePass+1}</span><span>${esc(date(data.started_utc))}</span>`;
$("footer-date").textContent=date(data.finished_utc||data.generated_utc);
let notices=[...data.warnings,...(bundle.comparison?.warnings||[])];
if(data.status==="running")notices.push("Exécution en cours : ce fichier est un instantané partiel. Les réponses encore absentes ne sont pas des mesures.");
if(!data.review_attached)notices.push("La relecture des réponses de la passe affichée n’est pas attachée. Aucun score de qualité n’est déduit des seuls contrôles automatiques.");
if(data.input_budget.uncertain_requests)notices.push(`${data.input_budget.uncertain_requests} requête(s) sans coût complet retourné pour la passe affichée : leurs entrées restent réservées dans le plafond.`);
$("notice").textContent=notices.join(" ");
$("pass-picker").innerHTML=passes.length>1?passes.map((p,i)=>`<button class="button" aria-pressed="${i===activePass}" data-pass="${i}">Passe ${i+1} · ${i?"améliorée":"initiale"}</button>`).join(""):"";
$("pass-picker").querySelectorAll("[data-pass]").forEach(b=>b.addEventListener("click",()=>{activePass=Number(b.dataset.pass);data=passes[activePass];activateTab("overview");render()}));
}
$("filter-menu").innerHTML=data.models.map(m=>`<label><input type="checkbox" value="${esc(m.id)}" checked><span class="dot" style="background:${color(m)}"></span>${esc(m.name)}</label>`).join("")+`<button class="button" id="select-all-models">Tout afficher</button>`;
$("filter-menu").querySelectorAll("input").forEach(input=>input.addEventListener("change",()=>{if(input.checked)selected.add(input.value);else selected.delete(input.value);render()}));
$("select-all-models").addEventListener("click",()=>{$("filter-menu").querySelectorAll("input").forEach(i=>{i.checked=true;selected.add(i.value)});render()});
$("question-search").addEventListener("input",renderMatrix);
document.querySelectorAll("[data-sort]").forEach(button=>button.addEventListener("click",()=>{if(sortKey===button.dataset.sort)sortDirection*=-1;else{sortKey=button.dataset.sort;sortDirection=["name","median_success_seconds","actual_reported_cost"].includes(sortKey)?1:-1}document.querySelectorAll(".ranking th[aria-sort]").forEach(th=>th.setAttribute("aria-sort","none"));button.parentElement.setAttribute("aria-sort",sortDirection===1?"ascending":"descending");renderRanking()}));
function renderStats(){const models=visible(),attempted=sum(models,"attempted"),expected=sum(models,"expected"),completed=sum(models,"completed"),correct=sum(models,"correct"),correctCases=sum(models,"correct_cases"),reviewed=models.filter(m=>m.quality_score!=null),budget=data.input_budget;$("stats").innerHTML=card("Cas entièrement corrects",reviewed.length?`${correctCases} / ${models.length*data.cases.length}`:"En attente",`${correct} / ${expected} réponses entièrement correctes ; Q37 exige deux tours.`)+card("Réponses finalisées",`${completed} / ${expected}`,`${attempted} tours tentés · ${sum(models,"not_attempted")} non lancés`)+card("Coût du panel retourné",models.some(m=>m.actual_reported_cost!=null)?money(sum(models,"actual_reported_cost")):"—",`Global connu : ${money(budget.actual_reported_total_cost_usd)} · préparation : ${money(data.prior_input_budget.actual_reported_total_cost_usd??0)}. Retours manquants non inclus.`)+card("Entrée comptée dans le plafond",money(budget.conservative_input_debit_usd),`Plafond ${money(budget.max_input_cost_usd??2)} · réservations comprises`);$("progress").textContent=`${models.length} modèles affichés · ${attempted} / ${expected} tours tentés · ${completed} réponses finalisées`;$("filter-count").textContent=`(${models.length}/${data.models.length})`;const ranked=models.filter(m=>m.quality_score!=null).sort((a,b)=>b.quality_score-a.quality_score||(a.median_success_seconds??Infinity)-(b.median_success_seconds??Infinity));if(!ranked.length){$("insights").innerHTML="";return}const best=ranked[0],tied=ranked.filter(m=>Math.abs(m.quality_score-best.quality_score)<.001),fastest=models.filter(m=>m.median_success_seconds!=null).sort((a,b)=>a.median_success_seconds-b.median_success_seconds)[0];$("insights").innerHTML=`<div class="insight-box"><h3>${tied.length>1?"Meilleur score partagé":"Meilleur score observé"} : ${esc(tied.map(m=>m.name).join(", "))}</h3><p class="small">${pct(best.quality_score)} sur ce panel. ${best.correct} réponse(s) entièrement correcte(s) sur ${best.expected} pour ${esc(best.name)}. Une seule exécution par cas dans ce rapport.</p></div><div class="insight-box"><h3>${fastest?`Temps médian le plus court : ${esc(fastest.name)}`:"Aucune réponse finalisée"}</h3><p class="small">${fastest?`${seconds(fastest.median_success_seconds)} sur ${fastest.completed} réponse(s) finalisée(s) ; ${fastest.correct} entièrement correcte(s). Vérifier les cas difficiles avant de choisir.`:"Les échecs restent visibles dans le tableau et les questions."}</p></div>`}
function renderRanking(){const models=visible().sort((a,b)=>{let x=a[sortKey],y=b[sortKey];if(x==null)return y==null?0:1;if(y==null)return -1;return typeof x==="string"?sortDirection*x.localeCompare(y,"fr"):sortDirection*(x-y)});$("ranking-body").innerHTML=models.length?models.map(m=>`<tr><td><span class="model-name"><i class="dot" style="background:${color(m)}"></i>${esc(m.name)}</span><span class="model-id mono">${esc(m.id)}</span></td><td><span class="score">${pct(m.quality_score)}</span>${m.quality_score!=null?`<span class="score-track" aria-hidden="true"><span class="score-fill" style="width:${Math.max(0,Math.min(100,m.quality_score))}%"></span></span>`:""}</td><td>${m.quality_score!=null?`${m.correct} / ${m.expected}`:"—"}<span class="model-id">${m.correct_cases} / ${data.cases.length} cas entiers · ${m.partial} réponse(s) partielle(s)</span></td><td>${m.completed} / ${m.expected}<span class="model-id"><span class="failure-count">${m.failure} échec(s)</span>${m.not_attempted?` · ${m.not_attempted} non lancé(s)`:""}</span></td><td>${seconds(m.median_success_seconds)}<span class="model-id">${m.completed} mesure(s) finalisée(s)</span></td><td>${money(m.actual_reported_cost)}<span class="model-id">${m.uncertain_requests} requête(s) incertaine(s)</span></td></tr>`).join(""):`<tr><td colspan="6" class="empty">Sélectionnez au moins un modèle.</td></tr>`}
function svgNode(name,attrs,text){const node=document.createElementNS("http://www.w3.org/2000/svg",name);for(const [k,v]of Object.entries(attrs||{}))node.setAttribute(k,v);if(text!=null)node.textContent=text;return node}
function renderScatter(){const svg=$("scatter");while(svg.children.length>2)svg.lastElementChild.remove();const models=visible(),points=models.filter(m=>m.quality_score!=null&&m.median_success_seconds!=null);const left=68,right=760,top=24,bottom=308;let xmax=Math.max(10,...points.map(m=>m.median_success_seconds*1.18));xmax=Math.ceil(xmax/5)*5;const x=v=>left+(right-left)*v/xmax,y=v=>bottom-(bottom-top)*v/100;for(let value=0;value<=100;value+=25){svg.append(svgNode("line",{x1:left,y1:y(value),x2:right,y2:y(value),stroke:"#e4eae4","stroke-width":1}));svg.append(svgNode("text",{x:left-12,y:y(value)+4,"text-anchor":"end",fill:"#738280","font-size":12},value+" %"))}for(let i=0;i<=5;i++){const value=i*xmax/5;svg.append(svgNode("line",{x1:x(value),y1:top,x2:x(value),y2:bottom,stroke:"#f0f3ef","stroke-width":1}));svg.append(svgNode("text",{x:x(value),y:bottom+23,"text-anchor":"middle",fill:"#738280","font-size":12},number.format(value)+" s"))}svg.append(svgNode("text",{x:left,y:top-11,fill:"#617476","font-size":12},"Score qualité"));svg.append(svgNode("text",{x:(left+right)/2,y:bottom+53,"text-anchor":"middle",fill:"#617476","font-size":12},"Temps médian des réponses finalisées →"));const maxCost=Math.max(.0001,...points.map(m=>m.actual_reported_cost??0));const placed=[];for(const m of points){const cx=x(m.median_success_seconds),cy=y(m.quality_score),radius=8+14*Math.sqrt(Math.max(0,m.actual_reported_cost??0)/maxCost);const group=svgNode("g",{tabindex:0,role:"button","aria-label":`${m.name}, score ${pct(m.quality_score)}, temps médian ${seconds(m.median_success_seconds)}, coût reçu ${money(m.actual_reported_cost)}. Ouvrir ses réponses.`});group.append(svgNode("circle",{cx,cy,r:radius,fill:color(m),"fill-opacity":.16,stroke:color(m),"stroke-width":2}));group.append(svgNode("circle",{cx,cy,r:3,fill:color(m)}));group.append(svgNode("title",{},`${m.name} · ${pct(m.quality_score)} · ${seconds(m.median_success_seconds)} · ${money(m.actual_reported_cost)}`));let labelY=Math.max(17,cy-radius-8);while(placed.some(p=>Math.abs(p.x-cx)<115&&Math.abs(p.y-labelY)<15))labelY+=17;placed.push({x:cx,y:labelY});if(Math.abs(labelY-cy)>15)group.append(svgNode("line",{x1:cx,y1:cy,x2:cx+(cx>650?-radius-5:radius+5),y2:labelY-4,stroke:color(m),"stroke-opacity":.4,"stroke-width":1}));group.append(svgNode("text",{x:cx+(cx>650?-radius-8:radius+8),y:labelY,"text-anchor":cx>650?"end":"start",fill:color(m),"font-size":11,"font-weight":600},m.name));const open=()=>{activateTab("questions");$("question-search").value="";renderMatrix();openSession(m.id,data.cases[0]?.id)};group.addEventListener("click",open);group.addEventListener("keydown",e=>{if(["Enter"," "].includes(e.key)){e.preventDefault();open()}});svg.append(group)}if(!points.length){svg.append(svgNode("text",{x:(left+right)/2,y:160,"text-anchor":"middle",fill:"#738280","font-size":14},data.review_attached?"Aucune réponse finalisée pour les modèles sélectionnés.":"Le graphique qualité attend la relecture des réponses."))}$("scatter-legend").innerHTML=models.map(m=>`<div class="legend-item"><i class="dot" style="background:${color(m)};margin-top:6px"></i><div>${esc(m.name)}<small>${m.quality_score==null?"À relire":pct(m.quality_score)} · ${seconds(m.median_success_seconds)}${m.failure?` · ${m.failure} échec(s)`:""}</small></div></div>`).join("")}
function renderMatrix(){const models=visible(),needle=$("question-search").value.trim().toLocaleLowerCase("fr"),cases=data.cases.filter(c=>[c.id,c.kind,...c.turns].join(" ").toLocaleLowerCase("fr").includes(needle));$("matrix").innerHTML=`<thead><tr><th scope="col">Question</th>${models.map(m=>`<th scope="col"><i class="dot" style="background:${color(m)}"></i> ${esc(m.name)}</th>`).join("")}</tr></thead><tbody>${cases.map(c=>`<tr><td><div class="question-kind">${esc(c.id)} · ${esc(c.kind)}${c.expected_turns>1?` · ${c.expected_turns} tours`:""}</div><div class="question-name">${esc(c.turns[0]||"Libellé non disponible")}</div>${c.expected_turns>1?`<div class="small muted" style="margin-top:6px">↳ ${esc(c.turns[1]||"Tour suivant")}</div>`:""}</td>${models.map(m=>{const s=session(m.id,c.id),category=s?.category||"not_started",finalized=s?.turns.filter(t=>t.status==="completed")||[],latency=finalized.length?seconds(finalized.reduce((a,t)=>a+(t.timing.full_answer_seconds||0),0)):"";return `<td><button class="matrix-button ${category}" data-model="${esc(m.id)}" data-case="${esc(c.id)}" aria-label="${esc(m.name)} · ${esc(c.id)} · ${labels[category]}">${labels[category]}<span>${latency||(s?`${s.turns.length}/${s.expected_turns} tour(s)`:"aucune mesure")}</span></button></td>`}).join("")}</tr>`).join("")||`<tr><td colspan="${models.length+1}" class="empty">Aucune question ne correspond.</td></tr>`}</tbody>`;$("matrix").querySelectorAll("[data-case]").forEach(b=>b.addEventListener("click",()=>openSession(b.dataset.model,b.dataset.case)))}
function renderCosts(){const models=visible(),budget=data.input_budget,input=sum(models,"input_cost_at_list"),output=sum(models,"output_cost_at_list"),uncertain=sum(models,"uncertain_input_reservations");$("cost-stats").innerHTML=card("Coût total retourné",models.some(m=>m.actual_reported_cost!=null)?money(sum(models,"actual_reported_cost")):"—","Somme des retours API disponibles, entrées + sorties.")+card("Entrée connue au tarif public",models.some(m=>m.input_cost_at_list!=null)?money(input):"—","Comptabilité conservatrice ; les remises ne sont pas déduites.")+card("Sortie au tarif public",models.some(m=>m.output_cost_at_list!=null)?money(output):"—","Ce montant se situe en dehors du plafond d’entrée.")+card("Réservation d’entrée incertaine",models.some(m=>m.input_debit!=null)?money(Math.max(0,uncertain)):"—",`${sum(models,"uncertain_requests")} requête(s) peuvent encore être facturées.`);const debit=budget.conservative_input_debit_usd,limit=budget.max_input_cost_usd??2,margin=Math.max(0,(debit??0)-(budget.known_input_at_list_usd??0)-(budget.uncertain_input_reservations_usd??0));$("budget-meter").innerHTML=`<div class="budget-line"><span>Entrée comptée, tous modèles</span><strong>${money(debit)} / ${money(limit)}</strong></div><div class="budget-track"><div class="budget-fill" style="width:${debit==null?0:Math.min(100,debit/limit*100)}%"></div></div>`;$("budget-caption").textContent=debit==null?"La comptabilité du plafond sera affichée dès que le premier retour sera disponible.":`${number.format(debit/limit*100)} % du plafond d’entrée compté : ${money(budget.known_input_at_list_usd??0)} au tarif public, ${money(budget.uncertain_input_reservations_usd??0)} réservé pour les retours incertains et ${money(margin)} de marge tarifaire conservatrice. ${(budget.requests_started??0)} requêtes lancées${budget.blocked_requests?`, ${budget.blocked_requests} bloquée(s) par le plafond`:""}.`;const prior=data.prior_input_budget;$("prior-caption").textContent=prior.requests_started?`Le plafond global comprend aussi l’essai de configuration précédent : ${money(prior.actual_reported_total_cost_usd)} retourné par l’API et ${money(prior.uncertain_input_reservations_usd)} réservé pour ses retours incertains. Tous essais cumulés : ${money(budget.actual_reported_total_cost_usd)} retourné par l’API.`:"";const max=Math.max(.00001,...models.map(m=>(m.input_cost_at_list??0)+(m.uncertain_input_reservations??0)+(m.output_cost_at_list??0)));$("cost-bars").innerHTML=models.map(m=>{const known=m.input_cost_at_list??0,reserved=m.uncertain_input_reservations??0,out=m.output_cost_at_list??0;return `<div class="cost-row"><div class="model-name"><i class="dot" style="background:${color(m)}"></i>${esc(m.name)}</div><div class="bar-track" role="img" aria-label="${esc(m.name)} : entrée connue ${money(m.input_cost_at_list)}, sortie au tarif ${money(m.output_cost_at_list)}, réservation incertaine ${money(reserved)}"><span class="bar-segment input" style="width:${known/max*100}%"></span><span class="bar-segment output" style="width:${out/max*100}%"></span><span class="bar-segment uncertain" style="width:${reserved/max*100}%"></span></div><div class="cost-number">${money(m.actual_reported_cost)}<span class="model-id">reçu de l’API</span></div></div>`}).join("");$("price-body").innerHTML=models.map(m=>`<tr><td><span class="model-name"><i class="dot" style="background:${color(m)}"></i>${esc(m.name)}</span></td><td>${m.prices.prompt!=null?money(Number(m.prices.prompt)*1e6):"—"}</td><td>${m.prices.completion!=null?money(Number(m.prices.completion)*1e6):"—"}</td><td>${int.format(m.input_tokens)}</td><td>${int.format(m.output_tokens)}</td><td>${m.uncertain_requests}</td></tr>`).join("")}
function sourceHtml(proof,cited){const safeUrl=/^https?:\/\//i.test(proof.source_url||"")?proof.source_url:null;const title=[proof.brand,proof.model,proof.year].filter(v=>v!=null).join(" ")||proof.kind||"Preuve";const snippet=proof.text||proof.original_text||proof.value_text||(proof.row?json(proof.row):"");return `<li>${safeUrl?`<a href="${esc(safeUrl)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>`:esc(title)}${cited?" <span class=\"small\">· citée</span>":""}<span class="mono">${esc(proof.evidence_id)}</span>${snippet?`<div class="evidence-text">${esc(String(snippet))}</div>`:""}${proof.kind==="aggregate"?`<div class="evidence-text">Comptage : ${esc(proof.count)} · ${esc(json(proof.criteria||proof.scope||{}))}</div>`:""}</li>`}
const checkNames={identity_scope:"Identité et périmètre",answer_accuracy:"Exactitude",completeness:"Couverture",evidence_support:"Appui des preuves",no_material_overclaim:"Affirmations maîtrisées"};
function openSession(modelId,caseId){const m=data.models.find(m=>m.id===modelId),c=data.cases.find(c=>c.id===caseId),s=session(modelId,caseId);if(!m||!c)return;$("dialog-title").textContent=`${c.id} · ${m.name}`;$("dialog-subtitle").textContent=`${c.kind} · ${c.expected_turns} tour(s) attendu(s) · ${labels[s?.category||"not_started"]}`;let body="";for(let i=1;i<=c.expected_turns;i++){const t=s?.turns.find(t=>t.turn===i);if(!t){body+=`<div class="turn-card"><h3>Tour ${i} · Non lancé</h3><p class="muted small" style="margin-top:10px">Aucune réponse observée. ${esc(c.turns[i-1]||"")}</p></div>`;continue}const cited=new Set((t.final?.claims||[]).flatMap(claim=>claim.evidence_ids||[])),proofs=[...t.evidence].sort((a,b)=>Number(cited.has(b.evidence_id))-Number(cited.has(a.evidence_id)));body+=`<article class="turn-card"><div class="turn-head"><h3>Tour ${i} · ${esc(t.question)}</h3><span class="badge ${t.category}"><i class="state-dot ${t.category}"></i>${labels[t.category]}</span></div>${t.answer?`<pre class="answer">${esc(t.answer)}</pre>`:`<p class="answer">Aucune réponse finale acceptée. ${esc(t.error||t.status)}</p>`}${t.review?`<div class="review-note"><strong>Relecture.</strong> ${esc(t.review.reason||"Aucune remarque.")}</div><div class="checks">${Object.entries(t.review.checks||{}).map(([key,value])=>`<span class="check ${value===true?"yes":value===false?"no":""}">${value===true?"✓":value===false?"×":"?"} ${esc(checkNames[key]||key)}</span>`).join("")}</div>`:`<div class="review-note">${t.status==="completed"?"Cette réponse attend sa relecture. Les références présentes ont passé le contrôle de format ; leur présence ne suffit pas à prouver les faits.":"Échec d’exécution conservé dans les résultats."}</div>`}<div class="turn-metrics"><span>Réponse finale : ${seconds(t.timing.full_answer_seconds)}</span><span>Modèle : ${seconds(t.timing.model_seconds)}</span><span>Outils : ${seconds(t.timing.tool_seconds)}</span><span>${t.calls.length} appel(s) outil</span><span>Coût reçu : ${money(t.usage.cost_usd)}</span></div>${t.final?.missing?.length?`<details class="inspect" open><summary>Données manquantes signalées</summary><pre>${esc(json(t.final.missing))}</pre></details>`:""}<details class="inspect"><summary>Preuves livrées : ${proofs.length}, dont ${cited.size} citée(s)</summary><ul class="source-list">${proofs.map(p=>sourceHtml(p,cited.has(p.evidence_id))).join("")||"<li>Aucune preuve livrée.</li>"}</ul></details><details class="inspect"><summary>Appels des outils et résultats reçus</summary><pre>${esc(json(t.calls))}</pre></details><details class="inspect"><summary>Réponses brutes du modèle</summary><pre>${esc(json(t.model_responses))}</pre></details><details class="inspect"><summary>Réponse structurée, contrôles et usage</summary><pre>${esc(json({final:t.final,review:t.review,mechanical:t.mechanical,usage:t.usage,budget_requests:t.budget_requests,context:t.context,format_repairs:t.format_repairs}))}</pre></details></article>`}$("dialog-body").innerHTML=body;const dialog=$("answer-dialog");if(!dialog.open)dialog.showModal();$("close-dialog").focus()}
$("close-dialog").addEventListener("click",()=>$("answer-dialog").close());$("answer-dialog").addEventListener("click",e=>{if(e.target===$("answer-dialog")){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close()}});
function renderMethod(){
const protocol=data.protocol;
$("failure-protocol-caption").textContent=`Les causes regroupent les erreurs du parcours complet : ${protocol.rounds_per_turn??4} tours de modèle, ${protocol.tool_calls_per_turn??8} appels d’outils et ${int.format(protocol.max_tool_result_chars??32000)} caractères de résultats au maximum. Elles décrivent aussi l’intégration et ses plafonds. Une réponse finalisée mais incorrecte relève de la relecture. Un tour non lancé après l’échec précédent ne crée pas une nouvelle erreur.`;
$("method-chips").innerHTML=[`${data.cases.length} cas · ${data.models[0]?.expected??0} tours / modèle`,`1 passage par cas`,`${protocol.timeout_per_turn_seconds??30} s / tour`,`${protocol.rounds_per_turn??4} tours de modèle max`,`${protocol.tool_calls_per_turn??8} appels outils max`,`${int.format(protocol.max_tool_result_chars??32000)} caractères de résultats max`,`${int.format(protocol.max_output_tokens??1200)} tokens de sortie max / appel`,`6 outils communs + réponse finale`,`Raisonnement : ${typeof protocol.reasoning_effort==="object"?"minimum compatible / modèle":protocol.reasoning_effort??"none"}`,`Graine : ${protocol.seed??20261014}`].map(t=>`<span class="method-chip">${esc(t)}</span>`).join("");
$("source-hash").textContent=protocol.source_sha256||"Non disponible";$("report-hash").textContent=data.report_sha256;$("pack-hash").textContent=protocol.pack_manifest_sha256||"Non disponible";
const efforts=protocol.reasoning_effort;$("reasoning-settings").textContent=typeof efforts==="object"?"Réglages minimaux compatibles : "+data.models.map(m=>m.name+" = "+(efforts[m.id]??"non précisé")).join(" ; ")+". Certains modèles Google imposent du raisonnement ; cette différence est conservée dans les mesures.":"Raisonnement configuré : "+(efforts??"none")+".";
$("run-history").textContent=data.prior_input_budget.requests_started?"Pour cette passe, l’essai de configuration initial a été arrêté après un refus de paramètre Google. Les huit modèles ont ensuite été relancés avec leurs réglages compatibles. Ses réponses ne servent pas au classement ; ses coûts et réservations restent compris dans le budget historique de cette passe.":"Cette passe utilise un nouveau budget d’entrée indépendant. Les réponses et les dépenses des passes précédentes ne lui sont pas imputées.";
const baseline=data.models.find(m=>m.id==="openai/gpt-6-luna");const pricier=baseline?data.models.filter(m=>Number(m.prices.prompt)>Number(baseline.prices.prompt)||Number(m.prices.completion)>Number(baseline.prices.completion)):[];$("price-note").textContent=pricier.length?pricier.map(m=>m.name).join(" et ")+" coûtent plus cher que GPT-6 Luna au tarif public. Ils sont conservés dans le panel demandé comme points de comparaison.":"";
}
function renderFailures(){const models=visible(),causes=Object.keys(data.failure_cause_labels),totals=Object.fromEntries(causes.map(c=>[c,models.reduce((n,m)=>n+(m.failure_causes[c]||0),0)])),failed=Object.values(totals).reduce((a,b)=>a+b,0),attempted=sum(models,"attempted");$("failure-summary").textContent=`${failed} tour(s) non finalisé(s) sur ${attempted} tentés pour les modèles affichés. Les nombres indiquent la cause d’arrêt, indépendamment du score des réponses acceptées.`;const rows=causes.filter(c=>totals[c]>0).sort((a,b)=>totals[b]-totals[a]);$("failure-table").innerHTML=`<thead><tr><th scope="col">Cause enregistrée</th><th scope="col">Total</th>${models.map(m=>`<th scope="col"><i class="dot" style="background:${color(m)}"></i> ${esc(m.name)}</th>`).join("")}</tr></thead><tbody>${rows.map(c=>`<tr><td>${esc(data.failure_cause_labels[c])}</td><td class="failure-total">${totals[c]}</td>${models.map(m=>{const n=m.failure_causes[c]||0;return `<td>${n?`<span class="failure-heat" style="background:rgba(182,70,84,${Math.min(.3,.06+n*.035)})">${n}</span>`:`<span class="failure-zero">—</span>`}</td>`}).join("")}</tr>`).join("")||`<tr><td colspan="${models.length+2}" class="empty">Aucune erreur d’exécution observée pour les modèles affichés.</td></tr>`}${rows.length?`<tr><td><strong>Tours non finalisés</strong></td><td class="failure-total">${failed}</td>${models.map(m=>`<td class="failure-total">${Object.values(m.failure_causes).reduce((a,b)=>a+b,0)}</td>`).join("")}</tr>`:""}</tbody>`}
const changeLabels={improved:"Amélioration",regressed:"Dégradation",unchanged:"Score inchangé",unreviewed:"À relire",question_changed:"Question différente"};
const signed=(v,format=number.format.bind(number))=>v==null?"—":(v>0?"+":"")+format(v);
const deltaClass=(v,lowerBetter=false)=>v==null||v===0?"neutral":(lowerBetter?v<0:v>0)?"gain":"loss";
const passSession=(p,model,caseId)=>p.sessions.find(s=>s.model===model&&s.case_id===caseId);
function renderComparison(){
const comparison=bundle.comparison;
$("tab-comparison").hidden=!comparison;
if(!comparison)return;
const models=comparison.models.filter(m=>selected.has(m.id)),before=passes[0],after=passes[1];
const judged=before.review_attached&&after.review_attached;
$("compare-stats").innerHTML=card("Cas entièrement corrects",judged?`${sum(models.map(m=>m.before),"correct_cases")} → ${sum(models.map(m=>m.after),"correct_cases")}`:"En attente",`${models.length*comparison.case_ids.length} cas observables par passe. Q37 exige ses deux tours.`)+card("Cas améliorés",judged?String(sum(models,"improved")):"À relire","Le jugement du cas entier gagne des points.")+card("Cas dégradés",judged?String(sum(models,"regressed")):"À relire",`${sum(models,"unchanged")} scores inchangés · ${sum(models,"unreviewed")} non comparables.`)+card("Entrée de la nouvelle passe",money(after.current_input_budget.conservative_input_debit_usd),`Nouveau plafond ${money(after.current_input_budget.max_input_cost_usd??2)} ; réservations comprises.`);
const ranked=[...models].sort((a,b)=>{const x=a[compareSort],y=b[compareSort];if(x==null)return y==null?0:1;if(y==null)return -1;return typeof x==="string"?compareDirection*x.localeCompare(y,"fr"):compareDirection*(x-y)});
$("compare-ranking").innerHTML=ranked.map(m=>`<tr><td><span class="model-name"><i class="dot" style="background:${color(m)}"></i>${esc(m.name)}</span><span class="model-id mono">${esc(m.id)}</span><span class="model-id"><span class="gain">${m.improved} améliorés</span> · <span class="loss">${m.regressed} dégradés</span> · ${m.unchanged} inchangés</span></td><td><span class="score">${judged?`${m.before.correct_cases} → ${m.after.correct_cases}`:"À relire"}</span> <span class="delta ${deltaClass(m.correct_cases_delta)}">${signed(m.correct_cases_delta,int.format.bind(int))}</span><span class="model-id">sur ${comparison.case_ids.length} cas entiers par passe</span></td><td>${pct(m.before.quality_score)} → ${pct(m.after.quality_score)}<span class="model-id"><span class="delta ${deltaClass(m.quality_score_delta)}">${signed(m.quality_score_delta)} points</span></span></td><td>${seconds(m.matched_before_seconds)} → ${seconds(m.matched_after_seconds)}<span class="model-id"><span class="delta ${deltaClass(m.matched_seconds_delta,true)}">${signed(m.matched_seconds_delta)} s</span> · ${m.matched_cases} cas communs</span><span class="model-id">p50 réponses finalisées : ${seconds(m.before.median_success_seconds)} → ${seconds(m.after.median_success_seconds)}</span></td><td>${money(m.before.actual_reported_cost)} → ${money(m.after.actual_reported_cost)}<span class="model-id"><span class="delta ${deltaClass(m.known_cost_delta_usd,true)}">${signed(m.known_cost_delta_usd,v=>money(v))}</span></span><span class="model-id">Réservations incertaines : ${money(m.before.uncertain_input_reservations)} → ${money(m.after.uncertain_input_reservations)} (${m.before.uncertain_requests} → ${m.after.uncertain_requests} requêtes)</span><span class="model-id">Entrées reçues : ${int.format(m.before.input_tokens)} → ${int.format(m.after.input_tokens)} tokens</span></td></tr>`).join("")||'<tr><td colspan="5" class="empty">Sélectionnez au moins un modèle.</td></tr>';
const cases=before.cases.filter(c=>comparison.case_ids.includes(c.id));
$("compare-matrix").innerHTML=`<thead><tr><th scope="col">Question commune</th>${models.map(m=>`<th scope="col"><i class="dot" style="background:${color(m)}"></i> ${esc(m.name)}</th>`).join("")}</tr></thead><tbody>${cases.map(c=>`<tr><td><div class="question-kind">${esc(c.id)} · ${esc(c.kind)}${c.expected_turns>1?` · ${c.expected_turns} tours`:""}</div><div class="question-name">${esc(c.turns[0])}</div></td>${models.map(m=>{const result=m.cases.find(x=>x.id===c.id);return `<td><button class="matrix-button ${result.change}" data-compare-model="${esc(m.id)}" data-compare-case="${esc(c.id)}"><strong>${changeLabels[result.change]}</strong><span>${labels[result.before_category]} →<br>${labels[result.after_category]}</span></button></td>`}).join("")}</tr>`).join("")}</tbody>`;
$("compare-matrix").querySelectorAll("[data-compare-case]").forEach(b=>b.addEventListener("click",()=>openComparison(b.dataset.compareModel,b.dataset.compareCase)));
$("compare-source-note").textContent=(comparison.same_source?"Empreinte de la base identique. ":"L’empreinte de la base a changé. ")+(comparison.all_observed_questions_match?"Les libellés des tours communs observés sont identiques.":"Certains libellés diffèrent ; ces cas ne sont pas appariés.");
$("pipeline-changes").innerHTML=comparison.pipeline_changes.length?comparison.pipeline_changes.map(change=>`<li>${esc(typeof change==="string"?change:change.description||json(change))}</li>`).join(""):"<li>Les empreintes du code sont figées dans chaque protocole ; consulter les appels d’outils pour voir les résultats effectivement livrés.</li>";
$("settings-changes").innerHTML=comparison.settings_changes.map(c=>`<tr><td>${esc(c.label)}</td><td>${esc(typeof c.before==="object"?json(c.before):c.before)}</td><td>${esc(typeof c.after==="object"?json(c.after):c.after)}</td></tr>`).join("")||'<tr><td colspan="3">Les limites enregistrées sont identiques.</td></tr>';
$("compare-budgets").innerHTML=passes.map((p,i)=>{const current=p.current_input_budget;return `<tr><td><strong>Passe ${i+1} · ${i?"améliorée":"initiale"}</strong></td><td>${p.sessions.length} / ${p.expected_sessions}</td><td>${p.sessions.reduce((n,s)=>n+s.turns.length,0)} / ${p.expected_turns}</td><td>${money(current.actual_reported_total_cost_usd)}<span class="model-id">${current.reported_total_costs_missing??0} retour(s) manquant(s)</span></td><td>${money(current.conservative_input_debit_usd)} / ${money(current.max_input_cost_usd??2)}</td><td>${money(current.uncertain_input_reservations_usd)}</td></tr>`}).join("");
$("compare-budget-note").textContent=`Les tableaux comparent les deux panneaux mesurés. Pour la passe 1, la préparation antérieure représente en plus ${money(before.prior_input_budget.actual_reported_total_cost_usd??0)} de coût connu et ${money(before.prior_input_budget.conservative_input_debit_usd??0)} d’entrée comptée. Les coûts connus de tous les essais conservés dans ce fichier totalisent ${money(passes.reduce((total,p)=>total+(p.input_budget.actual_reported_total_cost_usd??0),0))}, sans transformer les réservations incertaines en dépenses confirmées.`;
}
document.querySelectorAll("[data-compare-sort]").forEach(button=>button.addEventListener("click",()=>{if(compareSort===button.dataset.compareSort)compareDirection*=-1;else{compareSort=button.dataset.compareSort;compareDirection=["name","matched_seconds_delta","known_cost_delta_usd"].includes(compareSort)?1:-1}renderComparison()}));
function comparedTurnHtml(t,index,passIndex,question){
if(!t)return `<article class="turn-card"><div class="pass-label">Passe ${passIndex+1} · ${passIndex?"améliorée":"initiale"}</div><h3>Non lancé</h3><p class="muted small" style="margin-top:10px">${esc(question||"")} · Aucune réponse observée.</p></article>`;
const cited=new Set((t.final?.claims||[]).flatMap(c=>c.evidence_ids||[])),proofs=[...t.evidence].sort((a,b)=>Number(cited.has(b.evidence_id))-Number(cited.has(a.evidence_id)));
return `<article class="turn-card"><div class="pass-label">Passe ${passIndex+1} · ${passIndex?"améliorée":"initiale"}</div><div class="turn-head"><h3>${esc(t.question)}</h3><span class="badge ${t.category}">${labels[t.category]}</span></div>${t.answer?`<pre class="answer">${esc(t.answer)}</pre>`:`<p class="answer">Aucune réponse finale acceptée. ${esc(t.error||t.status)}</p>`}<div class="review-note">${t.review?`<strong>Relecture.</strong> ${esc(t.review.reason||"Aucune remarque.")}`:t.status==="completed"?"Cette réponse attend sa relecture.":"Échec d’exécution enregistré."}</div><div class="checks">${Object.entries(t.review?.checks||{}).map(([key,v])=>`<span class="check ${v===true?"yes":v===false?"no":""}">${v===true?"✓":v===false?"×":"?"} ${esc(checkNames[key]||key)}</span>`).join("")}</div><div class="turn-metrics"><span>Temps complet : ${seconds(t.timing.full_answer_seconds)}</span><span>Modèle : ${seconds(t.timing.model_seconds)}</span><span>Outils : ${seconds(t.timing.tool_seconds)}</span><span>${t.calls.length} appel(s) outil</span><span>Coût reçu : ${money(t.usage.cost_usd)}</span><span>Entrée reçue : ${t.usage.input_tokens==null?"—":int.format(t.usage.input_tokens)} tokens</span></div>${t.final?.missing?.length?`<details class="inspect"><summary>Données manquantes signalées</summary><pre>${esc(json(t.final.missing))}</pre></details>`:""}<details class="inspect"><summary>Preuves livrées : ${proofs.length}, dont ${cited.size} citées</summary><ul class="source-list">${proofs.map(p=>sourceHtml(p,cited.has(p.evidence_id))).join("")||"<li>Aucune preuve livrée.</li>"}</ul></details><details class="inspect"><summary>Appels et résultats des outils</summary><pre>${esc(json(t.calls))}</pre></details><details class="inspect"><summary>Réponses brutes du modèle</summary><pre>${esc(json(t.model_responses))}</pre></details><details class="inspect"><summary>Réponse structurée, jugement et comptabilité</summary><pre>${esc(json({final:t.final,review:t.review,mechanical:t.mechanical,usage:t.usage,budget_requests:t.budget_requests,context:t.context,format_repairs:t.format_repairs}))}</pre></details></article>`;
}
function openComparison(modelId,caseId){
const model=bundle.comparison.models.find(m=>m.id===modelId),caseInfo=passes[0].cases.find(c=>c.id===caseId),change=model?.cases.find(c=>c.id===caseId);if(!model||!caseInfo)return;
const old=passSession(passes[0],modelId,caseId),fresh=passSession(passes[1],modelId,caseId);
$("dialog-title").textContent=`${caseId} · ${model.name}`;$("dialog-subtitle").textContent=`${caseInfo.kind} · ${changeLabels[change.change]} · Passe 1 ${labels[change.before_category]} → Passe 2 ${labels[change.after_category]}`;
let body="";
for(let i=1;i<=caseInfo.expected_turns;i++){
const a=old?.turns.find(t=>t.turn===i),b=fresh?.turns.find(t=>t.turn===i),callNames=t=>t?.calls.map(c=>c.name).join(" → ")||"aucun",requests=t=>t?.budget_requests||[],bytes=t=>requests(t).reduce((n,r)=>n+(r.payload_utf8_bytes||0),0);
body+=`<section class="comparison-turn"><h3>Tour ${i} · ${esc(caseInfo.turns[i-1]||"")}</h3><details class="receipt-diff"><summary class="small">Parcours et contexte envoyés · différences enregistrées</summary><div class="turn-metrics"><span>Appels modèle : ${a?.model_responses.length??0} → ${b?.model_responses.length??0}</span><span>Tokens entrée reçus : ${a?.usage.input_tokens==null?"—":int.format(a.usage.input_tokens)} → ${b?.usage.input_tokens==null?"—":int.format(b.usage.input_tokens)}</span><span>Volume total envoyé à l’API : ${requests(a).length?int.format(bytes(a)):"—"} → ${requests(b).length?int.format(bytes(b)):"—"} octets</span></div><p class="small muted" style="margin-top:10px">Passe 1 : ${esc(callNames(a))}<br>Passe 2 : ${esc(callNames(b))}</p><p class="caption">Le volume est la somme des requêtes complètes enregistrées, historique retransmis compris ; il ne mesure pas la seule longueur des extraits. Les retours de tokens manquants restent inconnus.</p></details><div class="comparison-grid">${comparedTurnHtml(a,i,0,caseInfo.turns[i-1])}${comparedTurnHtml(b,i,1,caseInfo.turns[i-1])}</div></section>`;
}
$("dialog-body").innerHTML=body;const dialog=$("answer-dialog");if(!dialog.open)dialog.showModal();$("close-dialog").focus();
}
function render(){renderHeader();renderMethod();renderStats();renderRanking();renderScatter();renderMatrix();renderCosts();renderFailures();renderComparison()}
activateTab(bundle.comparison?"comparison":"overview");render();
</script>
</body>
</html>'''


def render(report, out, *, semantic_review=None, pack=None, baseline_report=None, baseline_review=None):
    current = normalize(report, semantic_review, pack)
    passes = [current]
    if baseline_report is not None:
        passes.insert(0, normalize(baseline_report, baseline_review, pack))
    data = {"title": "Benchmark SQL + RAG · Comparaison des passes", "passes": passes}
    if len(passes) == 2:
        data["comparison"] = compare_passes(*passes)
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # An answer containing </script> must remain data rather than HTML source.
    serialized = (serialized.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
                  .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    page = TEMPLATE.replace("__BENCHMARK_DATA__", serialized)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return {"html": str(out.resolve()), "report_sha256": current["report_sha256"],
            "passes": len(passes), "models": len(current["models"]),
            "observed_sessions": [len(p["sessions"]) for p in passes],
            "observed_turns": [sum(len(s["turns"]) for s in p["sessions"]) for p in passes],
            "semantic_review_attached": [p["review_attached"] for p in passes],
            "warnings": [warning for p in passes for warning in p["warnings"]]
                        + data.get("comparison", {}).get("warnings", [])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--semantic-review", type=Path)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--baseline-review", type=Path)
    parser.add_argument("--pack", type=Path, default=ROOT / "eval_results/technical/sql-rag-comparison-20261014-v4")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.report, args.out, semantic_review=args.semantic_review, pack=args.pack,
                            baseline_report=args.baseline_report, baseline_review=args.baseline_review),
                     ensure_ascii=False, indent=2))

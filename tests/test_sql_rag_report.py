"""Guard against misleading before/after comparisons in the offline report."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sql_rag_report", ROOT / "scripts/render_sql_rag_benchmark.py")
report_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report_module)


def write_pass(tmp_path, name, results, judgments, **extras):
    report = {"status": "completed", "protocol": {"models": ["example/model"],
              "cases": list(dict.fromkeys(session["case_id"] for session in results)),
              "source_sha256": "same-source"}, "results": results, **extras}
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(report))
    review = {"run_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "models": [{"model": "example/model", "quality_score_percent": 50,
                           "cases": judgments}]}
    review_path = tmp_path / f"{name}-review.json"
    review_path.write_text(json.dumps(review))
    return path, review_path


def session(case_id, *turns, expected=1):
    return {"model": "example/model", "case_id": case_id, "expected_turns": expected,
            "turns": [{"turn": index, "question": f"Question {case_id}, tour {index}",
                       "status": status, "answer": answer,
                       "timing": {"full_answer_seconds": seconds},
                       "usage": {"cost_usd": .01}, "evidence": []}
                      for index, (status, seconds, answer) in enumerate(turns, 1)]}


def judgment(case_id, *categories):
    return {"case_id": case_id, "turns": [{"turn": i, "category": category,
            "score": {"correct": 2, "partial": 1}.get(category, 0)}
            for i, category in enumerate(categories, 1)]}


def test_matched_latency_does_not_reward_new_fast_cases(tmp_path):
    old, old_review = write_pass(tmp_path, "old", [session("Q1", ("completed", 5, "ok")),
        session("Q2", ("timeout", 30, ""))], [judgment("Q1", "correct"), judgment("Q2", "failure")])
    new, new_review = write_pass(tmp_path, "new", [session("Q1", ("completed", 7, "ok")),
        session("Q2", ("completed", 1, "ok"))], [judgment("Q1", "correct"), judgment("Q2", "correct")])
    before = report_module.normalize(old, old_review, None)
    after = report_module.normalize(new, new_review, None)
    comparison = report_module.compare_passes(before, after)["models"][0]
    assert after["models"][0]["median_success_seconds"] < before["models"][0]["median_success_seconds"]
    assert comparison["matched_cases"] == 1
    assert comparison["matched_seconds_delta"] == 2  # The same case got slower.
    assert comparison["improved"] == 1


def test_partial_conversation_is_not_a_matched_success(tmp_path):
    old, old_review = write_pass(tmp_path, "old", [session("Q37", ("completed", 1, "ok"), expected=2)],
                                [judgment("Q37", "correct")])
    new, new_review = write_pass(tmp_path, "new", [session("Q37", ("completed", 2, "ok"),
                                ("completed", 3, "ok"), expected=2)], [judgment("Q37", "correct", "correct")])
    data = report_module.compare_passes(report_module.normalize(old, old_review, None),
                                      report_module.normalize(new, new_review, None))["models"][0]
    assert data["before"]["correct_cases"] == 0
    assert data["after"]["correct_cases"] == 1
    assert data["matched_cases"] == 0
    assert data["matched_seconds_delta"] is None


def test_mismatched_review_cannot_create_quality_improvement(tmp_path):
    old, old_review = write_pass(tmp_path, "old", [session("Q1", ("completed", 3, "ok"))],
                                [judgment("Q1", "correct")])
    new, new_review = write_pass(tmp_path, "new", [session("Q1", ("completed", 2, "ok"))],
                                [judgment("Q1", "correct")])
    new.write_text(new.read_text() + "\n")  # Review no longer binds to exact report.
    after = report_module.normalize(new, new_review, None)
    compared = report_module.compare_passes(report_module.normalize(old, old_review, None), after)["models"][0]
    assert not after["review_attached"]
    assert compared["quality_score_delta"] is None
    assert compared["correct_cases_delta"] is None
    assert compared["improved"] == compared["regressed"] == 0
    assert compared["unreviewed"] == 1


def test_changed_question_is_not_paired(tmp_path):
    old, old_review = write_pass(tmp_path, "old", [session("Q1", ("completed", 3, "ok"))],
                                [judgment("Q1", "correct")])
    changed = session("Q1", ("completed", 2, "ok"))
    changed["turns"][0]["question"] = "Different question"
    new, new_review = write_pass(tmp_path, "new", [changed], [judgment("Q1", "correct")])
    result = report_module.compare_passes(report_module.normalize(old, old_review, None),
                                        report_module.normalize(new, new_review, None))
    assert not result["all_observed_questions_match"]
    assert result["models"][0]["matched_cases"] == 0
    assert result["models"][0]["cases"][0]["change"] == "question_changed"


def test_embedded_data_is_safe_and_budgets_stay_separate(tmp_path):
    malicious = '</script><script>fetch("https://evil.example")</script>'
    old, old_review = write_pass(tmp_path, "old", [session("Q1", ("completed", 3, malicious))],
        [judgment("Q1", "correct")], input_budget={"conservative_input_debit_usd": .9},
        current_input_budget={"conservative_input_debit_usd": .8})
    new, new_review = write_pass(tmp_path, "new", [session("Q1", ("completed", 2, "ok"))],
        [judgment("Q1", "correct")], input_budget={"conservative_input_debit_usd": .2})
    output = tmp_path / "report.html"
    report_module.render(new, output, semantic_review=new_review, baseline_report=old, baseline_review=old_review)
    html = output.read_text()
    payload = re.search(r'<script id="benchmark-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    assert "</script>" not in payload
    bundle = json.loads(payload)
    assert bundle["passes"][0]["sessions"][0]["turns"][0]["answer"] == malicious
    assert bundle["passes"][0]["current_input_budget"]["conservative_input_debit_usd"] == .8
    assert bundle["passes"][1]["current_input_budget"]["conservative_input_debit_usd"] == .2
    assert 'connect-src \'none\'' in html
    assert "data-compare-case" in html


def test_compact_source_map_restores_links_without_extra_proof_text(tmp_path):
    result = session("Q1", ("completed", 3, "ok"))
    receipt = result["turns"][0]
    receipt["evidence"] = [{"evidence_id": "f1:row:2", "object_id": "f1", "text": "Delivered excerpt"}]
    receipt["calls"] = [{"name": "get_fiches", "result": {"evidence": [
        {"evidence_id": "f1:row:2", "object_id": "f1", "text": "Longer text omitted from model view"}]},
        "delivered_result": {"sources": {"f1": {"brand": "Honda", "model": "CB 500 F", "year": 2020,
                                                  "source_url": "https://example.org/f1"}}}}]
    path, review = write_pass(tmp_path, "compact", [result], [judgment("Q1", "correct")])
    proof = report_module.normalize(path, review, None)["sessions"][0]["turns"][0]["evidence"][0]
    assert proof["source_url"] == "https://example.org/f1"
    assert proof["model"] == "CB 500 F"
    assert proof["text"] == "Delivered excerpt"


def test_followup_keeps_source_metadata_of_retained_proofs(tmp_path):
    conversation = session("Q37", ("completed", 3, "List of fiches"),
                           ("completed", 2, "Count of previous fiches"), expected=2)
    first, second = conversation["turns"]
    proof = {"evidence_id": "f1:equipment:ABS", "object_id": "f1", "text": "ABS de série"}
    first["evidence"] = [proof]
    first["calls"] = [{"name": "query_catalog", "delivered_result": {
        "sources": {"f1": {"brand": "Yamaha", "model": "MT-10", "year": 2020,
                           "source_url": "https://example.org/mt10-2020"}}, "evidence": [proof]}}]
    second["evidence"] = [proof, {"evidence_id": "aggregate:count", "kind": "aggregate", "count": 1}]
    second["calls"] = [{"name": "query_catalog", "delivered_result": {
        "sources": {}, "evidence": [{"evidence_id": "aggregate:count", "kind": "aggregate", "count": 1}]}}]
    path, review = write_pass(tmp_path, "conversation", [conversation], [judgment("Q37", "correct", "correct")])
    normalized = report_module.normalize(path, review, None)["sessions"][0]["turns"][1]
    retained = next(item for item in normalized["evidence"] if item["evidence_id"] == proof["evidence_id"])
    assert retained["source_url"] == "https://example.org/mt10-2020"
    assert retained["model"] == "MT-10"
    assert retained["text"] == "ABS de série"
    assert len(normalized["evidence"]) == 2

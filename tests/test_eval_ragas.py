import json
from types import SimpleNamespace

import pytest

pytest.importorskip("ragas", reason="RAGAS integration tests need the optional eval dependencies")

from bikefinder_rag.eval import run_ragas as evaluation
from bikefinder_rag.eval.provenance import load_answers_cache


def setup_generation(monkeypatch, tmp_path, result):
    path = tmp_path / "answers.json"
    monkeypatch.setattr(evaluation, "ANSWERS_CACHE", path)
    monkeypatch.setattr(evaluation, "BACKEND", "ollama")
    monkeypatch.setattr(evaluation, "run_agent", lambda *_: result)
    return path


@pytest.mark.parametrize("history", [
    [{"role": "user", "content": "Question"}],
    [{"role": "assistant", "tool_calls": [{"function": {"name": "filter_specs"}}]},
     {"role": "tool", "content": "Rows"}],
])
def test_transport_error_without_final_assistant_answer_is_not_cached(monkeypatch, tmp_path, history):
    path = setup_generation(monkeypatch, tmp_path, ("Could not reach the local Ollama server", history))
    with pytest.raises(RuntimeError, match="not cached"):
        evaluation.generate_answers([{"id": "q1", "question": "Question"}], [], None, {"model": "local"})
    assert not path.exists()


def test_real_answer_is_cached_with_contexts_and_generation_date(monkeypatch, tmp_path):
    answer = "Owners report low consumption."
    path = setup_generation(monkeypatch, tmp_path, (answer, [
        {"role": "tool", "content": "Low consumption"},
        {"role": "assistant", "content": answer},
    ]))
    identity = {"model": "local"}
    rows = evaluation.generate_answers([{"id": "q1", "question": "Question"}], [], None, identity)
    assert load_answers_cache(path, identity) == rows
    assert rows[0]["answer"] == answer
    assert rows[0]["contexts"] == ["Low consumption"]
    assert rows[0]["generated_at_utc"].endswith("+00:00")


def test_interrupted_generation_preserves_successes_and_later_cached_answers(monkeypatch, tmp_path):
    path = setup_generation(monkeypatch, tmp_path, None)
    def run_agent(conn, client, question):
        if question == "First":
            return "A real answer", [{"role": "assistant", "content": "A real answer"}]
        return "Server unavailable", [{"role": "user", "content": question}]
    monkeypatch.setattr(evaluation, "run_agent", run_agent)
    cached = [{"question": "Later", "answer": "Earlier successful answer", "contexts": ["Source"],
               "generated_at_utc": "2026-10-09T12:00:00+00:00"}]
    questions = [{"id": text, "question": text} for text in ("First", "Failing", "Later")]
    identity = {"model": "local"}
    with pytest.raises(RuntimeError):
        evaluation.generate_answers(questions, cached, None, identity)
    saved = load_answers_cache(path, identity)
    assert [row["question"] for row in saved] == ["First", "Later"]
    assert saved[1] == cached[0]


def test_anthropic_text_blocks_are_valid_but_pending_tool_calls_are_not():
    block = SimpleNamespace(type="text", text="Final answer")
    assert evaluation._completed_answer("Final answer", [{"role": "assistant", "content": [block]}])
    assert not evaluation._completed_answer("Final answer", [{"role": "assistant", "content": [
        block, SimpleNamespace(type="tool_use")
    ]}])


def test_all_failed_scores_are_null_in_standard_json():
    summary = evaluation._summarize_scores([
        {"faithfulness": None, "answer_relevancy": float("nan")},
        {"faithfulness": float("nan"), "answer_relevancy": None},
    ])
    assert summary["scores_available"] == {"faithfulness": 0, "answer_relevancy": 0}
    assert summary["faithfulness_mean"] is None
    assert summary["answer_relevancy_mean"] is None
    assert json.loads(json.dumps(summary, allow_nan=False)) == summary


def test_partial_scores_report_their_real_denominators():
    summary = evaluation._summarize_scores([
        {"faithfulness": 0.8, "answer_relevancy": None},
        {"faithfulness": 1.0, "answer_relevancy": 0.7},
    ])
    assert summary["scores_available"] == {"faithfulness": 2, "answer_relevancy": 1}
    assert summary["faithfulness_mean"] == 0.9
    assert summary["answer_relevancy_mean"] == 0.7

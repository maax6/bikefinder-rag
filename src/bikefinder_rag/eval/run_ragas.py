#!/usr/bin/env python3
"""RAGAS evaluation over the golden question set.

Runs each question through the real agent loop, capturing the tool
results it used as "contexts", then scores faithfulness (is the answer
grounded in those contexts?) and answer_relevancy (does it address the
question?) — the two RAGAS metrics that don't require hand-authored
ground-truth answers, which we don't have yet at pilot scale.

Run: PYTHONPATH=src .venv/bin/python -m bikefinder_rag.eval.run_ragas
"""

import json
import sys
from pathlib import Path

from anthropic import Anthropic
from datasets import Dataset
from dotenv import load_dotenv
from ragas import evaluate
from ragas.metrics import answer_relevancy, faithfulness

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
load_dotenv()

from bikefinder_rag.agent.loop import BACKEND, run_agent
from bikefinder_rag.db.client import get_connection

GOLDEN_PATH = Path(__file__).resolve().parent / "golden_questions.json"


def _extract_contexts(messages: list[dict]) -> list[str]:
    """Pull raw tool outputs back out of the message history run_agent
    returns, so RAGAS has 'contexts' to check the answer's faithfulness
    against. Handles both backends' tool-result message shapes."""
    contexts: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role, content = msg.get("role"), msg.get("content")
        if role == "tool" and isinstance(content, str):  # Ollama
            contexts.append(content)
        elif role == "user" and isinstance(content, list):  # Anthropic
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    contexts.append(block.get("content", ""))
    return contexts


def main() -> None:
    questions = json.loads(GOLDEN_PATH.read_text())
    client = None if BACKEND == "ollama" else Anthropic()
    conn = get_connection()

    rows = []
    for item in questions:
        answer, messages = run_agent(conn, client, item["question"])
        contexts = _extract_contexts(messages)
        rows.append(
            {
                "question": item["question"],
                "answer": answer,
                "contexts": contexts or ["(no tool call was made)"],
            }
        )
        print(f"[{item['id']}] {item['question']}\n  -> {answer[:200]}\n", file=sys.stderr)

    conn.close()

    dataset = Dataset.from_list(rows)
    result = evaluate(dataset, metrics=[faithfulness, answer_relevancy])

    out_path = Path(__file__).resolve().parent / "ragas_results.json"
    result.to_pandas().to_json(out_path, orient="records", indent=2)
    print(f"\nRAGAS results written to {out_path}", file=sys.stderr)
    print(result, file=sys.stderr)


if __name__ == "__main__":
    main()

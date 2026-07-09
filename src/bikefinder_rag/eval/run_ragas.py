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

from bikefinder_rag.agent.loop import SYSTEM_PROMPT, MODEL
from bikefinder_rag.agent.tools import TOOLS, execute_tool
from bikefinder_rag.db.client import get_connection

GOLDEN_PATH = Path(__file__).resolve().parent / "golden_questions.json"


def run_one(conn, client: Anthropic, question: str) -> tuple[str, list[str]]:
    """Like agent.loop.run_agent, but also collects raw tool outputs as
    RAGAS 'contexts' instead of just the final answer."""
    messages = [{"role": "user", "content": question}]
    contexts: list[str] = []

    while True:
        response = client.messages.create(
            model=MODEL, max_tokens=1024, system=SYSTEM_PROMPT, tools=TOOLS, messages=messages
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            answer = "".join(b.text for b in response.content if b.type == "text")
            return answer, contexts

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            results = execute_tool(conn, block.name, block.input)
            contexts.append(str(results) if results else "No matching rows.")
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": str(results) if results else "No matching rows."}
            )
        messages.append({"role": "user", "content": tool_results})


def main() -> None:
    questions = json.loads(GOLDEN_PATH.read_text())
    client = Anthropic()
    conn = get_connection()

    rows = []
    for item in questions:
        answer, contexts = run_one(conn, client, item["question"])
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

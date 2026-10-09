#!/usr/bin/env python3
"""RAGAS evaluation over the golden question set.

Runs each question through the real agent loop, capturing the tool
results it used as "contexts", then scores faithfulness (is the answer
grounded in those contexts?) and answer_relevancy (does it address the
question?) — the two RAGAS metrics that don't require hand-authored
ground-truth answers, which we don't have yet at pilot scale.

Fully local by default: generation uses AGENT_BACKEND (ollama for the
free path), the judge is an Ollama model (RAGAS_JUDGE_MODEL, default
qwen3.6 — deliberately a different model than the mistral-small
generator, to avoid a model grading its own writing style), and
answer_relevancy's embeddings are the project's own BGE-M3.

Note: ragas 0.4.3 requires langchain-community==0.4.1 (0.4.2 removed a
module ragas still imports) — pinned in pyproject.toml.

Run: PYTHONPATH=src .venv/bin/python -m bikefinder_rag.eval.run_ragas
"""

import json
import math
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
load_dotenv()

warnings.filterwarnings("ignore", category=DeprecationWarning)

import subprocess

from datasets import Dataset
from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_ollama import ChatOllama
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import answer_relevancy, faithfulness
from ragas.run_config import RunConfig

from bikefinder_rag.agent.loop import BACKEND, OLLAMA_HOST, TURN_LIMIT_MESSAGE, run_agent
from bikefinder_rag.db.client import get_connection
from bikefinder_rag.embeddings.embedder import embed_texts
from bikefinder_rag.eval.provenance import (
    CacheMismatchError, collect_provenance, dated_report_path, generation_identity,
    load_answers_cache, ollama_model_identity, save_answers_cache,
)

GOLDEN_PATH = Path(__file__).resolve().parent / "golden_questions.json"
ANSWERS_CACHE = Path(__file__).resolve().parent / "generated_answers.json"
JUDGE_MODEL = os.environ.get("RAGAS_JUDGE_MODEL", "qwen3.6")


class BgeM3Embeddings(Embeddings):
    """The project's own BGE-M3, exposed through langchain's interface so
    answer_relevancy scores with the same embedding space the RAG uses."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        return embed_texts([text])[0]


class ClaudeCliChat(BaseChatModel):
    """Judge via the Claude Code CLI (`claude -p`), i.e. the user's Claude
    subscription — no API key. RAGAS_JUDGE_MODEL='claude-cli' or
    'claude-cli:opus' picks it; only sensible for occasional eval runs
    (each call re-pays ~2-3s of CLI startup)."""

    model: str = "sonnet"

    @property
    def _llm_type(self) -> str:
        return "claude-cli"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        prompt = "\n\n".join(
            m.content for m in messages if isinstance(m.content, str) and m.content
        )
        last_error = ""
        for attempt in range(3):
            if attempt:
                time.sleep(60 * attempt)
            proc = subprocess.run(
                ["claude", "-p", "--model", self.model],
                input=prompt, capture_output=True, text=True, timeout=600,
            )
            output = proc.stdout.strip()
            # During a subscription usage limit, the CLI prints the limit
            # banner on stdout with exit 0 — returning it as a judge verdict
            # made every item silently NaN. Fail loudly and retry instead.
            looks_limited = any(
                s in output.lower() for s in ("usage limit", "rate limit", "limit reached")
            )
            if proc.returncode == 0 and output and not looks_limited:
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content=output))])
            last_error = (proc.stderr.strip() or output)[:400]
        raise RuntimeError(f"claude -p failed after 3 attempts: {last_error}")


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


def _completed_answer(answer: str, messages: list[dict]) -> bool:
    """Transport/auth/turn-limit strings are not generated final answers."""
    if not isinstance(answer, str) or not answer.strip() or answer == TURN_LIMIT_MESSAGE or not messages:
        return False
    final = messages[-1]
    if not isinstance(final, dict) or final.get("role") != "assistant" or final.get("tool_calls"):
        return False
    content = final.get("content")
    if isinstance(content, str):
        return content == answer
    if isinstance(content, list):
        text = []
        for block in content:
            kind = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if kind == "tool_use":
                return False
            if kind == "text":
                text.append(block.get("text", "") if isinstance(block, dict) else block.text)
        return "".join(text) == answer
    return False


def _summarize_scores(records: list[dict]) -> dict:
    summary = {"scores_available": {}}
    for name in ("faithfulness", "answer_relevancy"):
        values = [float(row[name]) for row in records
                  if row.get(name) is not None and math.isfinite(float(row[name]))]
        summary["scores_available"][name] = len(values)
        summary[f"{name}_mean"] = round(math.fsum(values) / len(values), 4) if values else None
    return summary


def generate_answers(questions: list[dict], cached_rows: list[dict], conn,
                     identity: dict) -> list[dict]:
    """Generate the missing answers, reusing any cached ones. The cache is
    rewritten after every answer, so an interrupted generation resumes at
    the first unanswered question instead of redoing the run."""
    answered = {row["question"]: row for row in cached_rows}
    rows: list[dict] = []
    client = None
    for item in questions:
        if item["question"] in answered:
            rows.append(answered[item["question"]])
            print(f"[{item['id']}] (cached)", file=sys.stderr)
            continue
        if BACKEND == "anthropic" and client is None:
            from anthropic import Anthropic
            client = Anthropic()
        answer, messages = run_agent(conn, client, item["question"])
        if not _completed_answer(answer, messages):
            raise RuntimeError(
                f"Generation failed for {item['id']}: no completed final assistant answer. "
                f"{str(answer)[:200]} Fix the backend and rerun to resume; this failure was not cached."
            )
        contexts = _extract_contexts(messages)
        rows.append({"question": item["question"], "answer": answer,
                     "contexts": contexts or ["(no tool call was made)"],
                     "generated_at_utc": datetime.now(timezone.utc).isoformat()})
        # Preserve later cached questions if generation is interrupted here.
        current = {row["question"] for row in rows}
        save_answers_cache(ANSWERS_CACHE, identity,
                           rows + [row for row in cached_rows if row["question"] not in current])
        print(f"[{item['id']}] {item['question']}\n  -> {answer[:200]}\n", file=sys.stderr)
    return rows


def main() -> None:
    questions = json.loads(GOLDEN_PATH.read_text())

    # Verify the generator and corpus before reusing any answer. Changing
    # only the judge is allowed; old caches with no provenance need a rerun.
    conn = get_connection()
    try:
        metadata = collect_provenance(conn, generation=True)
        identity = generation_identity(metadata)
        try:
            cached_rows = load_answers_cache(ANSWERS_CACHE, identity,
                                            regenerate="--regenerate" in sys.argv)
        except CacheMismatchError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Generating answers (backend={BACKEND}, {len(cached_rows)} cached)...", file=sys.stderr)
        rows = generate_answers(questions, cached_rows, conn, identity)
        save_answers_cache(ANSWERS_CACHE, identity, rows)
    finally:
        conn.close()
    metadata["judge_model"] = JUDGE_MODEL
    metadata["answers_generated_at_utc"] = {
        q["id"]: row["generated_at_utc"] for q, row in zip(questions, rows)
    }
    metadata["cached_answers_reused"] = len(
        {q["question"] for q in questions} & {row["question"] for row in cached_rows}
    )

    if JUDGE_MODEL.startswith("claude-cli"):
        _, _, cli_model = JUDGE_MODEL.partition(":")
        judge_chat = ClaudeCliChat(model=cli_model or "sonnet")
        metadata["judge"] = {"backend": "claude-cli", "model": judge_chat.model,
                             "requested_model": JUDGE_MODEL}
        print(f"Scoring with judge=claude -p --model {judge_chat.model} "
              "(subscription, no API key)...", file=sys.stderr)
    else:
        metadata["judge"] = {"backend": "ollama", **ollama_model_identity(JUDGE_MODEL, OLLAMA_HOST),
                             "options": {"temperature": 0.0, "num_ctx": 16384}}
        print(f"Scoring with judge={JUDGE_MODEL} (local Ollama)...", file=sys.stderr)
        # 16k context: on the full corpus, tool outputs make faithfulness
        # prompts overflow 8k and the judge silently loses the tail.
        judge_chat = ChatOllama(model=JUDGE_MODEL, base_url=OLLAMA_HOST, temperature=0.0, num_ctx=16384)
        # Warm the judge up before scoring: loading a 20GB+ model into GPU
        # memory takes minutes and would otherwise be billed to the first
        # item's RunConfig timeout (observed: Job[0] TimeoutError at 600s).
        print("  warming up the judge (model load)...", file=sys.stderr)
        judge_chat.invoke("ping")
    judge = LangchainLLMWrapper(judge_chat)
    embeddings = LangchainEmbeddingsWrapper(BgeM3Embeddings())

    dataset = Dataset.from_list([
        {key: row[key] for key in ("question", "answer", "contexts")} for row in rows
    ])
    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy],
        llm=judge,
        embeddings=embeddings,
        # 20 min/item: long-context faithfulness jobs on a local judge
        # were blowing the 10 min default and returning NaN.
        run_config=RunConfig(timeout=1200, max_workers=1),
    )

    df = result.to_pandas()
    df.insert(0, "id", [q["id"] for q in questions])

    out_path = dated_report_path(Path(__file__).resolve().parents[3] / "eval_results/ragas",
                                 "ragas_results", metadata["created_at_utc"])
    records = json.loads(df.to_json(orient="records"))
    summary = {
        "metadata": metadata,
        "generation_backend": BACKEND,
        "generation_model": metadata["generation"]["model"],
        "judge_model": JUDGE_MODEL,
        "questions_total": len(rows),
        **_summarize_scores(records),
        "per_question": records,
    }
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False))
    print(f"\nRAGAS results written to {out_path}", file=sys.stderr)
    print(result, file=sys.stderr)


if __name__ == "__main__":
    main()

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
import os
import sys
import time
import warnings
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

from bikefinder_rag.agent.loop import BACKEND, OLLAMA_HOST, run_agent
from bikefinder_rag.db.client import get_connection
from bikefinder_rag.embeddings.embedder import embed_texts

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


def generate_answers(questions: list[dict]) -> list[dict]:
    client = None
    if BACKEND != "ollama":
        from anthropic import Anthropic

        client = Anthropic()

    conn = get_connection()
    rows = []
    try:
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
    finally:
        conn.close()
    return rows


def main() -> None:
    questions = json.loads(GOLDEN_PATH.read_text())

    # Generation is the expensive half (12 agent runs); cache it so a crash
    # during scoring — or a judge/config change — doesn't force a redo.
    # Delete generated_answers.json (or pass --regenerate) for fresh answers.
    if ANSWERS_CACHE.exists() and "--regenerate" not in sys.argv:
        cached = json.loads(ANSWERS_CACHE.read_text())
        if [r["question"] for r in cached] == [q["question"] for q in questions]:
            print(f"Reusing generated answers from {ANSWERS_CACHE}", file=sys.stderr)
            rows = cached
        else:
            print("Answer cache is stale (questions changed), regenerating...", file=sys.stderr)
            rows = None
    else:
        rows = None

    if rows is None:
        print(f"Generating answers (backend={BACKEND})...", file=sys.stderr)
        rows = generate_answers(questions)
        ANSWERS_CACHE.write_text(json.dumps(rows, indent=2, ensure_ascii=False))

    if JUDGE_MODEL.startswith("claude-cli"):
        _, _, cli_model = JUDGE_MODEL.partition(":")
        judge_chat = ClaudeCliChat(model=cli_model or "sonnet")
        print(f"Scoring with judge=claude -p --model {judge_chat.model} "
              "(subscription, no API key)...", file=sys.stderr)
    else:
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

    dataset = Dataset.from_list(rows)
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

    out_path = Path(__file__).resolve().parent / "ragas_results.json"
    records = json.loads(df.to_json(orient="records"))
    summary = {
        "generation_backend": BACKEND,
        "judge_model": JUDGE_MODEL,
        "faithfulness_mean": round(float(df["faithfulness"].mean()), 4),
        "answer_relevancy_mean": round(float(df["answer_relevancy"].mean()), 4),
        "per_question": records,
    }
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nRAGAS results written to {out_path}", file=sys.stderr)
    print(result, file=sys.stderr)


if __name__ == "__main__":
    main()

"""Start a separate, preloaded local front; never restart an existing demo."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from dotenv import load_dotenv
import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7864)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--model", choices=["ministral-3:3b", "ministral-3:8b", "qwen3.5:4b"], default="qwen3.5:4b")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--traces", type=Path, required=True)
    parser.add_argument("--ready-report", type=Path, required=True)
    args = parser.parse_args()
    if args.ready_report.exists():
        raise FileExistsError("Keep startup measurements; choose a fresh report")
    load_dotenv()
    os.environ.update(AGENT_BACKEND="ollama", BIKEFINDER_JEV_ROUTER="1", BIKEFINDER_JEV_RAG="1",
        BIKEFINDER_CATALOG_RESEARCH="1", BIKEFINDER_CATALOG_EXPERIMENT="1",
        BIKEFINDER_EXPERIMENT_MODEL=args.model, BIKEFINDER_EXPERIMENT_INDEX=str(args.index.resolve()),
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", GRADIO_ANALYTICS_ENABLED="False",
        LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false", GRADIO_HOST="127.0.0.1")
    from bikefinder_rag.agent.rag_synthesis import local_url
    host = local_url(os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"))
    started = time.perf_counter()
    from bikefinder_rag.catalog.experiment import get_corpus
    from bikefinder_rag.embeddings import embedder, experiment_reranker
    get_corpus()
    embedder.embed_text("Préparation de la recherche locale.")
    experiment_reranker.rank("Transmission", ["Transmission manuelle ou automatique."])
    preparation_seconds = time.perf_counter() - started
    with requests.Session() as session:
        session.trust_env = False
        preload_started = time.perf_counter()
        reply = session.post(host + "/api/generate", json={"model": args.model, "prompt": "",
            "stream": False, "keep_alive": "20m", "options": {"num_ctx": 4096}}, timeout=45, allow_redirects=False)
        reply.raise_for_status()
        preload_seconds = time.perf_counter() - preload_started
        version = session.get(host + "/api/version", timeout=5).json()
        tags = session.get(host + "/api/tags", timeout=5).json()
        model = next(m for m in tags["models"] if m["name"] == args.model)
    args.ready_report.parent.mkdir(parents=True, exist_ok=True)
    args.ready_report.write_text(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
        "index_and_retrieval_startup_seconds": preparation_seconds, "writer_preload_seconds": preload_seconds,
        "ready_seconds": time.perf_counter() - started, "model": model, "ollama": version,
        "note": "Normal service initialization, separate from each full frontend request; no question, answer or Jev cache"}, indent=2) + "\n")
    import runpy
    serve = runpy.run_path(str(Path(__file__).with_name("evaluate_rag_synthesis.py")))["serve"]
    serve(args.port, args.traces, [args.questions])


if __name__ == "__main__":
    main()

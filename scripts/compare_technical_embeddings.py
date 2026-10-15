"""Local embedding pilot on a frozen, deliberately reduced technical corpus.

This reuses known questions and all their supplied-scope passages, plus hard
negatives from the previous four-method study. It is neither a fresh holdout
nor a measurement of global retrieval across all 105,687 passages.
"""
import argparse
import gc
import json
import os
from pathlib import Path
import random
import time

import numpy as np

from benchmark_technical_retrieval import BM25, metrics, relevance_of, reciprocal_rank_fusion, rank_scores, sha256_file

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "eval_results/technical/retrieval-benchmark-20261013"
INDEX = ROOT / "data/technical/retrieval-benchmark-20261013/index"
TASK = "Retrieve source passages that answer the motorcycle technical question, preserving model, year, variant, units and equipment qualifications."


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def prepare(directory, minimum=4096):
    if directory.exists():
        raise FileExistsError("Keep the frozen pilot unchanged")
    questions = json.loads((OLD / "questions-holdout.json").read_text())["questions"]
    docs = [json.loads(line) for line in (INDEX / "documents.jsonl").read_text().splitlines()]
    scopes = {oid for q in questions for oid in q["supplied_scope_object_ids"]}
    required = {pid for q in questions for pid in relevance_of(q)}
    rows = json.loads((OLD / "holdout-global-firstpass-traces.json").read_text())["rows"]
    for row in rows:
        required.update(row.get("candidate_ids", []))
        required.update(p["id"] for p in row.get("ranking", []))
    selected = {i for i, d in enumerate(docs) if d["id"] in required or d["object_id"] in scopes}
    remaining = [i for i in range(len(docs)) if i not in selected]
    random.Random(20261014).shuffle(remaining)
    selected.update(remaining[:max(0, minimum - len(selected))])
    indices = sorted(selected)
    subset = [docs[i] for i in indices]
    lookup = {d["id"] for d in subset}
    assert required <= lookup
    directory.mkdir(parents=True)
    write(directory / "documents.json", subset)
    write(directory / "questions.json", questions)
    original = np.load(INDEX / "vectors.npy", mmap_mode="r", allow_pickle=False)
    np.save(directory / "bge-vectors.npy", original[indices])
    BM25.build([d["text"] for d in subset]).save(directory)
    write(directory / "protocol.json", {
        "status": "frozen_before_candidate_execution", "corpus_passages": len(subset),
        "original_passages": len(docs), "questions": len(questions),
        "positive_questions": sum(bool(relevance_of(q)) for q in questions),
        "question_source_sha256": sha256_file(OLD / "questions-holdout.json"),
        "original_documents_sha256": sha256_file(INDEX / "documents.jsonl"),
        "documents_sha256": sha256_file(directory / "documents.json"),
        "questions_sha256": sha256_file(directory / "questions.json"),
        "bge_vectors_sha256": sha256_file(directory / "bge-vectors.npy"),
        "selection": "All source sections within supplied scopes, union of historical retrieval candidates/rankings, seeded random distractors to minimum 4096",
        "queries_known": True, "global_candidate_subset_not_full_corpus": True,
        "max_length": 512, "rrf_constant": 60, "hybrid_candidates_per_method": 40,
        "query_instruction": TASK,
        "limits": ["Candidate pool uses historical systems and known references; selection bias is possible.",
                   "Supplied scope is an oracle: identity resolution is not evaluated.",
                   "Global judgments are incomplete; unjudged passages are not automatically false.",
                   "No calibrated abstention threshold or generation quality measured.",
                   "A full-corpus run and new independent questions are required before migration."]})
    print(json.dumps({"prepared": str(directory), "passages": len(subset)}), flush=True)


def evaluate(args):
    if args.out.exists():
        raise FileExistsError("Preserve first runs")
    protocol = json.loads((args.pilot / "protocol.json").read_text())
    for key, filename in [("documents_sha256", "documents.json"), ("questions_sha256", "questions.json"),
                          ("bge_vectors_sha256", "bge-vectors.npy")]:
        if sha256_file(args.pilot / filename) != protocol[key]:
            raise ValueError("Pilot fingerprint differs")
    documents = json.loads((args.pilot / "documents.json").read_text())
    questions = json.loads((args.pilot / "questions.json").read_text())
    lexical = BM25.load(args.pilot)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    import torch
    from sentence_transformers import SentenceTransformer
    started = time.perf_counter()
    model = SentenceTransformer(str(args.model_path), device="mps", local_files_only=True,
                               model_kwargs={"torch_dtype": torch.float16})
    model.max_seq_length = protocol["max_length"]
    load_seconds = time.perf_counter() - started
    instruction = "" if args.kind == "bge" else "Instruct: " + TASK + "\nQuery: "
    # Avoid silently dropping a number, unit or qualifier at a tokenizer boundary.
    doc_lengths = [len(model.tokenizer.encode(d["text"])) for d in documents]
    query_lengths = [len(model.tokenizer.encode(instruction + q["question"])) for q in questions]
    if max(doc_lengths + query_lengths) > model.max_seq_length:
        raise ValueError("Input would be truncated; freeze a revised protocol first")
    model.encode(["Préparation du modèle."], prompt="", normalize_embeddings=True)
    started = time.perf_counter()
    if args.kind == "bge":
        vectors = np.load(args.pilot / "bge-vectors.npy", allow_pickle=False)
        encoding_seconds = None
    else:
        vectors = model.encode([d["text"] for d in documents], prompt="", batch_size=16,
                               normalize_embeddings=True, show_progress_bar=True)
        encoding_seconds = time.perf_counter() - started
    if vectors.shape[0] != len(documents) or not np.isfinite(vectors).all():
        raise ValueError("Invalid candidate vectors")
    result = {"candidate": args.kind, "model_path": str(args.model_path), "protocol": protocol,
              "model_load_seconds": load_seconds, "document_encoding_seconds": encoding_seconds,
              "dimensions": vectors.shape[1], "max_document_tokens": max(doc_lengths),
              "max_query_tokens": max(query_lengths), "rows": [], "remote_api_cost_usd": 0,
              "script_sha256": sha256_file(__file__), "model_files_sha256": {
                  str(p.relative_to(args.model_path)): sha256_file(p) for p in args.model_path.rglob("*")
                  if p.is_file() and p.suffix in {".json", ".safetensors", ".model"}}}
    for q in questions:
        for scope in ["supplied", "candidate_subset"]:
            allowed = np.array([i for i, d in enumerate(documents) if scope == "candidate_subset"
                                or d["object_id"] in q["supplied_scope_object_ids"]], dtype=np.int64)
            started = time.perf_counter()
            encoded = model.encode([q["question"]], prompt=instruction, normalize_embeddings=True)[0]
            scores = vectors[allowed] @ encoded if len(allowed) else np.array([])
            order = np.argsort(-scores, kind="stable")[:40]
            dense = [(int(allowed[i]), float(scores[i])) for i in order]
            dense_seconds = time.perf_counter() - started
            lex_started = time.perf_counter()
            ranked_lex = rank_scores(lexical.scores(q["question"]), allowed, limit=40)
            lexical_seconds = time.perf_counter() - lex_started
            hybrid = reciprocal_rank_fusion([ranked_lex, dense], constant=60, limit=10)
            for method, ranking, elapsed in [("dense", dense, dense_seconds),
                    ("lexical", ranked_lex, lexical_seconds), ("hybrid", hybrid, dense_seconds + lexical_seconds)]:
                ids = [documents[i]["id"] for i, _ in ranking[:10]]
                result["rows"].append({"question_id": q["id"], "scope": scope, "method": method,
                                       "ranked_ids": ids, "metrics": metrics(ids, q), "seconds": elapsed})
    summary = []
    for scope in ["supplied", "candidate_subset"]:
        for method in ["lexical", "dense", "hybrid"]:
            rows = [r for r in result["rows"] if r["scope"] == scope and r["method"] == method]
            positive = [r for r in rows if r["metrics"]["hit_at1"] is not None]
            summary.append({"scope": scope, "method": method, "positive_questions": len(positive),
                **{key: float(np.mean([r["metrics"][key] for r in positive])) for key in
                   ["hit_at1", "recall_at5", "recall_at10", "mrr_at10", "all_groups_at10"]},
                "median_seconds": float(np.median([r["seconds"] for r in rows]))})
    result["summary"] = summary
    write(args.out, result)
    print(json.dumps({"candidate": args.kind, "summary": summary}), flush=True)
    del model
    gc.collect()
    torch.mps.empty_cache()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--kind", choices=["bge", "qwen", "e5"])
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.prepare:
        prepare(args.pilot)
    else:
        evaluate(args)

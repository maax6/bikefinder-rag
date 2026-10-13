#!/usr/bin/env python3
"""Read-only, offline retrieval benchmark of a frozen technical catalogue.

The protocol is frozen before encoding documents or opening evaluation questions.
All four pipelines index identical source passages with identity and section title.
Supplied scopes are explicitly an oracle experiment, never identity resolution.
No query/result cache, remote inference, production DB, or live chat is used.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
from pathlib import Path
import platform
import re
import resource
import sqlite3
import subprocess
import sys
import time
import unicodedata

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "technical-retrieval-benchmark-v1"
METHODS = ("lexical", "dense", "hybrid", "rerank")
STOPWORDS = set("le la les un une des du de d l a au aux ce cette ces et est sont en pour sur dans quelle quel quelles quels the a an is are of to for on in what which".split())


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_json(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(canonical_json(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def append_json(path, value):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(canonical_json(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def peak_memory_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def command_output(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def environment():
    versions = {}
    for package in ("numpy", "torch", "transformers", "sentence-transformers", "tokenizers"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    result = {"python": sys.version, "packages": versions, "platform": platform.platform(),
              "machine": platform.machine(), "cpu_count": os.cpu_count(), "load_average": os.getloadavg(),
              "process_peak_memory_bytes": peak_memory_bytes(), "git_commit": command_output(["git", "rev-parse", "HEAD"]),
              "git_status": command_output(["git", "status", "--porcelain"]),
              "script_sha256": sha256_file(__file__)}
    if sys.platform == "darwin":
        result.update({"cpu": command_output(["sysctl", "-n", "machdep.cpu.brand_string"]),
                       "memory_bytes": command_output(["sysctl", "-n", "hw.memsize"]),
                       "swap": command_output(["sysctl", "vm.swapusage"])})
    if "torch" in sys.modules:
        torch = sys.modules["torch"]
        result["torch_cpu_threads"] = torch.get_num_threads()
        result["torch_interop_threads"] = torch.get_num_interop_threads()
        if torch.backends.mps.is_available():
            result["mps_allocated_memory_bytes"] = torch.mps.current_allocated_memory()
            result["mps_driver_memory_bytes"] = torch.mps.driver_allocated_memory()
    return result


def tokenize(text):
    """Accent folded, case folded tokens, without language synonym expansion.

    Decimal separators normalize; digit groups ('1 084') join. Alphanumeric
    model codes ('MT-07', 'CB500F') keep a compact token and constituent tokens.
    Negations, 'avec', 'sans', 'option' and units are deliberately not stopwords.
    """
    value = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    value = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?:\D|$))", "", value)
    words = re.findall(r"[a-z]+(?:[-_/]?[a-z0-9]+)*|[0-9]+(?:[.,][0-9]+)?", value)
    tokens = []
    for word in words:
        word = word.replace(",", ".")
        compact = re.sub(r"[-_/]", "", word)
        if compact not in STOPWORDS:
            tokens.append(compact)
        if re.search(r"[a-z]", word) and re.search(r"[0-9]", word):
            tokens.extend(part for part in re.findall(r"[a-z]+|[0-9]+", word) if part not in STOPWORDS and part != compact)
    return tokens


def documents_from_snapshot(snapshot):
    """Original section indices are part of stable evidence IDs; never re-chunk."""
    documents = []
    counts = {"objects": 0, "spec_rows": 0, "passages": 0, "empty_sections": 0}
    conn = sqlite3.connect(f"{Path(snapshot).resolve().as_uri()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute("SELECT id,url,brand,model,year,source_sha256,record FROM objects ORDER BY id")
        for object_id, url, brand, model, year, source_hash, raw in rows:
            record = json.loads(raw)
            counts["objects"] += 1
            counts["spec_rows"] += len(record.get("spec_rows", []))
            for ordinal, section in enumerate(record.get("technical_sections", [])):
                original = section.get("text", "")
                if not original.strip():
                    counts["empty_sections"] += 1
                    continue
                title = section.get("section", "")
                identity = " ".join(str(x) for x in (brand, model, year) if x is not None)
                indexed = f"{identity}\n{title}\n{original}"
                documents.append({"id": f"{object_id}:section:{ordinal}", "object_id": object_id,
                                  "brand": brand, "model": model, "year": year, "section": title,
                                  "source_url": url, "source_sha256": source_hash,
                                  "original_text": original, "text": indexed,
                                  "text_sha256": hashlib.sha256(indexed.encode()).hexdigest()})
    finally:
        conn.close()
    counts["passages"] = len(documents)
    return documents, counts


class BM25:
    """Local BM25 with k1=1.2,b=.75; positive Robertson/Lucene-style IDF.

    Documents and queries use exactly the same tokenizer. Query term multiplicity
    contributes once. Stable ties are resolved using canonical document order.
    Postings are serialized numeric arrays, never untrusted pickled objects.
    """
    def __init__(self, vocabulary, offsets, postings, frequencies, lengths, k1=1.2, b=.75):
        self.vocabulary = vocabulary
        self.offsets = offsets
        self.postings = postings
        self.frequencies = frequencies
        self.lengths = lengths
        self.k1, self.b = k1, b
        self.average_length = float(np.mean(lengths)) if len(lengths) else 1.0
        if (len(offsets) != len(vocabulary) + 1 or offsets[0] != 0 or
                offsets[-1] != len(postings) or len(postings) != len(frequencies) or
                np.any(np.diff(offsets) < 0) or np.any(postings < 0) or np.any(postings >= len(lengths)) or
                np.any(frequencies <= 0) or np.any(lengths < 0)):
            raise ValueError("Invalid BM25 postings arrays")

    @classmethod
    def build(cls, texts, k1=1.2, b=.75):
        entries = defaultdict(list)
        lengths = []
        for idx, text in enumerate(texts):
            tokens = tokenize(text)
            lengths.append(len(tokens))
            for term, frequency in Counter(tokens).items():
                entries[term].append((idx, frequency))
        words = sorted(entries)
        offsets, indices, frequencies = [0], [], []
        for term in words:
            for idx, frequency in entries[term]:
                indices.append(idx)
                frequencies.append(frequency)
            offsets.append(len(indices))
        return cls({term: i for i, term in enumerate(words)}, np.asarray(offsets, dtype=np.int64),
                   np.asarray(indices, dtype=np.int32), np.asarray(frequencies, dtype=np.float32),
                   np.asarray(lengths, dtype=np.int32), k1, b)

    def save(self, directory):
        directory = Path(directory)
        atomic_json(directory / "lexical-vocabulary.json", {"terms": self.vocabulary, "k1": self.k1, "b": self.b})
        target = directory / "lexical-postings.npz"
        temporary = target.with_suffix(".npz.tmp")
        with temporary.open("wb") as stream:
            np.savez(stream, offsets=self.offsets, postings=self.postings,
                     frequencies=self.frequencies, lengths=self.lengths)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        metadata = read_json(directory / "lexical-vocabulary.json")
        with np.load(directory / "lexical-postings.npz", allow_pickle=False) as data:
            return cls(metadata["terms"], data["offsets"], data["postings"], data["frequencies"],
                       data["lengths"], metadata["k1"], metadata["b"])

    def scores(self, question):
        scores = np.zeros(len(self.lengths), dtype=np.float32)
        for term in set(tokenize(question)):
            token_id = self.vocabulary.get(term)
            if token_id is None:
                continue
            start, end = self.offsets[token_id:token_id + 2]
            ids, tf = self.postings[start:end], self.frequencies[start:end]
            df = end - start
            idf = math.log(1 + (len(self.lengths) - df + .5) / (df + .5))
            denominator = tf + self.k1 * (1 - self.b + self.b * self.lengths[ids] / self.average_length)
            scores[ids] += idf * tf * (self.k1 + 1) / denominator
        return scores


def rank_scores(scores, allowed, limit):
    allowed = np.asarray(allowed, dtype=np.int64)
    if len(allowed) == 0:
        return []
    if not np.all(np.isfinite(scores[allowed])):
        raise ValueError("Non-finite retrieval scores")
    ordering = np.lexsort((allowed, -scores[allowed]))[:limit]
    return [(int(allowed[i]), float(scores[allowed[i]])) for i in ordering]


def reciprocal_rank_fusion(rankings, constant=60, limit=30):
    values = defaultdict(float)
    for ranking in rankings:
        for rank, (idx, _score) in enumerate(ranking, 1):
            values[idx] += 1 / (constant + rank)
    return sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit]


def supplied_scope(documents, question, mode):
    if mode == "global":
        return np.arange(len(documents), dtype=np.int64)
    scope = question.get("supplied_scope_object_ids")
    if scope is None:
        scope = question.get("scope", {}).get("object_ids")
    if scope is None:
        raise ValueError(f"Question {question['id']} lacks explicit supplied scope")
    existing = {doc["object_id"] for doc in documents}
    if set(scope) - existing:
        raise ValueError(f"Unknown supplied object IDs: {sorted(set(scope) - existing)}")
    permitted = set(scope)
    return np.asarray([idx for idx, doc in enumerate(documents) if doc["object_id"] in permitted], dtype=np.int64)


def judgements_of(question):
    if "gold_passages" in question:
        return {item["id"]: float(item["grade"]) for item in question["gold_passages"]}
    return {key: float(value) for key, value in question.get("relevance", {}).items()}


def relevance_of(question):
    return {key: value for key, value in judgements_of(question).items() if value > 0}


def groups_of(question):
    groups = question.get("required_groups", question.get("evidence_groups", []))
    result = []
    for group in groups:
        if isinstance(group, dict):
            result.append(group.get("passage_ids", group.get("ids", [])))
        else:
            result.append(group)
    return result


def metrics(ranked_ids, question, k=10):
    """Metrics measure judged evidence, never similarity-as-truth.

    Multi-group coverage is separate: one alternative passage satisfies a group.
    Unknown/negative evidence is not assigned a fabricated relevance denominator.
    """
    gold = relevance_of(question)
    ids = ranked_ids[:10]
    judged = judgements_of(question)
    result = {"judged_gold_count": len(gold), "ranked_count": len(ids),
              "judgements_complete_global": bool(question.get("judgements_complete_global", False)),
              "unjudged_fraction_at10": sum(item not in judged for item in ids) / len(ids) if ids else 0.0}
    if not gold:
        result.update({f"recall_at{n}": None for n in (1, 3, 5, 10)})
        result.update({f"hit_at{n}": None for n in (1, 3, 5, 10)})
        result.update({"mrr_at10": None, "ndcg_at10": None})
        result.update({f"{metric}_at{cutoff}": None for metric in ("group_coverage", "all_groups") for cutoff in (1, 3, 5, 10)})
        return result
    for cutoff in (1, 3, 5, 10):
        result[f"recall_at{cutoff}"] = len(set(ranked_ids[:cutoff]) & set(gold)) / len(gold)
        result[f"hit_at{cutoff}"] = float(bool(set(ranked_ids[:cutoff]) & set(gold)))
    result["mrr_at10"] = next((1 / rank for rank, doc in enumerate(ids, 1) if doc in gold), 0.0)
    dcg = sum((2 ** gold.get(doc, 0) - 1) / math.log2(rank + 1) for rank, doc in enumerate(ids, 1))
    ideal = sum((2 ** grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(sorted(gold.values(), reverse=True)[:10], 1))
    result["ndcg_at10"] = dcg / ideal if ideal else 0.0
    groups = groups_of(question)
    for cutoff in (1, 3, 5, 10):
        covered = sum(bool(set(group) & set(ranked_ids[:cutoff])) for group in groups)
        result[f"group_coverage_at{cutoff}"] = covered / len(groups) if groups else None
        result[f"all_groups_at{cutoff}"] = float(covered == len(groups)) if groups else None
    return result


def model_spec(path):
    path = Path(path).resolve()
    if not path.is_dir():
        raise ValueError(f"A pinned local model directory is required: {path}")
    files = {}
    for file in sorted(path.rglob("*")):
        if file.is_file() and file.suffix in {".json", ".safetensors", ".bin", ".model", ".txt"}:
            files[str(file.relative_to(path))] = sha256_file(file)
    if not any(name.endswith((".safetensors", ".bin")) for name in files):
        raise ValueError(f"No local model weights in {path}")
    revision = path.name if re.fullmatch(r"[0-9a-f]{40}", path.name) else "content-addressed-local-directory"
    return {"path": str(path), "revision": revision, "file_sha256": files, "content_sha256": digest_json(files)}


def local_models(protocol, device, *, reranker=True):
    # Set before importing libraries. Loading APIs independently forbid network.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    from sentence_transformers import CrossEncoder, SentenceTransformer
    started = time.perf_counter()
    dense = SentenceTransformer(protocol["dense_model"]["path"], device=device, local_files_only=True)
    dense.max_seq_length = protocol["max_length"]
    if protocol.get("inference_dtype") == "float16":
        dense.half()
    timings = {"dense_load_seconds": time.perf_counter() - started}
    ranker = None
    if reranker:
        started = time.perf_counter()
        ranker = CrossEncoder(protocol["reranker_model"]["path"], device=device,
                              max_length=protocol["max_length"], local_files_only=True)
        if protocol.get("inference_dtype") == "float16":
            ranker.model.half()
        timings["reranker_load_seconds"] = time.perf_counter() - started
    return dense, ranker, timings


def token_lengths(tokenizer, texts):
    return [len(tokens) for tokens in tokenizer(texts, truncation=False, padding=False)["input_ids"]]


def validate_checkpoint(checkpoint, protocol_hash, documents_hash, vectors):
    if checkpoint["protocol_sha256"] != protocol_hash or checkpoint["documents_sha256"] != documents_hash:
        raise ValueError("Checkpoint protocol/corpus mismatch; use a new isolated directory")
    completed = int(checkpoint["completed"])
    if not 0 <= completed <= len(vectors):
        raise ValueError("Checkpoint offset outside vector matrix")
    expected_start = 0
    for batch in checkpoint.get("batches", []):
        if batch["start"] != expected_start or batch["end"] <= batch["start"] or batch["end"] > completed:
            raise ValueError("Checkpoint batches are not a contiguous durable prefix")
        fragment = np.asarray(vectors[batch["start"]:batch["end"]], dtype=np.float32)
        if hashlib.sha256(fragment.tobytes()).hexdigest() != batch["sha256"]:
            raise ValueError("Checkpoint vector checksum mismatch")
        if not np.all(np.isfinite(fragment)) or not np.allclose(np.linalg.norm(fragment, axis=1), 1, atol=.002):
            raise ValueError("Checkpoint contains invalid or unnormalised vectors")
        expected_start = batch["end"]
    if expected_start != completed:
        raise ValueError("Checkpoint completed offset disagrees with durable batches")
    return completed


def prepare(args):
    started = time.perf_counter()
    directory = Path(args.out).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "index-manifest.json").exists():
        raise ValueError("Completed index is immutable; use it or choose a new directory")
    documents, counts = documents_from_snapshot(args.snapshot)
    if not documents:
        raise ValueError("No non-empty technical passages")
    protocol_path = directory / "protocol.json"
    candidate = {"schema": SCHEMA, "snapshot": str(Path(args.snapshot).resolve()), "snapshot_sha256": sha256_file(args.snapshot),
                 "counts": counts, "representation": "brand model year\\nsection title\\nverbatim source section",
                 "stable_id": "object_id:section:original_section_index", "dense_dimension": 1024,
                 "dense_normalized": True, "dense_dtype": "float32", "distance": "cosine / exact dot product",
                 "lexical": {"method": "BM25", "k1": 1.2, "b": .75, "tokenizer": "accent-folded-codes-decimal-thousands-v1",
                             "stopwords": sorted(STOPWORDS), "idf": "log(1+(N-df+0.5)/(df+0.5))"},
                 "dense_model": model_spec(args.dense_model), "reranker_model": model_spec(args.reranker_model),
                 "pool": args.pool, "rerank_pool": args.pool, "k": args.k, "rrf_constant": args.rrf_constant,
                 "max_length": args.max_length, "device": args.device, "batch_size": args.batch_size,
                 "inference_dtype": args.dtype,
                 "repeats": args.repeats, "query_cache": False, "result_cache": False,
                 "preparation_code_sha256": preparation_code_hash(), "scope_modes": ["supplied-oracle", "global-no-scope"],
                 "holdout_policy": "Frozen before reading holdout. First pass never overwritten. No tuning on holdout."}
    if protocol_path.exists():
        protocol = read_json(protocol_path)
        if any(protocol.get(key) != value for key, value in candidate.items()):
            raise ValueError("Frozen protocol differs from requested prepare configuration")
    else:
        protocol = candidate | {"frozen_at": utc_now(), "environment_at_freeze": environment()}
        atomic_json(protocol_path, protocol)
    protocol_hash = digest_json(protocol)
    docs_path = directory / "documents.jsonl"
    if docs_path.exists():
        existing = [json.loads(line) for line in docs_path.read_text().splitlines() if line]
        if existing != documents:
            raise ValueError("Existing canonical documents differ from snapshot")
    else:
        with docs_path.open("x", encoding="utf-8") as stream:
            for document in documents:
                stream.write(canonical_json(document) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    docs_hash = sha256_file(docs_path)
    if not all((directory / name).exists() for name in ("lexical-postings.npz", "lexical-vocabulary.json")):
        lexical_started = time.perf_counter()
        BM25.build([doc["text"] for doc in documents]).save(directory)
        atomic_json(directory / "lexical-preparation.json", {"seconds": time.perf_counter() - lexical_started})
    else:
        BM25.load(directory)  # Reject interrupted/corrupt lexical serialization.
    dense, _ranker, timings = local_models(protocol, args.device, reranker=False)
    from transformers import AutoTokenizer
    reranker_tokenizer = AutoTokenizer.from_pretrained(protocol["reranker_model"]["path"], local_files_only=True)
    checkpoint_path, vector_path = directory / "embedding-checkpoint.json", directory / "vectors.npy"
    if vector_path.exists():
        vectors = np.load(vector_path, mmap_mode="r+", allow_pickle=False)
        checkpoint = read_json(checkpoint_path)
        offset = validate_checkpoint(checkpoint, protocol_hash, docs_hash, vectors)
    else:
        vectors = np.lib.format.open_memmap(vector_path, mode="w+", dtype=np.float32, shape=(len(documents), 1024))
        checkpoint = {"protocol_sha256": protocol_hash, "documents_sha256": docs_hash, "completed": 0, "batches": [],
                      "embedding_seconds": 0.0, "max_dense_document_tokens": 0, "max_reranker_document_tokens": 0,
                      "dense_document_truncations": 0, "reranker_document_truncations": 0,
                      "initial_load_timings": timings, "started_at": utc_now()}
        atomic_json(checkpoint_path, checkpoint)
        offset = 0
    print(f"Prepared {counts}; embeddings resume at {offset}/{len(documents)}; protocol {protocol_hash}", flush=True)
    last_progress = time.perf_counter()
    for start in range(offset, len(documents), args.batch_size):
        end = min(start + args.batch_size, len(documents))
        texts = [doc["text"] for doc in documents[start:end]]
        dense_lengths = token_lengths(dense.tokenizer, texts)
        reranker_lengths = token_lengths(reranker_tokenizer, texts)
        encoding_started = time.perf_counter()
        encoded = dense.encode(texts, batch_size=args.batch_size, normalize_embeddings=True,
                               convert_to_numpy=True, show_progress_bar=False)
        encoded = np.asarray(encoded, dtype=np.float32)
        if encoded.shape != (end - start, 1024) or not np.all(np.isfinite(encoded)):
            raise ValueError("Embedding output shape/value mismatch")
        norms = np.linalg.norm(encoded, axis=1, keepdims=True)
        if np.any(norms < 1e-8):
            raise ValueError("Zero embedding")
        encoded /= norms
        checkpoint["embedding_seconds"] += time.perf_counter() - encoding_started
        vectors[start:end] = encoded
        vectors.flush()
        checkpoint["completed"] = end
        checkpoint["batches"].append({"start": start, "end": end, "sha256": hashlib.sha256(encoded.tobytes()).hexdigest()})
        for prefix, lengths in (("dense", dense_lengths), ("reranker", reranker_lengths)):
            checkpoint[f"max_{prefix}_document_tokens"] = max(checkpoint[f"max_{prefix}_document_tokens"], max(lengths))
            checkpoint[f"{prefix}_document_truncations"] += sum(n > args.max_length for n in lengths)
        checkpoint["updated_at"] = utc_now()
        atomic_json(checkpoint_path, checkpoint)
        if time.perf_counter() - last_progress >= 30 or end == len(documents):
            print(f"Embeddings {end}/{len(documents)} ({end / len(documents):.1%}), cumulative encoding {checkpoint['embedding_seconds']:.1f}s", flush=True)
            last_progress = time.perf_counter()
    artifacts = {name: {"bytes": (directory / name).stat().st_size, "sha256": sha256_file(directory / name)}
                 for name in ("documents.jsonl", "vectors.npy", "lexical-vocabulary.json", "lexical-postings.npz", "protocol.json")}
    manifest = {"schema": SCHEMA, "protocol_sha256": protocol_hash, "artifacts": artifacts,
                "created_at": utc_now(), "counts": counts, "embedding_checkpoint": checkpoint,
                "lexical_preparation": read_json(directory / "lexical-preparation.json"),
                "this_prepare_process_seconds": time.perf_counter() - started, "environment": environment(),
                "total_index_bytes": sum(entry["bytes"] for entry in artifacts.values())}
    atomic_json(directory / "index-manifest.json", manifest)
    print(canonical_json({"index": str(directory), "counts": counts, "manifest": str(directory / "index-manifest.json")}), flush=True)


class RetrievalIndex:
    """Each method executes its complete pipeline; no query vector sharing."""
    def __init__(self, documents, lexical, vectors, dense, reranker, protocol):
        self.documents, self.lexical, self.vectors = documents, lexical, vectors
        self.dense, self.reranker, self.protocol = dense, reranker, protocol

    def search(self, question, allowed, method):
        if method not in METHODS:
            raise ValueError("Unknown retrieval method")
        t0 = time.perf_counter()
        timings = {"query_encoding_seconds": 0.0, "lexical_seconds": 0.0, "dense_search_seconds": 0.0,
                   "fusion_seconds": 0.0, "rerank_seconds": 0.0, "token_check_seconds": 0.0}
        pool, k = self.protocol["pool"], self.protocol["k"]
        lexical, dense = [], []
        query_tokens, pair_truncations = None, 0
        if method in ("lexical", "hybrid", "rerank"):
            started = time.perf_counter()
            lexical = rank_scores(self.lexical.scores(question), allowed, pool)
            timings["lexical_seconds"] = time.perf_counter() - started
        if method != "lexical":
            started = time.perf_counter()
            query_tokens = token_lengths(self.dense.tokenizer, [question])[0]
            timings["token_check_seconds"] += time.perf_counter() - started
            if query_tokens > self.protocol["max_length"]:
                raise ValueError("Query exceeds frozen max_length; do not silently truncate evaluation")
            started = time.perf_counter()
            query = np.asarray(self.dense.encode([question], normalize_embeddings=True,
                                               convert_to_numpy=True, show_progress_bar=False)[0], dtype=np.float32)
            norm = np.linalg.norm(query)
            if not np.isfinite(norm) or norm < 1e-8:
                raise ValueError("Invalid query vector")
            query /= norm
            timings["query_encoding_seconds"] = time.perf_counter() - started
            started = time.perf_counter()
            # Exact scoped matrix multiplication; global searches never read scope/gold.
            if len(allowed) == len(self.documents):
                scores = np.asarray(self.vectors @ query)
            else:
                scores = np.full(len(self.documents), -np.inf, dtype=np.float32)
                scores[allowed] = self.vectors[allowed] @ query
            dense = rank_scores(scores, allowed, pool)
            timings["dense_search_seconds"] = time.perf_counter() - started
        if method in ("hybrid", "rerank"):
            started = time.perf_counter()
            ranking = reciprocal_rank_fusion([lexical, dense], self.protocol["rrf_constant"], pool)
            timings["fusion_seconds"] = time.perf_counter() - started
        else:
            ranking = lexical if method == "lexical" else dense
        candidate_ids = [self.documents[idx]["id"] for idx, _score in ranking]
        if method == "rerank" and ranking:
            started = time.perf_counter()
            pairs = [(question, self.documents[idx]["text"]) for idx, _score in ranking]
            tokenizer = self.reranker.tokenizer
            encoded = tokenizer([pair[0] for pair in pairs], [pair[1] for pair in pairs], truncation=False, padding=False)
            pair_truncations = sum(len(ids) > self.protocol["max_length"] for ids in encoded["input_ids"])
            timings["token_check_seconds"] += time.perf_counter() - started
            if pair_truncations:
                raise ValueError("Rerank pairs exceed frozen max_length; benchmark would silently truncate")
            started = time.perf_counter()
            predicted = np.asarray(self.reranker.predict(pairs, batch_size=self.protocol["reranker_batch_size"],
                                                       show_progress_bar=False), dtype=np.float32).reshape(-1)
            if len(predicted) != len(ranking) or not np.all(np.isfinite(predicted)):
                raise ValueError("Reranker output mismatch")
            ranking = sorted([(idx, float(score)) for (idx, _old), score in zip(ranking, predicted)], key=lambda item: (-item[1], item[0]))
            timings["rerank_seconds"] = time.perf_counter() - started
        timings["total_seconds"] = time.perf_counter() - t0
        ranked = [{"id": self.documents[idx]["id"], "score": score, "rank": rank,
                   "object_id": self.documents[idx]["object_id"], "year": self.documents[idx]["year"],
                   "brand": self.documents[idx]["brand"], "model": self.documents[idx]["model"],
                   "section": self.documents[idx]["section"], "source_url": self.documents[idx]["source_url"],
                   "original_text": self.documents[idx]["original_text"]}
                  for rank, (idx, score) in enumerate(ranking[:k], 1)]
        return {"ranking": ranked, "candidate_ids": candidate_ids, "timings": timings,
                "query_tokens": query_tokens, "pair_truncations": pair_truncations, "scope_document_count": len(allowed)}


def load_questions(path, split):
    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
        rows = payload["questions"] if isinstance(payload, dict) else payload
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in text.splitlines() if line]
    questions = [row for row in rows if row.get("split", split) == split]
    if not questions or len({row["id"] for row in questions}) != len(questions):
        raise ValueError("Questions must be non-empty with unique IDs")
    for row in questions:
        if not isinstance(row.get("question"), str) or not row["question"].strip():
            raise ValueError("Missing original question")
        if any(grade < 0 or not math.isfinite(grade) for grade in judgements_of(row).values()):
            raise ValueError("Invalid relevance grade")
        if "gold_passages" in row and len({item["id"] for item in row["gold_passages"]}) != len(row["gold_passages"]):
            raise ValueError("Duplicate gold passage ID")
        if any(not group or set(group) - set(relevance_of(row)) for group in groups_of(row)):
            raise ValueError("Required evidence groups must be non-empty subsets of positive gold")
    return questions


def summarize(rows, questions):
    question_map = {row["id"]: row for row in questions}
    output = {}
    for method in METHODS:
        measured = [row for row in rows if row["method"] == method]
        first = [row for row in measured if row["repeat"] == 0]
        answerable = [row for row in first if row["metrics"]["judged_gold_count"]]
        seconds = np.asarray([row["timings"]["total_seconds"] for row in measured], dtype=float)
        aggregate = {"question_count": len(first), "latency_observations": len(measured),
                     "judged_positive_questions": len(answerable), "negative_questions": len(first) - len(answerable)}
        metric_names = ([f"{metric}_at{cutoff}" for metric in ("recall", "hit", "group_coverage", "all_groups") for cutoff in (1, 3, 5, 10)]
                        + ["mrr_at10", "ndcg_at10"])
        for name in metric_names:
            values = [row["metrics"][name] for row in answerable if row["metrics"][name] is not None]
            aggregate[name] = float(np.mean(values)) if values else None
        if len(seconds):
            aggregate["latency_seconds"] = {"median": float(np.median(seconds)), "p95": float(np.percentile(seconds, 95)),
                                             "maximum": float(np.max(seconds)), "std": float(np.std(seconds)), "minimum": float(np.min(seconds))}
            aggregate["stage_seconds_median"] = {stage: float(np.median([row["timings"][stage] for row in measured])) for stage in measured[0]["timings"]}
        by_category = {}
        for category in sorted({question_map[row["question_id"]].get("category", "unspecified") for row in first}):
            relevant = [row for row in answerable if question_map[row["question_id"]].get("category", "unspecified") == category]
            category_metrics = {}
            for name in ("recall_at10", "mrr_at10", "ndcg_at10", "hit_at1", "group_coverage_at3", "all_groups_at3", "all_groups_at5", "all_groups_at10"):
                values = [row["metrics"][name] for row in relevant if row["metrics"][name] is not None]
                category_metrics[name] = float(np.mean(values)) if values else None
            by_category[category] = {"positive_count": len(relevant), **category_metrics}
        aggregate["by_category"] = by_category
        scope_fractions = [row["wrong_scope_fraction_at10"] for row in first if row["wrong_scope_fraction_at10"] is not None]
        aggregate["wrong_scope_fraction_at10"] = float(np.mean(scope_fractions)) if scope_fractions else None
        aggregate["questions_with_scope_proxy"] = len(scope_fractions)
        stability = []
        for first_row in first:
            other = [row for row in measured if row["question_id"] == first_row["question_id"]]
            stability.append(all([p["id"] for p in row["ranking"]] == [p["id"] for p in first_row["ranking"]] for row in other))
        aggregate["identical_topk_across_repeats_fraction"] = float(np.mean(stability)) if stability else None
        output[method] = aggregate
    return output


def evaluate(args):
    process_started = time.perf_counter()
    directory = Path(args.index).resolve()
    manifest = read_json(directory / "index-manifest.json")
    protocol = read_json(directory / "protocol.json")
    if digest_json(protocol) != manifest["protocol_sha256"]:
        raise ValueError("Frozen protocol checksum mismatch")
    for name, artifact in manifest["artifacts"].items():
        if sha256_file(directory / name) != artifact["sha256"]:
            raise ValueError(f"Index artifact changed: {name}")
    if preparation_code_hash() != protocol["preparation_code_sha256"]:
        raise ValueError("Preparation algorithms changed after protocol freeze")
    if sorted(STOPWORDS) != protocol["lexical"]["stopwords"]:
        raise ValueError("Lexical tokenizer stopwords changed after protocol freeze")
    # Snapshot names alone do not prove immutable files: validate configurations
    # and weights again outside query measurements, before opening questions.
    for name in ("dense_model", "reranker_model"):
        if model_spec(protocol[name]["path"]) != protocol[name]:
            raise ValueError(f"Pinned local model files changed: {name}")
    # Evaluation code is frozen on the first development run, before holdout.
    # Index preparation may run while tests/review finish without re-encoding an
    # unchanged corpus if only presentation/evaluation defects are corrected.
    evaluation_protocol = {"schema": SCHEMA, "index_protocol_sha256": manifest["protocol_sha256"],
                           "evaluator_script_sha256": sha256_file(__file__), "repeats": protocol["repeats"],
                           "pool": protocol["pool"], "k": protocol["k"], "rrf_constant": protocol["rrf_constant"],
                           "max_length": protocol["max_length"], "negative_policy": "No abstention threshold, no score-as-confidence"}
    evaluation_protocol_path = directory / "evaluation-protocol.json"
    if evaluation_protocol_path.exists():
        if read_json(evaluation_protocol_path) != evaluation_protocol:
            raise ValueError("Evaluation harness changed after development/protocol freeze")
    elif args.split == "holdout":
        raise ValueError("Freeze evaluation protocol on development before opening holdout")
    else:
        atomic_json(evaluation_protocol_path, evaluation_protocol)
    questions = load_questions(args.questions, args.split)
    documents = [json.loads(line) for line in (directory / "documents.jsonl").read_text().splitlines() if line]
    known = {doc["id"] for doc in documents}
    for question in questions:
        if set(relevance_of(question)) - known or any(set(group) - known for group in groups_of(question)):
            raise ValueError(f"Gold evidence not in frozen corpus: {question['id']}")
        if len(groups_of(question)) and not relevance_of(question):
            raise ValueError("Evidence groups require positive judged evidence")
    results = directory / "results"
    results.mkdir(exist_ok=True)
    prefix = f"{args.split}-{args.mode}-firstpass"
    reservation, log_path = results / f"{prefix}-run.json", results / f"{prefix}.jsonl"
    identity = {"protocol_sha256": manifest["protocol_sha256"], "question_file_sha256": sha256_file(args.questions),
                "question_rows_sha256": digest_json(questions), "split": args.split, "mode": args.mode,
                "repeats": protocol["repeats"], "device": protocol["device"], "question_count": len(questions)}
    identity["evaluation_protocol_sha256"] = digest_json(evaluation_protocol)
    if reservation.exists():
        if not args.resume:
            raise ValueError("Immutable first pass already reserved; --resume only continues an interrupted identical run")
        previous = read_json(reservation)
        if any(previous.get(key) != value for key, value in identity.items()):
            raise ValueError("Cannot resume a different question/protocol/configuration")
        if (results / f"{prefix}-summary.json").exists():
            raise ValueError("Completed first pass cannot be overwritten")
    else:
        with reservation.open("x", encoding="utf-8") as stream:
            stream.write(canonical_json(identity | {"reserved_at": utc_now(), "environment": environment()}) + "\n")
    previous_rows = [json.loads(line) for line in log_path.read_text().splitlines() if line] if log_path.exists() else []
    done = {(row["question_id"], row["method"], row["repeat"]) for row in previous_rows}
    if len(done) != len(previous_rows):
        raise ValueError("Duplicate durable result rows")
    vectors = np.load(directory / "vectors.npy", mmap_mode="r", allow_pickle=False)
    lexical = BM25.load(directory)
    dense, reranker, model_timings = local_models(protocol, protocol["device"])
    index = RetrievalIndex(documents, lexical, vectors, dense, reranker,
                           protocol | {"reranker_batch_size": protocol["batch_size"]})
    init_seconds = time.perf_counter() - process_started
    if args.cold_dev_profile:
        if args.split != "dev":
            raise ValueError("Cold-init sample may only use development questions")
        sample = questions[0]
        allowed = supplied_scope(documents, sample, args.mode)
        cold = index.search(sample["question"], allowed, "rerank")
        profile_path = results / f"dev-{args.mode}-cold-init.json"
        if profile_path.exists():
            raise ValueError("Cold-init profile is immutable")
        atomic_json(profile_path, {"question_id": sample["id"], "model_load": model_timings, "process_init_seconds": init_seconds,
                                  "first_query": cold, "cache_note": "New Python process/model object; OS caches not controlled."})
    # A fixed, non-evaluation question warms every pipeline, explicitly excluded.
    warmup_started = time.perf_counter()
    warmup_allowed = np.arange(len(documents), dtype=np.int64)
    for method in METHODS:
        index.search("Quelle transmission et combien de rapports pour cette moto ?", warmup_allowed, method)
    warmup_seconds = time.perf_counter() - warmup_started
    rows = list(previous_rows)
    for repeat in range(protocol["repeats"]):
        for ordinal, question in enumerate(questions):
            allowed = supplied_scope(documents, question, args.mode)
            # Deterministic Latin rotation avoids a fixed privileged pipeline order.
            shift = (ordinal + repeat) % len(METHODS)
            order = METHODS[shift:] + METHODS[:shift]
            for method in order:
                if (question["id"], method, repeat) in done:
                    continue
                result = index.search(question["question"], allowed, method)
                ranked_ids = [row["id"] for row in result["ranking"]]
                expected = set(question.get("supplied_scope_object_ids", question.get("scope", {}).get("object_ids", [])))
                outside = sum(row["object_id"] not in expected for row in result["ranking"][:10]) if expected else 0
                row = result | {"question_id": question["id"], "question": question["question"], "category": question.get("category"),
                                "answerability": question.get("answerability"), "mode": args.mode, "method": method, "repeat": repeat,
                                "metrics": metrics(ranked_ids, question, protocol["k"]),
                                "wrong_scope_fraction_at10": outside / min(10, len(ranked_ids)) if ranked_ids and expected else None,
                                "expected_limits": question.get("expected_limits", []), "recorded_at": utc_now(),
                                "process_peak_memory_bytes": peak_memory_bytes()}
                append_json(log_path, row)
                rows.append(row)
                print(f"{args.split}/{args.mode} repeat {repeat + 1}: {question['id']} {method} {result['timings']['total_seconds']:.3f}s", flush=True)
    summary = {"schema": SCHEMA, "identity": identity, "completed_at": utc_now(), "model_load_timings": model_timings,
               "process_init_seconds": init_seconds, "warmup_seconds_excluded": warmup_seconds, "results": summarize(rows, questions),
               "environment_after": environment(), "query_cache": False, "result_cache": False,
               "remote_inference_calls": 0, "jev_calls": 0,
               "scope_interpretation": "Oracle-supplied evidence scope, not bot identity resolution" if args.mode == "supplied" else "Entire corpus, no scope injected",
               "limits": ["Retrieval only; no chat/A2 legal certification measured.",
                          "Global gold is incomplete unless explicitly fully judged: metrics describe known judged proofs, not exhaustive corpus truth.",
                          "Negative cases rank passages; no abstention threshold is calibrated and a result score is not a confidence.",
                          "P95 is descriptive on a small question set; repeats are not independent questions.",
                          "Model/index warmup excluded; OS cache coldness not claimed.",
                          "Wrong-scope fraction is an identity proxy; it may flag legitimate global alternatives."]}
    atomic_json(results / f"{prefix}-summary.json", summary)
    print(canonical_json({"summary": str(results / f"{prefix}-summary.json"), "results": summary["results"]}), flush=True)


def profile_lazy(args):
    """Development-only diagnostic of raw-section, per-fiche lazy embeddings.

    Mirrors the active encoder's float32/default length and source-text cache
    semantics in memory. SQL, identity resolution and chat are not measured.
    """
    output = Path(args.out)
    if output.exists():
        raise ValueError("Lazy diagnostic is immutable; choose a new output")
    protocol = read_json(Path(args.index) / "protocol.json")
    if model_spec(protocol["dense_model"]["path"]) != protocol["dense_model"]:
        raise ValueError("Pinned dense model changed")
    questions = load_questions(args.questions, "dev")
    selected, seen = [], set()
    for question in questions:
        scope = question.get("supplied_scope_object_ids", [])
        if question.get("split") == "dev" and len(scope) == 1 and relevance_of(question) and scope[0] not in seen:
            selected.append(question)
            seen.add(scope[0])
            if len(selected) == 3:
                break
    if not selected:
        raise ValueError("Lazy diagnostic requires explicit development single-fiche cases")
    if sha256_file(protocol["snapshot"]) != protocol["snapshot_sha256"]:
        raise ValueError("Frozen source snapshot changed")
    documents, _counts = documents_from_snapshot(protocol["snapshot"])
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                      HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
    from sentence_transformers import SentenceTransformer
    started = time.perf_counter()
    model = SentenceTransformer(protocol["dense_model"]["path"],
                                device=protocol["device"], local_files_only=True)
    load_seconds = time.perf_counter() - started
    observations = []
    for question in selected:
        scope = set(question["supplied_scope_object_ids"])
        texts = list(dict.fromkeys(d["original_text"] for d in documents if d["object_id"] in scope))
        started = time.perf_counter()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        document_seconds = time.perf_counter() - started
        # Every query is genuinely encoded; only source vectors are cached.
        search_seconds = []
        for _repeat in range(4):
            query_started = time.perf_counter()
            vector = model.encode([question["question"]], normalize_embeddings=True, show_progress_bar=False)[0]
            np.argsort(-(vectors @ vector))[:5]
            search_seconds.append(time.perf_counter() - query_started)
        observations.append({"question_id": question["id"], "unique_raw_sections": len(texts),
                             "document_encoding_seconds": document_seconds,
                             "first_source_miss_plus_query_seconds": document_seconds + search_seconds[0],
                             "source_cached_query_seconds": search_seconds[1:]})
    atomic_json(output, {"schema": SCHEMA, "created_at": utc_now(), "observations": observations,
                         "dense_load_seconds": load_seconds, "compute_dtype": "float32",
                         "max_length": model.max_seq_length, "device": str(model.device),
                         "dense_model": protocol["dense_model"], "dev_sha256": sha256_file(args.questions),
                         "environment": environment(), "remote_inference_calls": 0,
                         "limits": ["Encoder and exact in-memory dot product only; no SQL, identity resolution or chat.",
                                    "Each fiche starts with an assumed empty source cache, then three queries reuse source vectors; no cross-fiche or query cache. Independent of the canonical-index pipelines.",
                                    "A new model object is loaded; system file caches are not controlled."]})
    print(canonical_json({"lazy_profile": str(output), "observations": observations}), flush=True)


def parser():
    main = argparse.ArgumentParser(description=__doc__)
    commands = main.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    build.add_argument("--snapshot", required=True)
    build.add_argument("--out", required=True)
    build.add_argument("--dense-model", required=True, help="Pinned local snapshot directory")
    build.add_argument("--reranker-model", required=True, help="Pinned local snapshot directory")
    build.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    build.add_argument("--dtype", choices=("float32", "float16"), default="float32")
    build.add_argument("--batch-size", type=int, default=16)
    build.add_argument("--pool", type=int, default=30)
    build.add_argument("--k", type=int, default=10)
    build.add_argument("--rrf-constant", type=int, default=60)
    build.add_argument("--max-length", type=int, default=512)
    build.add_argument("--repeats", type=int, default=3)
    run = commands.add_parser("evaluate")
    run.add_argument("--questions", required=True)
    run.add_argument("--index", required=True)
    run.add_argument("--split", choices=("dev", "holdout"), required=True)
    run.add_argument("--mode", choices=("supplied", "global"), required=True)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--cold-dev-profile", action="store_true")
    lazy = commands.add_parser("profile-lazy", help="Development-only raw-source embedding diagnostic")
    lazy.add_argument("--questions", required=True)
    lazy.add_argument("--index", required=True)
    lazy.add_argument("--out", required=True)
    return main


def preparation_code_hash():
    # Representation/tokenization/encoding/checkpoint semantics are pinned even
    # when report-only code is completed while an isolated index is preparing.
    return hashlib.sha256("\n".join(inspect.getsource(part) for part in
                                  (documents_from_snapshot, tokenize, BM25, local_models,
                                   token_lengths, validate_checkpoint, prepare)).encode()).hexdigest()


def main():
    args = parser().parse_args()
    if args.command == "prepare":
        if min(args.batch_size, args.pool, args.k, args.rrf_constant, args.max_length, args.repeats) <= 0 or args.pool < args.k or args.k < 10:
            raise ValueError("Positive budgets, pool >= k >= 10, are required for frozen Recall@10")
        if args.dtype == "float16" and args.device != "mps":
            raise ValueError("FP16 is only supported by this harness on MPS")
        prepare(args)
    elif args.command == "profile-lazy":
        profile_lazy(args)
    else:
        evaluate(args)


if __name__ == "__main__":
    main()

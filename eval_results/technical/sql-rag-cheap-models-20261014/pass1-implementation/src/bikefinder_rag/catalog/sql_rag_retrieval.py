"""Frozen BM25/BGE retrieval with full source binding checked on startup."""
from collections import defaultdict
import json
import math
from pathlib import Path
import re

import numpy as np

from bikefinder_rag.catalog.enriched import folded
from bikefinder_rag.catalog.sql_rag_service import digest
from bikefinder_rag.embeddings.embedder import MODEL_REVISION

STOPWORDS = set("le la les un une des du de d l a au aux ce cette ces et est sont en pour sur dans quelle quel quelles quels the a an is are of to for on in what which".split())


def tokenize(text):
    # Same tokenizer as the frozen technical-retrieval benchmark v1.
    value = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?:\D|$))", "", folded(text))
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


class FrozenRetrieval:
    def __init__(self, directory, service, *, encoder=None):
        self.directory = Path(directory)
        manifest = json.loads((self.directory / "index-manifest.json").read_text())
        for name, artifact in manifest["artifacts"].items():
            if Path(name).name != name or digest(self.directory / name) != artifact["sha256"]:
                raise ValueError("Frozen retrieval file checksum mismatch")
        protocol = json.loads((self.directory / "protocol.json").read_text())
        # Find the revision in the frozen configuration without relying on a guessed key.
        if MODEL_REVISION not in json.dumps(protocol):
            raise ValueError("Frozen index embedding revision differs from local encoder")
        self.documents = [json.loads(line) for line in (self.directory / "documents.jsonl").open(encoding="utf-8")]
        expected = {r["id"]: r for r in service._sql("SELECT p.*,f.brand,f.model,f.year,f.source_url,f.source_sha256 FROM passages p JOIN fiches f ON f.id=p.object_id")}
        if len(expected) != len(self.documents):
            raise ValueError("Retrieval index does not cover the full current snapshot")
        seen = set()
        for d in self.documents:
            p = expected.get(d["id"])
            if p is None or d["id"] in seen or any(d[k] != p[k] for k in ["object_id", "section", "brand", "model", "year", "source_url", "source_sha256"]):
                raise ValueError("Indexed passage identity/source mismatch")
            if d["original_text"] != p["text"] or d["text"] != f"{p['brand']} {p['model']} {p['year']}\n{p['section']}\n{p['text']}":
                raise ValueError("Indexed passage differs from original source")
            seen.add(d["id"])
        self.lookup = {d["id"]: i for i, d in enumerate(self.documents)}
        self.vectors = np.load(self.directory / "vectors.npy", mmap_mode="r", allow_pickle=False)
        if self.vectors.shape != (len(self.documents), 1024):
            raise ValueError("Frozen vector shape mismatch")
        for start in range(0, len(self.vectors), 1024):
            vectors = self.vectors[start:start + 1024]
            if not np.all(np.isfinite(vectors)) or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-3):
                raise ValueError("Frozen vectors must be finite and normalized")
        metadata = json.loads((self.directory / "lexical-vocabulary.json").read_text())
        self.vocabulary, self.k1, self.b = metadata["terms"], metadata["k1"], metadata["b"]
        with np.load(self.directory / "lexical-postings.npz", allow_pickle=False) as arrays:
            self.offsets, self.postings, self.frequencies, self.lengths = (arrays[k] for k in ["offsets", "postings", "frequencies", "lengths"])
        if len(self.lengths) != len(self.documents) or len(self.offsets) != len(self.vocabulary) + 1 or self.offsets[-1] != len(self.postings) or len(self.postings) != len(self.frequencies):
            raise ValueError("Frozen lexical index shape mismatch")
        if self.offsets[0] != 0 or np.any(np.diff(self.offsets) < 0) or np.any(self.postings < 0) or np.any(self.postings >= len(self.documents)) or np.any(self.frequencies <= 0) or not np.all(np.isfinite(self.frequencies)) or np.any(self.lengths < 0):
            raise ValueError("Frozen lexical postings invalid")
        self.average_length = float(np.mean(self.lengths)) or 1
        if encoder is None:
            from bikefinder_rag.embeddings.embedder import embed_text
            encoder = embed_text
        self.encoder = encoder
        self.validated_passages = len(seen)

    def search(self, question, passage_ids, limit):
        allowed = np.array([self.lookup[p] for p in passage_ids], dtype=np.int64)
        if not len(allowed):
            return [], {"mode": "hybrid", "candidate_pool": 40, "rrf_constant": 60}
        scores = np.zeros(len(self.documents), dtype=np.float32)
        for term in set(tokenize(question)):
            token = self.vocabulary.get(term)
            if token is None:
                continue
            start, end = self.offsets[token:token + 2]
            ids, tf = self.postings[start:end], self.frequencies[start:end]
            idf = math.log(1 + (len(self.lengths) - (end - start) + .5) / ((end - start) + .5))
            scores[ids] += idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.lengths[ids] / self.average_length))
        lexical_order = np.lexsort((allowed, -scores[allowed]))[:40]
        # Zero-score documents are not literal evidence; exclude them from BM25 fusion.
        lexical = [int(allowed[i]) for i in lexical_order if scores[allowed[i]] > 0]
        query = np.asarray(self.encoder(question), dtype=np.float32)
        if query.shape != (1024,) or not np.all(np.isfinite(query)) or np.linalg.norm(query) < 1e-8:
            raise ValueError("Invalid local query embedding")
        query /= np.linalg.norm(query)
        dense_scores = self.vectors[allowed] @ query
        dense_order = np.lexsort((allowed, -dense_scores))[:40]
        dense = [int(allowed[i]) for i in dense_order]
        fused = defaultdict(float)
        for ranking in [lexical, dense]:
            for position, index in enumerate(ranking, 1):
                fused[index] += 1 / (60 + position)
        ranked = sorted(fused, key=lambda i: (-fused[i], i))[:limit]
        results = []
        for i in ranked:
            d = self.documents[i]
            results.append({k: d[k] for k in ["id", "object_id", "section", "brand", "model", "year", "source_url", "source_sha256"]} |
                           {"text": d["original_text"], "text_sha256": __import__("hashlib").sha256(d["original_text"].encode()).hexdigest(), "rrf_score": fused[i]})
        return results, {"mode": "hybrid", "candidate_pool": 40, "rrf_constant": 60, "ranked_candidate_count": len(fused), "matched_total": None}

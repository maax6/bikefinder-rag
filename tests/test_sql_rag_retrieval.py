from collections import Counter, defaultdict
import json

import numpy as np
import pytest

from test_sql_rag_service import service
from bikefinder_rag.catalog.sql_rag_retrieval import FrozenRetrieval, tokenize
from bikefinder_rag.catalog.sql_rag_service import digest
from bikefinder_rag.embeddings.embedder import MODEL_REVISION


def make_index(root, service):
    root.mkdir()
    docs = []
    for p in service._sql("SELECT p.*,f.brand,f.model,f.year,f.source_url,f.source_sha256 FROM passages p JOIN fiches f ON f.id=p.object_id ORDER BY p.id"):
        docs.append({**p, "original_text": p["text"], "text": f"{p['brand']} {p['model']} {p['year']}\n{p['section']}\n{p['text']}"})
    (root / "documents.jsonl").write_text("".join(json.dumps(d) + "\n" for d in docs))
    (root / "protocol.json").write_text(json.dumps({"revision": MODEL_REVISION}))
    vectors = np.zeros((len(docs), 1024), dtype=np.float32)
    vectors[:, 0] = 1
    np.save(root / "vectors.npy", vectors)
    postings = defaultdict(list)
    lengths = []
    for i, doc in enumerate(docs):
        terms = tokenize(doc["text"])
        lengths.append(len(terms))
        for word, count in Counter(terms).items():
            postings[word].append((i, count))
    offsets, ids, frequencies = [0], [], []
    vocabulary = {word: i for i, word in enumerate(sorted(postings))}
    for word in vocabulary:
        for i, count in postings[word]:
            ids.append(i)
            frequencies.append(count)
        offsets.append(len(ids))
    (root / "lexical-vocabulary.json").write_text(json.dumps({"terms": vocabulary, "k1": 1.2, "b": .75}))
    np.savez(root / "lexical-postings.npz", offsets=np.array(offsets), postings=np.array(ids), frequencies=np.array(frequencies), lengths=np.array(lengths))
    (root / "index-manifest.json").write_text(json.dumps({"artifacts": {p.name: {"sha256": digest(p)} for p in root.iterdir()}}))


def test_hybrid_filters_scope_before_rank_even_when_other_fiche_matches_query(service, tmp_path):
    root = tmp_path / "index"
    make_index(root, service)
    query = np.zeros(1024, dtype=np.float32)
    query[0] = 1
    index = FrozenRetrieval(root, service, encoder=lambda _: query)
    rows, metrics = index.search("DCT", ["b:section:0"], 8)
    assert [r["object_id"] for r in rows] == ["b"]
    assert rows[0]["text"] == "manuelle à 6 rapports"
    assert index.validated_passages == 3


def test_changed_index_text_is_rejected_even_if_manifest_is_rehashed(service, tmp_path):
    root = tmp_path / "index"
    make_index(root, service)
    p = root / "documents.jsonl"
    docs = [json.loads(line) for line in p.read_text().splitlines()]
    docs[0]["original_text"] = "Forged DCT claim"
    p.write_text("".join(json.dumps(d) + "\n" for d in docs))
    manifest = json.loads((root / "index-manifest.json").read_text())
    manifest["artifacts"][p.name]["sha256"] = digest(p)
    (root / "index-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="original source"):
        FrozenRetrieval(root, service, encoder=lambda _: np.ones(1024))

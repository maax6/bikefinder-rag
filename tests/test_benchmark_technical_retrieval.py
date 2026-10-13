"""Controlled evidence/measurement checks; no model, network or live DB required."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import numpy as np
import pytest


SPEC = importlib.util.spec_from_file_location("benchmark_technical_retrieval", Path(__file__).parents[1] / "scripts/benchmark_technical_retrieval.py")
retrieval = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = retrieval
SPEC.loader.exec_module(retrieval)


def document(object_id, year, text, section="Transmission", ordinal=0):
    return {"id": f"{object_id}:section:{ordinal}", "object_id": object_id, "brand": "Honda", "model": "CB500F",
            "year": year, "section": section, "source_url": f"https://source.invalid/{object_id}",
            "original_text": text, "text": f"Honda CB500F {year}\n{section}\n{text}"}


def question(gold=None, groups=None, scope=None):
    return {"id": "q1", "split": "dev", "question": "La transmission de la Honda CB500F 2020 ?",
            "category": "facts", "answerability": "answerable", "supplied_scope_object_ids": scope or ["old"],
            "gold_passages": [{"id": key, "grade": grade} for key, grade in (gold or {}).items()],
            "required_groups": groups or []}


class FakeTokenizer:
    def __call__(self, texts, pairs=None, **kwargs):
        if pairs is None:
            return {"input_ids": [[0] * (len(text.split()) + 2) for text in texts]}
        return {"input_ids": [[0] * (len(text.split()) + len(pair.split()) + 3) for text, pair in zip(texts, pairs)]}


class FakeDense:
    def __init__(self):
        self.tokenizer = FakeTokenizer()
        self.calls = []

    def encode(self, texts, **kwargs):
        self.calls.extend(texts)
        return np.asarray([[1, 0] for _text in texts], dtype=np.float32)


class FakeReranker:
    def __init__(self):
        self.tokenizer = FakeTokenizer()
        self.calls = []

    def predict(self, pairs, **kwargs):
        self.calls.append(pairs)
        return np.asarray([3 if "cardan" in text else 1 for _query, text in pairs])


@pytest.fixture
def fake_index():
    docs = [document("old", 2020, "Secondaire par chaîne, boîte 6 rapports"),
            document("new", 2021, "Secondaire par cardan, boîte 6 rapports"),
            document("other", 2020, "Réservoir : 15 litres", "Châssis")]
    vectors = np.asarray([[.8, .6], [1, 0], [0, 1]], dtype=np.float32)
    dense, reranker = FakeDense(), FakeReranker()
    return retrieval.RetrievalIndex(docs, retrieval.BM25.build([doc["text"] for doc in docs]), vectors,
                                   dense, reranker, {"pool": 30, "k": 10, "rrf_constant": 60, "max_length": 512,
                                                     "reranker_batch_size": 2})


def test_lexical_normalizes_accents_codes_decimals_and_preserves_qualifications(tmp_path):
    assert "equipement" in retrieval.tokenize("Équipement")
    assert {"mt07", "mt", "07"} <= set(retrieval.tokenize("MT-07"))
    assert "cb500f" in retrieval.tokenize("CB500F")
    assert {"1084", "35.5"} <= set(retrieval.tokenize("1 084 cc et 35,5 kW"))
    assert {"sans", "non", "avec", "option"} <= set(retrieval.tokenize("sans ABS, non certifié, avec option"))
    bm25 = retrieval.BM25.build(["MT-07 Équipement : ABS de série", "CB500F Équipement : ABS en option"])
    bm25.save(tmp_path)
    loaded = retrieval.BM25.load(tmp_path)
    scores = loaded.scores("mt07 equipement ABS")
    assert scores[0] > scores[1]
    assert np.array_equal(scores, bm25.scores("mt07 equipement ABS"))
    assert not list(tmp_path.glob("*.tmp"))


def test_stable_source_ids_verbatim_text_and_read_only_snapshot(tmp_path):
    path = tmp_path / "snapshot.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE objects(id TEXT,url TEXT,brand TEXT,model TEXT,year INT,source_sha256 TEXT,record TEXT)")
        raw = {"spec_rows": [{"label": "Transmission", "value": "Chaîne"}], "technical_sections": [
            {"section": "Châssis", "text": ""}, {"section": "Transmission", "text": "  Secondaire : chaîne; non disponible en option. "}]}
        conn.execute("INSERT INTO objects VALUES(?,?,?,?,?,?,?)", ("obj", "https://source.invalid", "Honda", "CB500F", 2020, "hash", json.dumps(raw)))
    before = retrieval.sha256_file(path)
    docs, counts = retrieval.documents_from_snapshot(path)
    assert retrieval.sha256_file(path) == before
    assert counts == {"objects": 1, "spec_rows": 1, "passages": 1, "empty_sections": 1}
    assert docs[0]["id"] == "obj:section:1"
    assert docs[0]["original_text"] == "  Secondaire : chaîne; non disponible en option. "
    assert docs[0]["text"] == "Honda CB500F 2020\nTransmission\n" + docs[0]["original_text"]


def test_supplied_scope_is_identical_for_four_methods_without_year_relaxation(fake_index):
    q = question({"old:section:0": 3})
    allowed = retrieval.supplied_scope(fake_index.documents, q, "supplied")
    assert list(allowed) == [0]
    for method in retrieval.METHODS:
        result = fake_index.search(q["question"], allowed, method)
        assert [item["id"] for item in result["ranking"]] == ["old:section:0"]
        assert result["ranking"][0]["year"] == 2020
    with pytest.raises(ValueError, match="Unknown supplied"):
        retrieval.supplied_scope(fake_index.documents, q | {"supplied_scope_object_ids": ["missing"]}, "supplied")
    empty = retrieval.supplied_scope(fake_index.documents, q | {"supplied_scope_object_ids": []}, "supplied")
    assert all(fake_index.search(q["question"], empty, method)["ranking"] == [] for method in retrieval.METHODS)


def test_global_does_not_inject_gold_scope_and_pipeline_encoding_is_not_reused(fake_index):
    q = question({"old:section:0": 3})
    allowed = retrieval.supplied_scope(fake_index.documents, q, "global")
    assert list(allowed) == [0, 1, 2]
    outputs = {method: fake_index.search(q["question"], allowed, method) for method in retrieval.METHODS}
    assert outputs["dense"]["ranking"][0]["object_id"] == "new"  # closer wrong-year evidence remains visible
    assert fake_index.dense.calls == [q["question"]] * 3
    assert outputs["hybrid"]["candidate_ids"] == outputs["rerank"]["candidate_ids"]
    assert all(pair[0] == q["question"] for pair in fake_index.reranker.calls[0])
    doc_map = {doc["id"]: doc for doc in fake_index.documents}
    assert [pair[1] for pair in fake_index.reranker.calls[0]] == [doc_map[doc_id]["text"] for doc_id in outputs["hybrid"]["candidate_ids"]]
    for result in outputs.values():
        assert result["timings"]["total_seconds"] >= sum(value for name, value in result["timings"].items() if name != "total_seconds")
        assert result["pair_truncations"] == 0


def test_rrf_reorders_shared_evidence_with_stable_ties():
    result = retrieval.reciprocal_rank_fusion([[(1, 100), (0, 1)], [(2, .9), (0, .8)]], 60, 30)
    assert [idx for idx, _score in result] == [0, 1, 2]
    assert result[0][1] == pytest.approx(2 / 62)


def test_metrics_distinguish_hit_recall_grades_and_multi_group_alternatives():
    q = question({"a": 3, "a-alternative": 3, "b": 1}, [["a", "a-alternative"], ["b"]])
    result = retrieval.metrics(["wrong", "a", "b"], q)
    assert result["hit_at1"] == 0
    assert result["hit_at3"] == 1
    assert result["recall_at3"] == pytest.approx(2 / 3)
    assert result["mrr_at10"] == .5
    assert result["group_coverage_at10"] == 1
    assert result["all_groups_at10"] == 1
    assert result["group_coverage_at1"] == 0
    assert result["group_coverage_at3"] == 1
    assert result["all_groups_at3"] == 1
    expected_dcg = 7 / np.log2(3) + 1 / np.log2(4)
    ideal = 7 + 7 / np.log2(3) + 1 / np.log2(4)
    assert result["ndcg_at10"] == pytest.approx(expected_dcg / ideal)
    assert retrieval.metrics(["a"], q)["group_coverage_at10"] == .5
    rank11 = retrieval.metrics([f"wrong{i}" for i in range(10)] + ["a"], q, k=20)
    assert rank11["mrr_at10"] == rank11["ndcg_at10"] == rank11["recall_at10"] == 0


def test_negative_cases_have_no_fabricated_recall_and_judged_zero_not_unjudged():
    result = retrieval.metrics(["known-irrelevant", "unknown"], question({"known-irrelevant": 0}))
    assert result["recall_at10"] is None
    assert result["hit_at10"] is None
    assert result["mrr_at10"] is None
    assert result["ndcg_at10"] is None
    assert result["unjudged_fraction_at10"] == .5
    assert result["judgements_complete_global"] is False


@pytest.mark.parametrize("gold,groups", [({"a": -1}, []), ({"a": float("nan")}, []), ({"a": float("inf")}, []),
                                         ({"a": 3}, [["outside"]]), ({"a": 0}, [["a"]])])
def test_invalid_annotations_fail_before_inference(tmp_path, gold, groups):
    path = tmp_path / "dev.json"
    path.write_text(json.dumps({"questions": [question(gold, groups)]}))
    with pytest.raises(ValueError):
        retrieval.load_questions(path, "dev")


def test_duplicate_gold_ids_are_rejected(tmp_path):
    q = question({"a": 3})
    q["gold_passages"].append({"id": "a", "grade": 1})
    path = tmp_path / "dev.json"
    path.write_text(json.dumps({"questions": [q]}))
    with pytest.raises(ValueError, match="Duplicate gold"):
        retrieval.load_questions(path, "dev")


def test_resume_checkpoint_requires_matching_identity_valid_normalized_prefix():
    vectors = np.asarray([[1, 0], [0, 1], [.6, .8]], dtype=np.float32)
    checkpoint = {"protocol_sha256": "p", "documents_sha256": "d", "completed": 2,
                  "batches": [{"start": 0, "end": 2, "sha256": hashlib.sha256(vectors[:2].tobytes()).hexdigest()}]}
    assert retrieval.validate_checkpoint(checkpoint, "p", "d", vectors) == 2
    with pytest.raises(ValueError, match="protocol/corpus mismatch"):
        retrieval.validate_checkpoint(checkpoint, "changed", "d", vectors)
    modified = vectors.copy()
    modified[0] = [0, 1]
    with pytest.raises(ValueError, match="checksum mismatch"):
        retrieval.validate_checkpoint(checkpoint, "p", "d", modified)
    with pytest.raises(ValueError, match="offset disagrees"):
        retrieval.validate_checkpoint(checkpoint | {"completed": 3}, "p", "d", vectors)
    corrupted = vectors.copy()
    corrupted[0] *= 2
    checkpoint["batches"][0]["sha256"] = hashlib.sha256(corrupted[:2].tobytes()).hexdigest()
    with pytest.raises(ValueError, match="unnormalised"):
        retrieval.validate_checkpoint(checkpoint, "p", "d", corrupted)


def test_local_model_loading_forbids_network_and_pins_device_dtype_and_length(monkeypatch):
    calls = []

    class FakeModel:
        def __init__(self, path, **kwargs):
            calls.append((path, kwargs))
            self.model = self
            self.halved = False

        def half(self):
            self.halved = True

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=FakeModel, CrossEncoder=FakeModel))
    protocol = {"dense_model": {"path": "/local/dense/revision"}, "reranker_model": {"path": "/local/reranker/revision"},
                "max_length": 512, "inference_dtype": "float16"}
    dense, reranker, timings = retrieval.local_models(protocol, "mps")
    assert calls == [("/local/dense/revision", {"device": "mps", "local_files_only": True}),
                     ("/local/reranker/revision", {"device": "mps", "max_length": 512, "local_files_only": True})]
    assert dense.halved and reranker.halved and dense.max_seq_length == 512
    assert retrieval.os.environ["HF_HUB_OFFLINE"] == retrieval.os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert retrieval.os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert all(value >= 0 for value in timings.values())


def test_overlong_query_and_pair_fail_instead_of_silent_truncation(fake_index):
    fake_index.protocol["max_length"] = 5
    with pytest.raises(ValueError, match="Query exceeds"):
        fake_index.search("this question has too many words", [0], "dense")
    fake_index.protocol["max_length"] = 8
    with pytest.raises(ValueError, match="Rerank pairs exceed"):
        fake_index.search("transmission", [0], "rerank")


def test_empty_unknown_model_directories_do_not_trigger_download(tmp_path):
    with pytest.raises(ValueError, match="No local model weights"):
        retrieval.model_spec(tmp_path)


def test_latency_repeats_do_not_inflate_quality_question_count():
    q = question({"a": 3})
    rows = []
    for repeat, seconds in enumerate([1, 2, 3]):
        rows.append({"question_id": q["id"], "method": "dense", "repeat": repeat,
                     "ranking": [{"id": "a"}], "metrics": retrieval.metrics(["a"], q),
                     "timings": {"total_seconds": seconds, "query_encoding_seconds": .5},
                     "wrong_scope_fraction_at10": 0})
    result = retrieval.summarize(rows, [q])["dense"]
    assert result["question_count"] == 1
    assert result["latency_observations"] == 3
    assert result["recall_at10"] == 1
    assert result["latency_seconds"]["median"] == 2
    assert result["identical_topk_across_repeats_fraction"] == 1


def write_fake_index(tmp_path, fake_index, monkeypatch):
    """A full CLI index contract built without importing any actual model."""
    monkeypatch.setattr(retrieval, "local_models", lambda protocol, device, **kwargs: (fake_index.dense, fake_index.reranker,
                                                                                   {"dense_load_seconds": 0, "reranker_load_seconds": 0}))
    monkeypatch.setattr(retrieval, "model_spec", lambda path: {"path": path, "content_sha256": "fake-model"})
    directory = tmp_path / "index"
    directory.mkdir()
    protocol = fake_index.protocol | {"schema": retrieval.SCHEMA, "device": "cpu", "batch_size": 2, "repeats": 2,
                                     "preparation_code_sha256": retrieval.preparation_code_hash(),
                                     "lexical": {"stopwords": sorted(retrieval.STOPWORDS)},
                                     "dense_model": {"path": "/local/dense", "content_sha256": "fake-model"},
                                     "reranker_model": {"path": "/local/reranker", "content_sha256": "fake-model"}}
    retrieval.atomic_json(directory / "protocol.json", protocol)
    (directory / "documents.jsonl").write_text("\n".join(retrieval.canonical_json(doc) for doc in fake_index.documents) + "\n")
    np.save(directory / "vectors.npy", fake_index.vectors)
    fake_index.lexical.save(directory)
    artifacts = {name: {"sha256": retrieval.sha256_file(directory / name)} for name in
                 ("protocol.json", "documents.jsonl", "vectors.npy", "lexical-vocabulary.json", "lexical-postings.npz")}
    retrieval.atomic_json(directory / "index-manifest.json", {"protocol_sha256": retrieval.digest_json(protocol), "artifacts": artifacts})
    questions_path = tmp_path / "questions.json"
    questions_path.write_text(json.dumps({"questions": [question({"old:section:0": 3}, [["old:section:0"]])]}))
    args = SimpleNamespace(index=str(directory), questions=str(questions_path), split="dev", mode="supplied",
                           resume=False, cold_dev_profile=False)
    return directory, args


def test_end_to_end_fake_measurement_is_immutable_and_freezes_before_holdout(tmp_path, fake_index, monkeypatch):
    directory, args = write_fake_index(tmp_path, fake_index, monkeypatch)
    retrieval.evaluate(args)
    assert (directory / "evaluation-protocol.json").exists()
    log_path = directory / "results/dev-supplied-firstpass.jsonl"
    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(rows) == 8
    assert all(row["question"] == question()["question"] for row in rows)
    assert {row["method"] for row in rows} == set(retrieval.METHODS)
    assert all(row["metrics"]["hit_at1"] == 1 for row in rows)
    summary = retrieval.read_json(directory / "results/dev-supplied-firstpass-summary.json")
    assert summary["remote_inference_calls"] == summary["jev_calls"] == 0
    assert summary["results"]["dense"]["question_count"] == 1
    assert summary["results"]["dense"]["latency_observations"] == 2
    with pytest.raises(ValueError, match="Immutable first pass"):
        retrieval.evaluate(args)
    args.resume = True
    with pytest.raises(ValueError, match="Completed first pass"):
        retrieval.evaluate(args)
    # A modified source artifact is rejected even before new models/query runs.
    (directory / "documents.jsonl").write_text(log_path.read_text())
    with pytest.raises(ValueError, match="Index artifact changed"):
        retrieval.evaluate(args)


def test_resumption_never_rewrites_completed_measurement_rows(tmp_path, fake_index, monkeypatch):
    directory, args = write_fake_index(tmp_path, fake_index, monkeypatch)
    original_search = retrieval.RetrievalIndex.search
    counter = {"calls": 0, "fail": True}

    def interrupted_search(self, question_text, allowed, method):
        counter["calls"] += 1
        if counter["calls"] == 6 and counter["fail"]:
            raise RuntimeError("controlled process interruption")
        return original_search(self, question_text, allowed, method)

    monkeypatch.setattr(retrieval.RetrievalIndex, "search", interrupted_search)
    with pytest.raises(RuntimeError, match="controlled process interruption"):
        retrieval.evaluate(args)
    log_path = directory / "results/dev-supplied-firstpass.jsonl"
    durable_prefix = log_path.read_text()
    assert len(durable_prefix.splitlines()) == 1
    counter["fail"] = False
    args.resume = True
    retrieval.evaluate(args)
    assert log_path.read_text().startswith(durable_prefix)
    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(rows) == len({(row["question_id"], row["method"], row["repeat"]) for row in rows}) == 8


def test_holdout_cannot_be_opened_before_evaluation_protocol_freeze(tmp_path, fake_index, monkeypatch):
    directory, args = write_fake_index(tmp_path, fake_index, monkeypatch)
    args.split = "holdout"
    with pytest.raises(ValueError, match="Freeze evaluation protocol"):
        retrieval.evaluate(args)
    assert not (directory / "results").exists()


@pytest.mark.parametrize("changed_path", ["/local/dense", "/local/reranker"])
def test_mutated_model_files_are_rejected_before_questions_or_measurements(tmp_path, fake_index, monkeypatch, changed_path):
    directory, args = write_fake_index(tmp_path, fake_index, monkeypatch)
    monkeypatch.setattr(retrieval, "model_spec", lambda path: {"path": path, "content_sha256": "mutated" if path == changed_path else "fake-model"})
    # A nonexistent question file establishes that model validation happens first.
    args.questions = str(tmp_path / "unopened-questions.json")
    with pytest.raises(ValueError, match="Pinned local model files changed"):
        retrieval.evaluate(args)
    assert not fake_index.dense.calls
    assert not fake_index.reranker.calls
    assert not (directory / "results").exists()


@pytest.mark.parametrize("invalid_input", ["changed-source", "reserved-questions"])
def test_lazy_diagnostic_rejects_invalid_provenance_before_document_or_model_loading(tmp_path, monkeypatch, invalid_input):
    snapshot = tmp_path / "snapshot.sqlite3"
    snapshot.write_bytes(b"frozen source")
    protocol = {"snapshot": str(snapshot), "snapshot_sha256": retrieval.sha256_file(snapshot),
                "dense_model": {"path": "/local/pinned"}}
    if invalid_input == "changed-source":
        snapshot.write_bytes(b"changed source")
    (tmp_path / "protocol.json").write_text(json.dumps(protocol))
    row = question({"old:section:0": 2})
    if invalid_input == "reserved-questions":
        row["split"] = "holdout"
    questions_path = tmp_path / "questions.json"
    questions_path.write_text(json.dumps({"questions": [row]}))
    monkeypatch.setattr(retrieval, "model_spec", lambda _path: protocol["dense_model"])
    monkeypatch.setattr(retrieval, "documents_from_snapshot", lambda _path: pytest.fail("Invalid source reached encoding preparation"))
    args = SimpleNamespace(index=str(tmp_path), questions=str(questions_path), out=str(tmp_path / "profile.json"))
    expected = "Frozen source snapshot changed" if invalid_input == "changed-source" else "non-empty"
    with pytest.raises(ValueError, match=expected):
        retrieval.profile_lazy(args)
    assert not Path(args.out).exists()

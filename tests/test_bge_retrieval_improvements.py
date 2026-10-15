"""Experiment safeguards: baseline fidelity, no truncation and split isolation."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture
def experiment(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("bge_improvement_experiment", scripts / "improve_bge_retrieval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_index(tmp_path, experiment):
    documents = [{"id": f"p{i}", "object_id": f"f{i}", "text": text, "original_text": text,
                  "section": "test", "brand": "test", "model": "test", "year": 2024,
                  "source_url": "https://example.com", "source_sha256": "fixture"}
                 for i, text in enumerate(["nothing", "unrelated", "requested"])]
    vectors = np.zeros((3, 1024), dtype=np.float32)
    vectors[:, 0] = [.9, .85, .4]
    vectors[:, 1] = np.sqrt(1 - vectors[:, 0] ** 2)
    query = np.zeros(1024, dtype=np.float32)
    query[0] = 1
    lexical = experiment.BM25.build([d["text"] for d in documents])
    lexical.save(tmp_path)
    return SimpleNamespace(directory=tmp_path, documents=documents, vectors=vectors,
                           encoder=lambda text: query), lexical


def test_experimental_baseline_matches_real_service_and_excludes_zero_lexical_scores(tmp_path, experiment):
    from bikefinder_rag.catalog.sql_rag_retrieval import FrozenRetrieval
    index, lexical = fixture_index(tmp_path, experiment)
    current = FrozenRetrieval.__new__(FrozenRetrieval)
    current.__dict__.update(index.__dict__)
    current.lookup = {d["id"]: i for i, d in enumerate(index.documents)}
    current.vocabulary = lexical.vocabulary
    for attr in ["offsets", "postings", "frequencies", "lengths", "k1", "b", "average_length"]:
        setattr(current, attr, getattr(lexical, attr))
    expected, _ = current.search("requested", list(current.lookup), 10)
    result = experiment.Search(index, None).query("requested", experiment.CONFIGS[1])
    assert [p["id"] for p in result["ranking"]] == [p["id"] for p in expected]
    assert result["ranking"][0]["id"] == "p2"


def test_reranker_rejects_long_pairs_before_predict(tmp_path, experiment):
    index, _ = fixture_index(tmp_path, experiment)

    def forbidden(*args, **kwargs):
        raise AssertionError("Truncated pairs must never reach prediction")

    reranker = SimpleNamespace(tokenizer=lambda *args, **kwargs: {"input_ids": [[0] * 513]}, predict=forbidden)
    with pytest.raises(ValueError, match="truncated"):
        experiment.Search(index, reranker).query("requested", experiment.CONFIGS[-1])


def test_brand_overlap_refuses_a_leaking_verification_split(experiment):
    cases = [{"split": split, "expected_identities": [{"brand": "Honda"}]} for split in ["dev", "check"]]
    with pytest.raises(ValueError, match="share brands"):
        experiment.brand_partition(cases)


def test_top10_reranking_preserves_the_whole_retrieved_proof_set(tmp_path, experiment):
    index, _ = fixture_index(tmp_path, experiment)
    baseline = experiment.Search(index, None).query("requested", experiment.CONFIGS[1])
    reranker = SimpleNamespace(tokenizer=lambda *args, **kwargs: {"input_ids": [[1], [1], [1]]},
                               predict=lambda *args, **kwargs: np.array([0, 1, 2]))
    reordered = experiment.Search(index, reranker).query("requested", experiment.PRESERVING_CONFIGS[2])
    before = [p["id"] for p in baseline["ranking"]]
    after = [p["id"] for p in reordered["ranking"]]
    assert set(after) == set(before)
    assert after != before


def test_choice_prioritizes_complete_evidence_over_one_good_first_passage(experiment):
    rows = [dict(config="incomplete", all_groups_at10=.5, hit_at1=1, ndcg_at10=1, median_seconds=.1),
            dict(config="complete", all_groups_at10=1, hit_at1=.8, ndcg_at10=.8, median_seconds=.5)]
    assert experiment.select_config(rows)["config"] == "complete"

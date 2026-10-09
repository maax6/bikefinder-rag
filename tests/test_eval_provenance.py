import copy
import json

import pytest

from bikefinder_rag.eval.provenance import (
    CacheMismatchError, corpus_snapshot, dated_report_path, generation_identity,
    load_answers_cache, ollama_model_identity, save_answers_cache,
)


def manifest():
    return {
        "created_at_utc": "2026-10-10T12:00:00+00:00",
        "git": {"sha": "abc", "dirty": False},
        "python": "3.11.9", "judge_model": "local-judge",
        "generation": {"backend": "ollama", "model": "small:latest", "digest": "digest-a",
                       "system_prompt_sha256": "prompt-a", "tool_schema_sha256": "tools-a"},
        "corpus": {"review_chunks": {"rows": 3, "rows_md5": "corpus-a"}},
        "retrieval": {"reranker_enabled": True},
        "implementation_sha256": {"agent/tools.py": "code-a"},
        "package_versions": {"requests": "2.32", "ragas": "0.4"},
    }


ROWS = [{"question": "Any reviews?", "answer": "A dated owner report.",
         "contexts": ["Owner report"], "generated_at_utc": "2026-10-09T12:00:00+00:00"}]


def test_rejudging_reuses_answers_and_their_original_generation_date(tmp_path):
    old = manifest()
    cache = tmp_path / "answers.json"
    save_answers_cache(cache, generation_identity(old), ROWS)
    new = copy.deepcopy(old)
    new.update(judge_model="another-judge", created_at_utc="2026-10-11T12:00:00+00:00",
               git={"sha": "docs-only-change", "dirty": True})
    new["package_versions"]["ragas"] = "0.5"
    assert load_answers_cache(cache, generation_identity(new)) == ROWS


@pytest.mark.parametrize("section,field,value", [
    ("generation", "model", "another-model"),
    ("generation", "digest", "updated-same-model-tag"),
    ("generation", "backend", "anthropic"),
    ("generation", "system_prompt_sha256", "new-prompt"),
    ("generation", "tool_schema_sha256", "new-tools"),
    ("retrieval", "reranker_enabled", False),
    ("implementation_sha256", "agent/tools.py", "changed-filtering"),
])
def test_changed_generator_cannot_relabel_cached_answers(tmp_path, section, field, value):
    old = manifest()
    cache = tmp_path / "answers.json"
    save_answers_cache(cache, generation_identity(old), ROWS)
    new = copy.deepcopy(old)
    new[section][field] = value
    with pytest.raises(CacheMismatchError, match="--regenerate"):
        load_answers_cache(cache, generation_identity(new))
    assert load_answers_cache(cache, generation_identity(new), regenerate=True) == []


def test_same_size_corpus_with_changed_content_invalidates_cache(tmp_path):
    old = manifest()
    cache = tmp_path / "answers.json"
    save_answers_cache(cache, generation_identity(old), ROWS)
    new = copy.deepcopy(old)
    new["corpus"]["review_chunks"]["rows_md5"] = "changed-vector-or-review"
    with pytest.raises(CacheMismatchError, match="corpus.*--regenerate"):
        load_answers_cache(cache, generation_identity(new))


def test_unversioned_cache_requires_explicit_regeneration(tmp_path):
    cache = tmp_path / "answers.json"
    cache.write_text(json.dumps(ROWS))
    with pytest.raises(CacheMismatchError, match="Legacy.*--regenerate"):
        load_answers_cache(cache, generation_identity(manifest()))
    assert load_answers_cache(cache, generation_identity(manifest()), regenerate=True) == []


def test_failed_cache_replacement_preserves_previous_answers(tmp_path, monkeypatch):
    cache = tmp_path / "answers.json"
    identity = generation_identity(manifest())
    save_answers_cache(cache, identity, ROWS)
    previous = cache.read_text()
    def fail_replace(*_):
        raise OSError("simulated interruption")
    monkeypatch.setattr(type(cache), "replace", fail_replace)
    with pytest.raises(OSError):
        save_answers_cache(cache, identity, [])
    assert cache.read_text() == previous
    assert list(tmp_path.iterdir()) == [cache]


def test_ollama_tag_resolves_to_digest_without_generating(monkeypatch):
    import requests

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "small:latest", "digest": "model-content"}]}

    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return Response()
    monkeypatch.setattr(requests, "get", get)
    assert ollama_model_identity("small", "http://localhost:11434/")["digest"] == "model-content"
    assert calls == ["http://localhost:11434/api/tags"]


def test_new_report_leaves_historical_report_intact(tmp_path):
    old = tmp_path / "retrieval_report.json"
    old.write_text("historical result")
    new = dated_report_path(tmp_path, "retrieval_report", "2026-10-10T12:00:00+00:00")
    new.write_text("new result")
    assert new != old
    assert old.read_text() == "historical result"


def test_corpus_snapshot_hashes_every_data_layer_and_reports_language_counts():
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, sql):
            self.sql = sql
            assert "UPDATE " not in sql and "INSERT " not in sql

        def fetchone(self):
            if "server_version" in self.sql:
                return "17.6", "0.8.1"
            assert "to_jsonb(t)" in self.sql  # includes vector/spec/enrichment values
            assert "ORDER BY id" in self.sql
            return 3, 9, "checksum"

        def fetchall(self):
            return [("en", "bikez", 2), ("fr", "motoplanete", 1)]

    class Connection:
        def cursor(self):
            return Cursor()

    snapshot = corpus_snapshot(Connection())
    assert set(snapshot) >= {"motorcycles", "model_families", "review_chunks",
                             "recalls", "used_price_estimates"}
    assert snapshot["review_languages"][1] == {"lang": "fr", "source": "motoplanete", "rows": 1}

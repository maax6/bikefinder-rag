from scripts import eval_retrieval as evaluation


class Cursor:
    def __init__(self, cases):
        self.cases = cases

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, params):
        case = self.cases[params[0][0]]
        if "WHERE id =" in sql:
            self.one = (case["own"],)
        elif "LIMIT 10" in sql:
            self.many = case["ann"]
        elif "+ 0, id" in sql:
            self.one = case["exact"]
        elif "count(*) + 1" in sql:
            self.one = (case["rank"],)
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class Connection:
    def __init__(self, cases):
        self.cases = cases

    def cursor(self):
        return Cursor(self.cases)


def sample(monkeypatch, ids):
    def fetchall(conn, sql, params):
        assert "ORDER BY md5" in sql and "random()" not in sql
        return [{"id": item, "comment_text": str(item)} for item in ids]
    monkeypatch.setattr(evaluation, "fetchall", fetchall)
    monkeypatch.setattr(evaluation, "embed_texts", lambda texts: [[int(t)] for t in texts])


def test_failures_distinguish_stored_vector_mismatch_from_ann_miss(monkeypatch):
    sample(monkeypatch, [7, 9])
    conn = Connection({
        7: {"own": 0.05, "ann": [(8, 0.02), (7, 0.05)], "exact": (8, 0.02), "rank": 2},
        9: {"own": 0.0, "ann": [(8, 0.1)], "exact": (9, 0.0), "rank": 1},
    })
    result = evaluation.self_retrieval_test(conn)
    assert result["sample_size"] == 2
    assert result["rank1_hits"] == 0
    assert result["avg_self_distance"] == 0.025  # own vectors, not unrelated ANN top-1
    assert [f["reason"] for f in result["failures"]] == ["stored_embedding_mismatch", "approximate_search_miss"]
    assert result["failures"][1]["exact_rank_allowing_distance_ties"] == 1
    assert result["failures"][1]["id"] == 9


def test_equal_distance_different_id_is_reported_as_a_tie(monkeypatch):
    sample(monkeypatch, [7])
    conn = Connection({7: {"own": 0.0, "ann": [(6, 0.0), (7, 0.0)],
                           "exact": (6, 0.0), "rank": 1}})
    result = evaluation.self_retrieval_test(conn, sample_size=1)
    assert result["rank1_hits"] == 0  # preserves strict historical ID metric
    assert result["failures"][0]["reason"] == "distance_tie"


def test_correct_top_id_does_not_hide_a_changed_embedding(monkeypatch):
    sample(monkeypatch, [7])
    conn = Connection({7: {"own": 0.05, "ann": [(7, 0.05)],
                           "exact": (7, 0.05), "rank": 1}})
    result = evaluation.self_retrieval_test(conn, sample_size=1)
    assert result["rank1_hits"] == 1
    assert result["stored_vector_mismatches"] == 1
    assert result["failures"][0]["reason"] == "stored_embedding_mismatch"


def test_empty_self_retrieval_has_no_spurious_perfect_score(monkeypatch):
    sample(monkeypatch, [])
    result = evaluation.self_retrieval_test(Connection({}))
    assert result["sample_size"] == 0
    assert result["rank1_hit_rate"] is None


def test_negative_control_compares_with_actual_topic_distance(monkeypatch):
    monkeypatch.setattr(evaluation, "NEGATIVE_QUERIES", ["cake recipe"])
    monkeypatch.setattr(evaluation, "semantic_search", lambda *args: [
        {"brand": "Honda", "model": "CB", "comment_text": "A comment", "distance": 0.4}
    ])
    assert not evaluation.negative_control_test(None, 0.5)[0]["worse_than_on_topic_avg"]
    assert evaluation.negative_control_test(None, 0.2)[0]["worse_than_on_topic_avg"]

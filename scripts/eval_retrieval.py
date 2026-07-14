#!/usr/bin/env python3
"""Prove the retrieval layer works, independent of any LLM.

No Anthropic, no Ollama, no agent loop — just pgvector + BGE-M3 embeddings,
so retrieval quality can be judged on its own instead of being confounded
with how well an LLM writes an answer from whatever it got back.

Four tests, in order of "does the plumbing even work" to "is it actually
semantically useful":

1. Data integrity  — row counts, brand spread, degenerate-comment counts.
2. Self-retrieval   — embedding a chunk's own text and searching for it
   should return that exact chunk first, at ~zero distance. This only
   proves the index/embedding pipeline is wired correctly; it says
   nothing about semantic quality.
3. Keyword-anchored lift — for a handful of themes (query + a regex that
   approximates "on topic"), compare the hit-rate inside the semantic
   top-K against the keyword's base rate in the whole corpus. A lift
   near 1x means the search is no better than random; a big lift means
   it's finding on-topic chunks that don't necessarily contain the
   literal keyword.
4. Negative control + cross-lingual — an off-topic query should score
   worse (larger distance) than an on-topic one, and a French query
   should retrieve the same English comments as its English equivalent
   (this is the whole reason the project uses a multilingual embedder).

Run:
    PYTHONPATH=src .venv/bin/python scripts/eval_retrieval.py
"""

import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from bikefinder_rag.db.client import get_connection
from bikefinder_rag.embeddings.embedder import embed_text, embed_texts

TOTAL_CHUNKS_SQL = "SELECT count(*) FROM review_chunks"

THEMES = [
    ("fuel economy / mileage", "how good is the fuel economy and mileage", r"mileage|fuel consumption|km/l|mpg"),
    ("vibration at speed", "does the engine vibrate a lot at speed", r"vibrat"),
    ("reliability problems", "is this bike reliable or does it break down", r"reliab|breakdown|problem|issue"),
    ("seat comfort", "is the seat comfortable for long rides", r"seat.{0,20}comfort|comfortable seat"),
    ("beginner friendly", "is this a good first bike for a beginner", r"beginner|first bike|new rider"),
    ("brakes", "how good are the brakes", r"brake|braking"),
]

NEGATIVE_QUERIES = [
    "recette de gâteau au chocolat sans four",
    "best python web framework for a REST API",
]

CROSS_LINGUAL_PAIRS = [
    ("is this bike reliable or does it break down", "est-ce que cette moto est fiable ou tombe-t-elle souvent en panne"),
    ("how good is the fuel economy and mileage", "quelle est la consommation d'essence de cette moto"),
]


def fetchall(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def semantic_search(conn, query: str, limit: int):
    vector = embed_text(query)
    return fetchall(
        conn,
        """
        SELECT rc.id, f.brand, f.family_name AS model, rc.comment_text,
               rc.embedding <=> %s::vector AS distance
        FROM review_chunks rc JOIN model_families f ON f.id = rc.family_id
        ORDER BY rc.embedding <=> %s::vector
        LIMIT %s
        """,
        [vector, vector, limit],
    )


def data_integrity(conn) -> dict:
    counts = fetchall(conn, """
        SELECT
          (SELECT count(*) FROM motorcycles) AS motorcycles,
          (SELECT count(*) FROM model_families) AS model_families,
          (SELECT count(*) FROM review_chunks) AS review_chunks,
          (SELECT count(DISTINCT family_id) FROM review_chunks) AS families_with_reviews,
          (SELECT count(*) FROM motorcycles WHERE family_id IN
             (SELECT DISTINCT family_id FROM review_chunks)) AS motos_with_reviews
    """)[0]
    length_stats = fetchall(conn, """
        SELECT count(*) FILTER (WHERE length(comment_text) < 15) AS very_short,
               avg(length(comment_text))::int AS avg_len,
               count(*) FILTER (WHERE embedding IS NULL) AS null_embeddings
        FROM review_chunks
    """)[0]
    orphans = fetchall(conn, """
        SELECT count(*) AS n FROM review_chunks rc
        LEFT JOIN model_families f ON f.id = rc.family_id WHERE f.id IS NULL
    """)[0]["n"]
    dupes = fetchall(conn, """
        SELECT count(*) AS n FROM (
          SELECT family_id, comment_text, author, posted_at, count(*) c
          FROM review_chunks GROUP BY 1, 2, 3, 4 HAVING count(*) > 1
        ) t
    """)[0]["n"]
    return {**counts, **length_stats, "orphan_chunks": orphans, "exact_duplicate_groups": dupes}


def self_retrieval_test(conn, sample_size=30) -> dict:
    sample = fetchall(conn, "SELECT id, comment_text FROM review_chunks ORDER BY random() LIMIT %s", [sample_size])
    vectors = embed_texts([r["comment_text"] for r in sample])
    hits_rank1 = 0
    distances = []
    with conn.cursor() as cur:
        for row, vec in zip(sample, vectors):
            cur.execute(
                "SELECT id, embedding <=> %s::vector AS d FROM review_chunks ORDER BY embedding <=> %s::vector LIMIT 1",
                [vec, vec],
            )
            top_id, dist = cur.fetchone()
            distances.append(dist)
            if top_id == row["id"]:
                hits_rank1 += 1
    return {
        "sample_size": sample_size,
        "rank1_hits": hits_rank1,
        "rank1_hit_rate": hits_rank1 / sample_size,
        "avg_self_distance": sum(distances) / len(distances),
    }


def keyword_lift_test(conn, total_chunks: int, top_k=30) -> list[dict]:
    results = []
    for name, query, pattern in THEMES:
        base_count = fetchall(conn, "SELECT count(*) AS n FROM review_chunks WHERE comment_text ~* %s", [pattern])[0]["n"]
        base_rate = base_count / total_chunks
        top = semantic_search(conn, query, top_k)
        matches = [r for r in top if re.search(pattern, r["comment_text"], re.IGNORECASE)]
        hit_rate = len(matches) / top_k
        results.append({
            "theme": name,
            "query": query,
            "base_count": base_count,
            "base_rate": round(base_rate, 4),
            "top_k": top_k,
            "hits_in_top_k": len(matches),
            "hit_rate": round(hit_rate, 4),
            "lift": round(hit_rate / base_rate, 2) if base_rate > 0 else None,
            "example_hits": [
                {"brand": r["brand"], "model": r["model"], "distance": round(r["distance"], 4),
                 "text": r["comment_text"][:220]}
                for r in top[:3]
            ],
        })
    return results


def negative_control_test(conn, on_topic_avg_top1: float) -> list[dict]:
    results = []
    for query in NEGATIVE_QUERIES:
        top = semantic_search(conn, query, 3)
        results.append({
            "query": query,
            "top1_distance": round(top[0]["distance"], 4),
            "worse_than_on_topic_avg": top[0]["distance"] > on_topic_avg_top1,
            "top_hits": [
                {"brand": r["brand"], "model": r["model"], "distance": round(r["distance"], 4),
                 "text": r["comment_text"][:200]}
                for r in top
            ],
        })
    return results


def cross_lingual_test(conn, top_k=10) -> list[dict]:
    results = []
    for en, fr in CROSS_LINGUAL_PAIRS:
        en_top = {r["id"] for r in semantic_search(conn, en, top_k)}
        fr_top = {r["id"] for r in semantic_search(conn, fr, top_k)}
        overlap = en_top & fr_top
        results.append({
            "english_query": en,
            "french_query": fr,
            "top_k": top_k,
            "overlap_count": len(overlap),
            "jaccard": round(len(overlap) / len(en_top | fr_top), 3),
        })
    return results


def main() -> None:
    conn = get_connection()
    try:
        integrity = data_integrity(conn)
        total_chunks = integrity["review_chunks"]

        self_retrieval = self_retrieval_test(conn)
        lift = keyword_lift_test(conn, total_chunks)
        negatives = negative_control_test(conn, self_retrieval["avg_self_distance"] + 0.3)
        cross_lingual = cross_lingual_test(conn)

        report = {
            "data_integrity": integrity,
            "self_retrieval": self_retrieval,
            "keyword_lift": lift,
            "negative_control": negatives,
            "cross_lingual": cross_lingual,
        }
        out_path = Path(__file__).resolve().parent.parent / "eval_results/retrieval/retrieval_report.json"
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nWritten to {out_path}", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

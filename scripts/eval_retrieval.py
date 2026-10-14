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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from bikefinder_rag.db.client import get_connection
from bikefinder_rag.embeddings.embedder import embed_text, embed_texts
from bikefinder_rag.eval.provenance import collect_provenance, dated_report_path

THEMES = [
    ("fuel economy / mileage", "how good is the fuel economy and mileage", r"mileage|fuel consumption|km/l|mpg"),
    ("vibration at speed", "does the engine vibrate a lot at speed", r"vibrat"),
    ("reliability problems", "is this bike reliable or does it break down", r"reliab|breakdown|problem|issue"),
    ("seat comfort", "is the seat comfortable for long rides", r"seat.{0,20}comfort|comfortable seat"),
    ("beginner friendly", "is this a good first bike for a beginner", r"beginner|first bike|new rider"),
    ("brakes", "how good are the brakes", r"brake|braking"),
]

# French queries judged with a bilingual keyword proxy — on-topic density
# of a query's top-k. The corpus mixes English forum comments and, since
# 2026-09-02, French owner reviews from motoplanete, so each regex carries
# the French words too; the shipped arms also report how many of their
# top-k are French documents (`fr_docs_*`), which is the new corpus's
# direct contribution.
#
# Each theme also carries an English phrasing for comparison. With the
# bilingual corpus the agent queries in the user's language: the French
# shipped arm now describes the direct path for French user questions.
#
# The English phrasings deliberately avoid the words the regex matches
# ("stop in an emergency", not "brakes"): the sparse leg retrieves on query
# terms and the proxy scores on those same terms, so a lexically-overlapping
# English query would score near-perfectly by construction and measure
# nothing. Paraphrases keep the proxy independent of the retriever.
FRENCH_THEMES = [
    ("fuel economy", "quelle est la consommation d'essence de cette moto",
     "what kind of gas usage does this bike get on the highway",
     r"mileage|fuel consumption|km/l|mpg|consommation|conso\b|litres?\s*(?:au|aux|/)\s*100|l/100"),
    ("vibration", "est-ce que le moteur vibre beaucoup a haute vitesse",
     "does the engine buzz badly at high speed",
     r"vibrat"),  # same stem in both languages
    ("seat comfort", "la selle est-elle confortable sur longs trajets",
     "how does the saddle feel on a long ride",
     r"seat.{0,20}comfort|comfortable seat|uncomfortable|selle.{0,30}confort|confort.{0,30}selle|inconfortable"),
    ("beginner", "est-ce une bonne premiere moto pour un debutant",
     "is this a good bike to learn on",
     r"beginner|first bike|new rider|d[ée]butant|premi[èe]re moto|jeune permis"),
    ("brakes", "les freins sont-ils bons",
     "how well does it stop in an emergency",
     r"brake|braking|frein"),
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
    sample = fetchall(conn, """
        SELECT id, comment_text FROM review_chunks
        ORDER BY md5(id::text || ':bikefinder-self-v1'), id LIMIT %s
    """, [sample_size])
    vectors = embed_texts([r["comment_text"] for r in sample])
    hits_rank1 = 0
    distances, samples, failures = [], [], []
    with conn.cursor() as cur:
        for row, vec in zip(sample, vectors):
            cur.execute(
                "SELECT embedding <=> %s::vector FROM review_chunks WHERE id = %s",
                [vec, row["id"]],
            )
            own_distance = cur.fetchone()[0]
            cur.execute(
                "SELECT id, embedding <=> %s::vector AS d FROM review_chunks ORDER BY embedding <=> %s::vector LIMIT 10",
                [vec, vec],
            )
            top = cur.fetchall()
            ann_rank = next((i for i, (chunk_id, _) in enumerate(top, 1)
                             if chunk_id == row["id"]), None)
            distances.append(own_distance)
            detail = {"id": row["id"], "stored_vector_distance": own_distance,
                      "ann_rank_in_top10": ann_rank,
                      "ann_top1_id": top[0][0] if top else None,
                      "ann_top1_distance": top[0][1] if top else None}
            samples.append(detail)
            if ann_rank == 1:
                hits_rank1 += 1
            if ann_rank != 1 or own_distance > 1e-4:
                # + 0 prevents the HNSW ORDER BY operator match, giving an
                # exact scan only for failures, without changing session settings.
                cur.execute("""
                    SELECT id, embedding <=> %s::vector AS d FROM review_chunks
                    ORDER BY (embedding <=> %s::vector) + 0, id LIMIT 1
                """, [vec, vec])
                exact_id, exact_distance = cur.fetchone()
                cur.execute("""
                    SELECT count(*) + 1 FROM review_chunks
                    WHERE embedding <=> %s::vector < %s
                """, [vec, own_distance - 1e-7])
                exact_rank = cur.fetchone()[0]
                if own_distance > 1e-4:
                    reason = "stored_embedding_mismatch"
                elif top and abs(top[0][1] - own_distance) <= 1e-7:
                    reason = "distance_tie"
                else:
                    reason = "approximate_search_miss"
                failures.append({**detail, "reason": reason,
                                 "exact_top1_id": exact_id,
                                 "exact_top1_distance": exact_distance,
                                 "exact_rank_allowing_distance_ties": exact_rank,
                                 "ann_top10": [{"id": chunk_id, "distance": dist}
                                               for chunk_id, dist in top]})
    return {
        "sampling": "md5(id::text || ':bikefinder-self-v1'), id",
        "requested_sample_size": sample_size,
        "sample_size": len(sample),
        "rank1_hits": hits_rank1,
        "rank1_hit_rate": hits_rank1 / len(sample) if sample else None,
        "stored_vector_mismatches": sum(distance > 1e-4 for distance in distances),
        "stored_distance_tolerance": 1e-4,
        "distance_tie_tolerance": 1e-7,
        "avg_self_distance": sum(distances) / len(distances) if distances else None,
        "samples": samples,
        "failures": failures,
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
            "top1_distance": round(top[0]["distance"], 4) if top else None,
            "example_hits": [
                {"brand": r["brand"], "model": r["model"], "distance": round(r["distance"], 4),
                 "text": r["comment_text"][:220]}
                for r in top[:3]
            ],
        })
    return results


def negative_control_test(conn, on_topic_avg_top1: float) -> list[dict]:
    """Distance separation only; this does not test agent abstention."""
    results = []
    for query in NEGATIVE_QUERIES:
        top = semantic_search(conn, query, 3)
        results.append({
            "query": query,
            "top1_distance": round(top[0]["distance"], 4),
            "on_topic_avg_top1_distance": round(on_topic_avg_top1, 4),
            "worse_than_on_topic_avg": top[0]["distance"] > on_topic_avg_top1,
            "top_hits": [
                {"brand": r["brand"], "model": r["model"], "distance": round(r["distance"], 4),
                 "text": r["comment_text"][:200]}
                for r in top
            ],
        })
    return results


def cross_lingual_test(conn, top_k=10, rerank_pool=50) -> list[dict]:
    """Dense-only top-k overlap between an EN query and its FR equivalent,
    and — when the reranker is enabled — the same overlap after
    cross-encoder reranking of a dense top-`rerank_pool` shortlist. The
    cross-encoder reads query and comment together, so it should agree
    with itself across languages far more than the bi-encoder does."""
    from bikefinder_rag.embeddings import reranker

    def top_ids(query: str) -> tuple[set, set | None]:
        dense = semantic_search(conn, query, rerank_pool if reranker.enabled() else top_k)
        dense_ids = {r["id"] for r in dense[:top_k]}
        if not reranker.enabled():
            return dense_ids, None
        scores = reranker.rerank(query, [r["comment_text"] for r in dense])
        ranked = sorted(zip(dense, scores), key=lambda p: p[1], reverse=True)
        return dense_ids, {r["id"] for r, _ in ranked[:top_k]}

    results = []
    for en, fr in CROSS_LINGUAL_PAIRS:
        en_dense, en_reranked = top_ids(en)
        fr_dense, fr_reranked = top_ids(fr)
        entry = {
            "english_query": en,
            "french_query": fr,
            "top_k": top_k,
            "overlap_count": len(en_dense & fr_dense),
            "jaccard": round(len(en_dense & fr_dense) / len(en_dense | fr_dense), 3),
        }
        if en_reranked is not None:
            entry["overlap_count_reranked"] = len(en_reranked & fr_reranked)
            entry["jaccard_reranked"] = round(
                len(en_reranked & fr_reranked) / len(en_reranked | fr_reranked), 3)
        results.append(entry)
    return results


def french_relevance_test(conn, top_k=10, rerank_pool=50) -> list[dict]:
    """On-topic hits (keyword proxy) in a query's top-k, over four arms.

    Two are reimplemented here (dense-only, dense+rerank) and kept for
    continuity with the numbers published on 2026-07-15. Two call
    `search_reviews` — the function the agent actually calls — because the
    two reimplemented arms stopped describing the product the day hybrid
    retrieval landed (2026-07-16) and nothing re-measured them:

      hits_dense       dense top-k, no rerank            (baseline)
      hits_reranked    dense top-50 reranked             (the '+57%' number)
      hits_shipped_fr  search_reviews(french query)      (French-user path)
      hits_shipped_en  search_reviews(english query)     (English comparison)

    `hits_shipped_fr` describes a French user question with the bilingual
    corpus; the agent uses the user's language. The reranker can only reorder its shortlist, so a
    theme whose pool holds no on-topic candidate stays at zero in every
    arm — that residual is a recall bound, and it is reported as-is."""
    from bikefinder_rag.agent.tools import search_reviews
    from bikefinder_rag.embeddings import reranker

    results = []
    for name, fr_query, en_query, pattern in FRENCH_THEMES:
        hits = lambda rows: sum(bool(re.search(pattern, r["comment_text"], re.IGNORECASE)) for r in rows)
        # `search_reviews` raises hnsw.ef_search, and SET persists for the
        # whole session — without this reset the dense arms would inherit
        # the previous theme's setting and stop being a fixed baseline.
        # 40 is pgvector's default, the condition the July numbers ran under.
        with conn.cursor() as cur:
            cur.execute("SET hnsw.ef_search = 40")
        pool = semantic_search(conn, fr_query, rerank_pool)
        entry = {"theme": name, "french_query": fr_query, "english_query": en_query,
                 "top_k": top_k, "hits_dense": hits(pool[:top_k])}
        if reranker.enabled():
            scores = reranker.rerank(fr_query, [r["comment_text"] for r in pool])
            reranked = [r for r, _ in sorted(zip(pool, scores), key=lambda p: p[1], reverse=True)]
            entry["hits_reranked"] = hits(reranked[:top_k])
        shipped_fr = search_reviews(conn, fr_query, limit=top_k)
        shipped_en = search_reviews(conn, en_query, limit=top_k)
        entry["hits_shipped_fr"] = hits(shipped_fr)
        entry["hits_shipped_en"] = hits(shipped_en)
        entry["fr_docs_shipped_fr"] = sum(r.get("lang") == "fr" for r in shipped_fr)
        entry["fr_docs_shipped_en"] = sum(r.get("lang") == "fr" for r in shipped_en)
        results.append(entry)
    return results


def main() -> None:
    conn = get_connection()
    try:
        metadata = collect_provenance(conn)
        integrity = data_integrity(conn)
        total_chunks = integrity["review_chunks"]
        if not total_chunks:
            raise SystemExit("The review corpus is empty; load a dataset before evaluating retrieval.")

        self_retrieval = self_retrieval_test(conn)
        lift = keyword_lift_test(conn, total_chunks)
        on_topic_avg = sum(row["top1_distance"] for row in lift) / len(lift)
        metadata["evaluation"] = {"negative_control": "distance separation, not agent abstention",
                                  "on_topic_avg_top1_distance": on_topic_avg}
        negatives = negative_control_test(conn, on_topic_avg)
        cross_lingual = cross_lingual_test(conn)
        french_relevance = french_relevance_test(conn)

        report = {
            "metadata": metadata,
            "data_integrity": integrity,
            "self_retrieval": self_retrieval,
            "keyword_lift": lift,
            "negative_control": negatives,
            "cross_lingual": cross_lingual,
            "french_relevance": french_relevance,
        }
        out_path = dated_report_path(Path(__file__).resolve().parent.parent / "eval_results/retrieval",
                                    "retrieval_report", metadata["created_at_utc"])
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nWritten to {out_path}", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

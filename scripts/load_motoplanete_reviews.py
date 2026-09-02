#!/usr/bin/env python3
"""Load motoplanete's French owner reviews into review_chunks.

Input: data/motoplanete/reviews.jsonl (scripts/scrape_motoplanete_reviews.py).
Each review is matched to our catalog with the token matcher shared by the
other enrichment loaders (brand, model, fiche year, ±1 year fallback), then
attached at FAMILY level like the bikez comments — a motoplanete review
pool spans model-years exactly the way a bikez forum does.

Embedded text = title + body (the title is often the verdict: "Il manque
qques litres"). Replies are loaded as their own rows: they are owner
opinions too, and the family attachment is what search needs.

Idempotent: the (family, author, posted_at, md5(text)) unique index skips
what is already there, and the schema additions use IF NOT EXISTS, so the
loader can run again as the crawl progresses.

    PYTHONPATH=src .venv/bin/python scripts/load_motoplanete_reviews.py [--data data/motoplanete]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
load_dotenv()

from bikefinder_rag.db.client import get_connection  # noqa: E402
from bikefinder_rag.embeddings.embedder import embed_texts  # noqa: E402
from bikefinder_rag.matching import MotorcycleMatcher  # noqa: E402

EMBED_BATCH = 64
# motoplanete already lists 2027 models while the catalog stops at 2024, and a
# review pool spans a model's whole life anyway: walk back up to 14 years to
# find the family (first hit wins), then one or two years forward.
REVIEW_YEAR_OFFSETS = tuple(range(0, -15, -1)) + (1, 2)
SCHEMA_SQL = Path(__file__).resolve().parent.parent / "src/bikefinder_rag/db/schema.sql"


def ensure_columns(conn) -> None:
    """Apply the review_chunks additions from schema.sql (all IF NOT EXISTS)
    to a database initialised before they existed."""
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    start = sql.index("-- French owner reviews (scripts/load_motoplanete_reviews.py)")
    with conn.cursor() as cur:
        cur.execute(sql[start:])
    conn.commit()


def review_text(row: dict) -> str:
    title, body = (row.get("title") or "").strip(), (row.get("text") or "").strip()
    return f"{title}\n{body}" if title and title.lower() not in body.lower() else body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=Path("data/motoplanete"))
    args = parser.parse_args()
    reviews_path = args.data / "reviews.jsonl"
    if not reviews_path.exists():
        sys.exit(f"{reviews_path} missing — run scrape_motoplanete_reviews.py first")

    conn = get_connection()
    try:
        ensure_columns(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT id, family_id, brand, model, year FROM motorcycles")
            matcher = MotorcycleMatcher([((mid, fid), b, m, y) for mid, fid, b, m, y in cur.fetchall()])

        rows = [json.loads(l) for l in reviews_path.open(encoding="utf-8") if l.strip()]
        by_fiche: dict[str, list[dict]] = {}
        for r in rows:
            by_fiche.setdefault(r["fiche_url"], []).append(r)

        to_embed: list[tuple[int, dict]] = []
        unmatched_fiches = unmatched_reviews = 0
        family_cache: dict[str, int | None] = {}
        for url, group in by_fiche.items():
            first = group[0]
            payloads, _dy = matcher.match(first["brand"], first["model"], first["fiche_year"],
                                          year_offsets=REVIEW_YEAR_OFFSETS)
            families = Counter(fid for _mid, fid in payloads)
            family_id = families.most_common(1)[0][0] if families else None
            family_cache[url] = family_id
            if family_id is None:
                unmatched_fiches += 1
                unmatched_reviews += len(group)
                continue
            for r in group:
                text = review_text(r)
                if text:
                    to_embed.append((family_id, {**r, "_text": text}))

        print(f"{len(rows)} reviews on {len(by_fiche)} fiches; "
              f"{len(by_fiche) - unmatched_fiches} fiches matched to a family, "
              f"{unmatched_fiches} unmatched ({unmatched_reviews} reviews dropped); "
              f"{len(to_embed)} reviews to embed.", file=sys.stderr)

        inserted = 0
        with conn.cursor() as cur:
            for start in range(0, len(to_embed), EMBED_BATCH):
                batch = to_embed[start:start + EMBED_BATCH]
                vectors = embed_texts([r["_text"] for _fid, r in batch])
                for (family_id, r), vector in zip(batch, vectors):
                    cur.execute(
                        """
                        INSERT INTO review_chunks
                            (family_id, comment_text, author, posted_at, embedding, source, lang, rating)
                        VALUES (%s, %s, %s, %s, %s, 'motoplanete', 'fr', %s)
                        ON CONFLICT (family_id, author, posted_at, md5(comment_text)) DO NOTHING
                        """,
                        (family_id, r["_text"], r.get("author") or None, r.get("posted_at"), vector, r.get("rating")),
                    )
                    inserted += cur.rowcount
                conn.commit()
                print(f"  embedded {min(start + EMBED_BATCH, len(to_embed))}/{len(to_embed)}", file=sys.stderr)
        print(f"Loaded {inserted} new French reviews (source=motoplanete, lang=fr).", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

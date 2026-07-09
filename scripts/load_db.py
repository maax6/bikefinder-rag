#!/usr/bin/env python3
"""Load scraped JSONL (data/pilot/motorcycles.jsonl + comments.jsonl) into
Postgres: specs as-is, comments embedded with BGE-M3 first.

Run: PYTHONPATH=src .venv/bin/python scripts/load_db.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
load_dotenv()

from bikefinder_rag.db.client import get_connection
from bikefinder_rag.embeddings.embedder import embed_texts

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "pilot"


def load_motorcycles(conn) -> dict[str, int]:
    url_to_id: dict[str, int] = {}

    with (DATA_DIR / "motorcycles.jsonl").open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]

    with conn.cursor() as cur:
        for row in rows:
            typed = row.get("typed_fields", {})
            cur.execute(
                """
                INSERT INTO motorcycles
                    (brand, model, year, category, url,
                     displacement_ccm, weight_kg, power_hp, torque_nm, seat_height_mm,
                     raw_specs)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET
                    displacement_ccm = EXCLUDED.displacement_ccm,
                    weight_kg = EXCLUDED.weight_kg,
                    power_hp = EXCLUDED.power_hp,
                    torque_nm = EXCLUDED.torque_nm,
                    seat_height_mm = EXCLUDED.seat_height_mm,
                    raw_specs = EXCLUDED.raw_specs
                RETURNING id
                """,
                (
                    row["brand"],
                    row["model"],
                    row["year"],
                    row["category"],
                    row["url"],
                    typed.get("displacement_ccm") or row.get("displacement_ccm"),
                    typed.get("weight_kg"),
                    typed.get("power_hp"),
                    typed.get("torque_nm"),
                    typed.get("seat_height_mm"),
                    json.dumps(row.get("raw_specs", {})),
                ),
            )
            (moto_id,) = cur.fetchone()
            url_to_id[row["url"]] = moto_id

    print(f"Loaded {len(url_to_id)} motorcycles.", file=sys.stderr)
    return url_to_id


def load_comments(conn, url_to_id: dict[str, int]) -> None:
    comments_path = DATA_DIR / "comments.jsonl"
    if not comments_path.exists():
        print("No comments.jsonl found, skipping.", file=sys.stderr)
        return

    by_url: dict[str, list[dict]] = defaultdict(list)
    with comments_path.open(encoding="utf-8") as f:
        for line in f:
            comment = json.loads(line)
            by_url[comment["motorcycle_url"]].append(comment)

    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT motorcycle_id FROM review_chunks")
        already_loaded = {row[0] for row in cur.fetchall()}

    total = 0
    n_bikes = len(by_url)
    with conn.cursor() as cur:
        for i, (url, comments) in enumerate(by_url.items(), start=1):
            moto_id = url_to_id.get(url)
            if moto_id is None or moto_id in already_loaded:
                continue

            texts = [c["text"] for c in comments]
            vectors = embed_texts(texts)
            if i % 10 == 0 or i == n_bikes:
                print(f"  embedded comments for {i}/{n_bikes} motorcycles ({total} rows so far)", file=sys.stderr)

            for comment, vector in zip(comments, vectors):
                cur.execute(
                    """
                    INSERT INTO review_chunks (motorcycle_id, comment_text, author, posted_at, embedding)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (moto_id, comment["text"], comment["author"], comment["posted_at"], vector),
                )
                total += 1

    print(f"Loaded {total} review comments (embedded with BGE-M3).", file=sys.stderr)


def main() -> None:
    conn = get_connection()
    url_to_id = load_motorcycles(conn)
    load_comments(conn, url_to_id)
    conn.close()


if __name__ == "__main__":
    main()

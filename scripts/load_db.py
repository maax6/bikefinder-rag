#!/usr/bin/env python3
"""Load scraped JSONL (data/pilot/motorcycles.jsonl + comments.jsonl) into
Postgres: model families first (one per bikez discussion forum), then specs,
then comments — deduplicated per family and embedded with BGE-M3.

bikez.com shares one forum per model family (every model-year links to the
same discussions.php page), so the scrape wrote each comment once per member
model-year. Here they collapse back to one row per family, which both removes
the duplicates and stops attributing decade-old comments to a specific recent
model-year.

Run: PYTHONPATH=src .venv/bin/python scripts/load_db.py
"""

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
load_dotenv()

from bikefinder_rag.db.client import get_connection
from bikefinder_rag.embeddings.embedder import embed_texts

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "pilot"
EMBED_BATCH = 256


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def family_display_name(member_models: list[str]) -> str:
    """One name for the whole family: the longest common prefix of member
    model names ('CB 250 K 1' + 'CB 250 N' -> 'CB 250'), falling back to the
    most common member name when the prefix is too short to mean anything."""
    prefix = os.path.commonprefix(member_models).strip(" -/")
    if len(prefix) >= 3:
        return prefix
    return Counter(member_models).most_common(1)[0][0]


def load_families(conn, motorcycles: list[dict]) -> dict[str, int]:
    """Insert one model_families row per distinct discussion_url; returns
    discussion_url -> family id."""
    members: dict[str, list[dict]] = defaultdict(list)
    for row in motorcycles:
        if row.get("discussion_url"):
            members[row["discussion_url"]].append(row)

    url_to_family: dict[str, int] = {}
    with conn.cursor() as cur:
        for discussion_url, rows in members.items():
            brand = Counter(r["brand"] for r in rows).most_common(1)[0][0]
            name = family_display_name([r["model"] for r in rows])
            years = [r["year"] for r in rows]
            cur.execute(
                """
                INSERT INTO model_families (discussion_url, brand, family_name, year_min, year_max)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (discussion_url) DO UPDATE SET
                    brand = EXCLUDED.brand,
                    family_name = EXCLUDED.family_name,
                    year_min = LEAST(model_families.year_min, EXCLUDED.year_min),
                    year_max = GREATEST(model_families.year_max, EXCLUDED.year_max)
                RETURNING id
                """,
                (discussion_url, brand, name, min(years), max(years)),
            )
            url_to_family[discussion_url] = cur.fetchone()[0]

    print(f"Loaded {len(url_to_family)} model families.", file=sys.stderr)
    return url_to_family


def load_motorcycles(conn, motorcycles: list[dict], url_to_family: dict[str, int]) -> dict[str, str | None]:
    """Insert motorcycles; returns motorcycle url -> its discussion_url (or None)."""
    moto_to_discussion: dict[str, str | None] = {}

    with conn.cursor() as cur:
        for row in motorcycles:
            typed = row.get("typed_fields", {})
            discussion_url = row.get("discussion_url")
            cur.execute(
                """
                INSERT INTO motorcycles
                    (brand, model, year, category, url, family_id,
                     displacement_ccm, weight_kg, power_hp, torque_nm, seat_height_mm,
                     raw_specs)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO UPDATE SET
                    family_id = EXCLUDED.family_id,
                    displacement_ccm = EXCLUDED.displacement_ccm,
                    weight_kg = EXCLUDED.weight_kg,
                    power_hp = EXCLUDED.power_hp,
                    torque_nm = EXCLUDED.torque_nm,
                    seat_height_mm = EXCLUDED.seat_height_mm,
                    raw_specs = EXCLUDED.raw_specs
                """,
                (
                    row["brand"],
                    row["model"],
                    row["year"],
                    row["category"],
                    row["url"],
                    url_to_family.get(discussion_url) if discussion_url else None,
                    typed.get("displacement_ccm") or row.get("displacement_ccm"),
                    typed.get("weight_kg"),
                    typed.get("power_hp"),
                    typed.get("torque_nm"),
                    typed.get("seat_height_mm"),
                    json.dumps(row.get("raw_specs", {})),
                ),
            )
            moto_to_discussion[row["url"]] = discussion_url

    print(f"Loaded {len(moto_to_discussion)} motorcycles.", file=sys.stderr)
    return moto_to_discussion


def load_comments(conn, moto_to_discussion: dict[str, str | None], url_to_family: dict[str, int]) -> None:
    comments_path = DATA_DIR / "comments.jsonl"
    if not comments_path.exists():
        print("No comments.jsonl found, skipping.", file=sys.stderr)
        return

    # The scrape duplicated each family's comments once per member model-year;
    # collapse to one row per (family, author, posted_at, text).
    unique: dict[tuple, dict] = {}
    skipped_no_family = 0
    for comment in read_jsonl(comments_path):
        discussion_url = moto_to_discussion.get(comment["motorcycle_url"])
        family_id = url_to_family.get(discussion_url) if discussion_url else None
        if family_id is None:
            skipped_no_family += 1
            continue
        key = (family_id, comment["author"], comment["posted_at"], comment["text"])
        unique.setdefault(key, comment)

    keys = list(unique)
    print(
        f"{len(keys)} unique comments to embed (deduplicated from the per-model-year scrape"
        + (f", {skipped_no_family} skipped without family" if skipped_no_family else "")
        + ").",
        file=sys.stderr,
    )

    total = 0
    with conn.cursor() as cur:
        for start in range(0, len(keys), EMBED_BATCH):
            batch = keys[start : start + EMBED_BATCH]
            vectors = embed_texts([key[3] for key in batch])
            for (family_id, author, posted_at, text), vector in zip(batch, vectors):
                cur.execute(
                    """
                    INSERT INTO review_chunks (family_id, comment_text, author, posted_at, embedding)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (family_id, author, posted_at, md5(comment_text)) DO NOTHING
                    """,
                    (family_id, text, author, posted_at, vector),
                )
                total += cur.rowcount
            print(f"  embedded {min(start + EMBED_BATCH, len(keys))}/{len(keys)}", file=sys.stderr)

    print(f"Loaded {total} review comments (embedded with BGE-M3).", file=sys.stderr)


def main() -> None:
    motorcycles = read_jsonl(DATA_DIR / "motorcycles.jsonl")
    conn = get_connection()
    try:
        url_to_family = load_families(conn, motorcycles)
        moto_to_discussion = load_motorcycles(conn, motorcycles, url_to_family)
        load_comments(conn, moto_to_discussion, url_to_family)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

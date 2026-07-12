#!/usr/bin/env python3
"""Load scraped JSONL (data/pilot/motorcycles.jsonl + comments.jsonl) into
Postgres: model families first (one per bikez discussion forum), then specs,
then comments — deduplicated per family and embedded with BGE-M3.

bikez.com shares one forum per model family (every model-year links to the
same discussions.php page), so the scrape wrote each comment once per member
model-year. Here they collapse back to one row per family, which both removes
the duplicates and stops attributing decade-old comments to a specific recent
model-year.

Run: PYTHONPATH=src .venv/bin/python scripts/load_db.py [data_dir]
(data_dir defaults to data/pilot; pass data/demo for the demo scrape.)
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
load_dotenv()

from bikefinder_rag.db.client import get_connection
from bikefinder_rag.embeddings.embedder import embed_texts
from bikefinder_rag.scraper.detail_scraper import extract_typed_fields

_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _ROOT / (sys.argv[1] if len(sys.argv) > 1 else "data/pilot")
EMBED_BATCH = 256

# A family only gets a narrative layer with at least this many unique
# comments (the README's curation rule — enforced here since the scraper
# streams threads to disk without knowing the final family totals).
MIN_SUBSTANTIVE_COMMENTS = 3


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def family_display_name(member_models: list[str]) -> str:
    """One name for the whole family: the words every member model name
    shares, in the first member's order ('FLHR Road King' + 'Road King
    Special' -> 'Road King'; 'CB 250 K 1' + 'CB 250 N' -> 'CB 250').
    Falls back to the shortest most-common member name when nothing is
    shared — variant names ('CB1000R Black Edition') would otherwise
    mislabel every comment in the family."""
    word_sets = [set(m.split()) for m in member_models]
    common = set.intersection(*word_sets)
    shared = [w for w in member_models[0].split() if w in common]
    if shared:
        return " ".join(shared)
    counts = Counter(member_models)
    top = max(counts.values())
    return min((m for m, c in counts.items() if c == top), key=len)


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
            # Re-derive typed fields from raw_specs with the current label
            # map — heals older scrapes when the map learns new labels
            # ('Power', 'Output', 'Effect'...) without re-scraping. Values
            # typed at scrape time win over the re-derivation.
            typed = {**extract_typed_fields(row.get("raw_specs", {})), **row.get("typed_fields", {})}
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
        # bikez stores apostrophes as acute accents ("it´s") — 28% of
        # comments carry them; normalize so embeddings see natural text.
        text = comment["text"].replace("´", "'")
        key = (family_id, comment["author"], comment["posted_at"], text)
        unique.setdefault(key, comment)

    per_family = Counter(key[0] for key in unique)
    keys = [key for key in unique if per_family[key[0]] >= MIN_SUBSTANTIVE_COMMENTS]
    thin = len(unique) - len(keys)
    print(
        f"{len(keys)} unique comments to embed (deduplicated from the per-model-year scrape"
        + (f", {skipped_no_family} skipped without family" if skipped_no_family else "")
        + (f", {thin} in families under the {MIN_SUBSTANTIVE_COMMENTS}-comment threshold" if thin else "")
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

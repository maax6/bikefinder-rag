#!/usr/bin/env python3
"""Pilot scrape: a small, deliberately varied sample (categories x decades x
brands) to validate the full pipeline before scraping the ~38k-entry catalog.

Writes two JSONL files under data/pilot/:
  - motorcycles.jsonl : one row per motorcycle (listing + specs)
  - comments.jsonl    : one row per forum comment, keyed by motorcycle url

Run: PYTHONPATH=src .venv/bin/python scripts/run_pilot_scrape.py
"""

import dataclasses
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bikefinder_rag.scraper.detail_scraper import fetch_discussion_comments, fetch_motorcycle_detail
from bikefinder_rag.scraper.list_scraper import list_motorcycles_for_year

# Deliberately spread across eras, including old/obscure entries (the "OVNIs")
# alongside modern, well-documented ones.
PILOT_YEARS = [1930, 1950, 1970, 1985, 2000, 2012, 2023]

MAX_PER_CATEGORY_PER_YEAR = 3
MAX_SAME_BRAND_PER_CATEGORY = 1
MIN_SUBSTANTIVE_COMMENTS = 3

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "pilot"


def select_stratified_sample(year: int) -> list:
    listings = list_motorcycles_for_year(year)
    by_category = defaultdict(list)
    for listing in listings:
        by_category[listing.category].append(listing)

    selected = []
    for category, entries in by_category.items():
        brand_counts: dict[str, int] = defaultdict(int)
        taken = 0
        for entry in entries:
            if taken >= MAX_PER_CATEGORY_PER_YEAR:
                break
            if brand_counts[entry.brand] >= MAX_SAME_BRAND_PER_CATEGORY:
                continue
            selected.append(entry)
            brand_counts[entry.brand] += 1
            taken += 1

    return selected


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    moto_path = OUT_DIR / "motorcycles.jsonl"
    comments_path = OUT_DIR / "comments.jsonl"

    discussion_cache: dict[str, list] = {}
    total_motorcycles = 0
    total_comments = 0

    with moto_path.open("w", encoding="utf-8") as moto_file, comments_path.open(
        "w", encoding="utf-8"
    ) as comments_file:
        for year in PILOT_YEARS:
            sample = select_stratified_sample(year)
            print(f"[{year}] stratified sample: {len(sample)} motorcycles", file=sys.stderr)

            for listing in sample:
                try:
                    detail = fetch_motorcycle_detail(listing.url)
                except Exception as exc:  # noqa: BLE001 - keep the pilot moving
                    print(f"  ! failed detail fetch {listing.url}: {exc}", file=sys.stderr)
                    continue

                record = {
                    **dataclasses.asdict(listing),
                    "typed_fields": detail.typed_fields,
                    "raw_specs": detail.raw_specs,
                    "discussion_url": detail.discussion_url,
                }
                moto_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                total_motorcycles += 1

                if detail.discussion_url:
                    if detail.discussion_url not in discussion_cache:
                        try:
                            discussion_cache[detail.discussion_url] = fetch_discussion_comments(
                                detail.discussion_url
                            )
                        except Exception as exc:  # noqa: BLE001
                            print(f"  ! failed discussion fetch {detail.discussion_url}: {exc}", file=sys.stderr)
                            discussion_cache[detail.discussion_url] = []

                    comments = discussion_cache[detail.discussion_url]
                    if len(comments) >= MIN_SUBSTANTIVE_COMMENTS:
                        for comment in comments:
                            comments_file.write(
                                json.dumps(
                                    {"motorcycle_url": listing.url, **dataclasses.asdict(comment)},
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                            total_comments += 1

                print(f"  + {listing.brand} {listing.model} ({listing.year}, {listing.category})", file=sys.stderr)

    print(f"\nDone. {total_motorcycles} motorcycles -> {moto_path}", file=sys.stderr)
    print(f"{total_comments} comments (>= {MIN_SUBSTANTIVE_COMMENTS}/bike threshold) -> {comments_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

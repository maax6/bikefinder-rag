#!/usr/bin/env python3
"""Demo-oriented scrape: the full latest model year for the major street
brands, so the bikes a visitor would actually type (MT-07, TMAX, X-ADV,
Street Triple...) are in the database.

Complements the stratified pilot sample (categories x decades), which was
statistically varied but demo-hostile: it contained almost no motorcycle a
visitor would spontaneously ask about. One recent year is enough for the
narrative layer because comments attach to model *families* — scraping the
2024 MT-07 captures the family forum with its whole multi-year history.

Appends to data/demo/*.jsonl and skips URLs already scraped (pilot or a
previous demo run), so it's resumable. Load with:
    PYTHONPATH=src .venv/bin/python scripts/load_db.py data/demo

Run: PYTHONPATH=src .venv/bin/python scripts/run_demo_scrape.py
"""

import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bikefinder_rag.scraper.detail_scraper import fetch_discussion_comments, fetch_motorcycle_detail
from bikefinder_rag.scraper.list_scraper import list_motorcycles_for_year

DEMO_YEARS = [2024]

# Prefix-matched against "Brand Model" so multi-word brands survive the
# listing parser's naive first-word split ("Moto Guzzi V7" -> brand "Moto").
CORE_BRANDS = (
    "Honda", "Yamaha", "Kawasaki", "Suzuki", "BMW", "Ducati", "Triumph",
    "Harley-Davidson", "Aprilia", "KTM", "Moto Guzzi", "Moto Morini",
    "Royal Enfield", "Enfield", "Indian", "Benelli", "MV Agusta",
)

MIN_SUBSTANTIVE_COMMENTS = 3
MAX_THREADS_PER_FORUM = 60  # deep forums (Gold Wing-class) get capped, not skipped

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_DIR = DATA_DIR / "demo"


def known_urls_and_discussions() -> tuple[set[str], set[str]]:
    """URLs already scraped, and discussion forums whose comments are
    already captured, across the pilot and any previous demo run."""
    urls: set[str] = set()
    discussions: set[str] = set()
    for jsonl in (DATA_DIR / "pilot" / "motorcycles.jsonl", OUT_DIR / "motorcycles.jsonl"):
        if not jsonl.exists():
            continue
        with jsonl.open(encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                urls.add(row["url"])
                if row.get("discussion_url"):
                    discussions.add(row["discussion_url"])
    return urls, discussions


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seen_urls, seen_discussions = known_urls_and_discussions()
    print(f"{len(seen_urls)} URLs already scraped, {len(seen_discussions)} forums already captured.",
          file=sys.stderr)

    discussion_cache: dict[str, list] = {}
    total_motorcycles = 0
    total_comments = 0

    with (OUT_DIR / "motorcycles.jsonl").open("a", encoding="utf-8") as moto_file, \
         (OUT_DIR / "comments.jsonl").open("a", encoding="utf-8") as comments_file:
        for year in DEMO_YEARS:
            listings = [
                listing for listing in list_motorcycles_for_year(year)
                if f"{listing.brand} {listing.model}".startswith(CORE_BRANDS)
                and listing.url not in seen_urls
            ]
            print(f"[{year}] {len(listings)} core-brand motorcycles to scrape", file=sys.stderr)

            for i, listing in enumerate(listings, start=1):
                try:
                    detail = fetch_motorcycle_detail(listing.url)
                except Exception as exc:  # noqa: BLE001 - keep the scrape moving
                    print(f"  ! failed detail fetch {listing.url}: {exc}", file=sys.stderr)
                    continue

                record = {
                    **dataclasses.asdict(listing),
                    "typed_fields": detail.typed_fields,
                    "raw_specs": detail.raw_specs,
                    "discussion_url": detail.discussion_url,
                }
                moto_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                moto_file.flush()
                seen_urls.add(listing.url)
                total_motorcycles += 1

                discussion_url = detail.discussion_url
                if discussion_url and discussion_url not in seen_discussions:
                    if discussion_url not in discussion_cache:
                        try:
                            discussion_cache[discussion_url] = fetch_discussion_comments(
                                discussion_url, max_threads=MAX_THREADS_PER_FORUM
                            )
                        except Exception as exc:  # noqa: BLE001
                            print(f"  ! failed discussion fetch {discussion_url}: {exc}", file=sys.stderr)
                            discussion_cache[discussion_url] = []

                    comments = discussion_cache[discussion_url]
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
                        comments_file.flush()

                if i % 25 == 0 or i == len(listings):
                    print(f"  [{year}] {i}/{len(listings)} done ({total_comments} comments so far)",
                          file=sys.stderr)

    print(f"\nDone. {total_motorcycles} motorcycles, {total_comments} comments -> {OUT_DIR}",
          file=sys.stderr)


if __name__ == "__main__":
    main()

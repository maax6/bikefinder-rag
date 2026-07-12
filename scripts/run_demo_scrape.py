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
     # defaults: 2024, core street brands, data/demo
     PYTHONPATH=src .venv/bin/python scripts/run_demo_scrape.py \
         --years 1894-1999 --brands all --out data/century
"""

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bikefinder_rag.scraper.detail_scraper import fetch_discussion_comments, fetch_motorcycle_detail
from bikefinder_rag.scraper.list_scraper import list_motorcycles_for_year

DEMO_YEARS = [2024]


def parse_years(spec: str) -> list[int]:
    """'2024' | '2020,2022' | '1894-1999' (ranges run newest-first so the
    best-documented years land before an overnight run is interrupted)."""
    years: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            start, end = (int(x) for x in part.split("-"))
            years.extend(range(max(start, end), min(start, end) - 1, -1))
        else:
            years.append(int(part))
    return years

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


def known_urls_and_discussions() -> tuple[set[str], set[str]]:
    """URLs already scraped, and discussion forums whose comments are
    already captured, across every scrape directory (pilot, demo, century...)."""
    urls: set[str] = set()
    discussions: set[str] = set()
    for jsonl in sorted(DATA_DIR.glob("*/motorcycles.jsonl")):
        with jsonl.open(encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                urls.add(row["url"])
                if row.get("discussion_url"):
                    discussions.add(row["discussion_url"])
    return urls, discussions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", default="2024",
                        help="'2024', '2020,2022' or '1894-1999' (default: 2024)")
    parser.add_argument("--brands", choices=["core", "all"], default="core",
                        help="'core' = major street brands only; 'all' = every included category/brand")
    parser.add_argument("--out", default="data/demo",
                        help="output directory for the JSONL files (default: data/demo)")
    args = parser.parse_args()

    years = parse_years(args.years)
    out_dir = Path(__file__).resolve().parent.parent / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    seen_urls, seen_discussions = known_urls_and_discussions()
    print(f"{len(seen_urls)} URLs already scraped, {len(seen_discussions)} forums already captured.",
          file=sys.stderr)
    print(f"Years: {years[0]}..{years[-1]} ({len(years)}), brands={args.brands}, out={args.out}",
          file=sys.stderr)

    discussion_cache: dict[str, list] = {}
    total_motorcycles = 0
    total_comments = 0

    with (out_dir / "motorcycles.jsonl").open("a", encoding="utf-8") as moto_file, \
         (out_dir / "comments.jsonl").open("a", encoding="utf-8") as comments_file:
        for year in years:
            listings = [
                listing for listing in list_motorcycles_for_year(year)
                if (args.brands == "all" or f"{listing.brand} {listing.model}".startswith(CORE_BRANDS))
                and listing.url not in seen_urls
            ]
            print(f"[{year}] {len(listings)} motorcycles to scrape", file=sys.stderr)

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

                print(f"  [{year} {i}/{len(listings)}] + {listing.brand} {listing.model}",
                      file=sys.stderr, flush=True)

                discussion_url = detail.discussion_url
                if discussion_url and discussion_url not in seen_discussions:
                    if discussion_url not in discussion_cache:
                        # Deep forums take a while (up to 60 threads at 1.5s
                        # each) — announce the crawl so the pause is explained.
                        print("        forum found, crawling threads...", file=sys.stderr, flush=True)
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
                        print(f"        forum: {len(comments)} comments kept "
                              f"({total_comments} total)", file=sys.stderr, flush=True)

    print(f"\nDone. {total_motorcycles} motorcycles, {total_comments} comments -> {out_dir}",
          file=sys.stderr)


if __name__ == "__main__":
    main()

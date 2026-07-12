#!/usr/bin/env python3
"""Scrape bikez.com: spec pages by year, plus every family forum thread.

Three levels of resume, so the script can be interrupted and re-run freely:
- Motorcycles: URLs already present in any data/*/motorcycles.jsonl are
  skipped.
- Forum threads: every fetched thread URL is journaled in threads_done.txt;
  only missing threads are ever fetched.
- Forums: a forum is journaled in forums_done.txt once its thread list has
  been fully walked. On startup, forums referenced by this output dir's
  motorcycles but not journaled as done (i.e. interrupted mid-crawl, since
  the bike row is written before its forum) are completed first. Delete
  forums_done.txt to force a full re-list (new threads) later.

The >=3-substantive-comments curation rule lives in load_db.py (families
with fewer unique comments are skipped at load time), since threads stream
to disk as they arrive.

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

from bikefinder_rag.scraper.detail_scraper import (
    fetch_motorcycle_detail,
    fetch_thread_comments,
    list_thread_urls,
)
from bikefinder_rag.scraper.list_scraper import list_motorcycles_for_year

# Prefix-matched against "Brand Model" so multi-word brands survive the
# listing parser's naive first-word split ("Moto Guzzi V7" -> brand "Moto").
CORE_BRANDS = (
    "Honda", "Yamaha", "Kawasaki", "Suzuki", "BMW", "Ducati", "Triumph",
    "Harley-Davidson", "Aprilia", "KTM", "Moto Guzzi", "Moto Morini",
    "Royal Enfield", "Enfield", "Indian", "Benelli", "MV Agusta",
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


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


def known_motorcycle_urls() -> set[str]:
    urls: set[str] = set()
    for jsonl in sorted(DATA_DIR.glob("*/motorcycles.jsonl")):
        with jsonl.open(encoding="utf-8") as f:
            urls.update(json.loads(line)["url"] for line in f)
    return urls


def read_journal(pattern: str) -> set[str]:
    entries: set[str] = set()
    for journal in sorted(DATA_DIR.glob(pattern)):
        with journal.open(encoding="utf-8") as f:
            entries.update(line.strip() for line in f if line.strip())
    return entries


def interrupted_forums(out_dir: Path, forums_done: set[str]) -> list[tuple[str, str]]:
    """(discussion_url, motorcycle_url) pairs for forums this output dir's
    bikes reference but whose crawl never completed — the bike row is
    written before its forum is walked, so an interrupt strands them."""
    pending: dict[str, str] = {}
    jsonl = out_dir / "motorcycles.jsonl"
    if jsonl.exists():
        with jsonl.open(encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                discussion_url = row.get("discussion_url")
                if discussion_url and discussion_url not in forums_done:
                    pending.setdefault(discussion_url, row["url"])
    return list(pending.items())


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

    seen_urls = known_motorcycle_urls()
    done_threads = read_journal("*/threads_done.txt")
    forums_done = read_journal("*/forums_done.txt")
    print(f"{len(seen_urls)} motorcycles already scraped, "
          f"{len(done_threads)} forum threads already captured, "
          f"{len(forums_done)} forums fully walked.", file=sys.stderr)
    print(f"Years: {years[0]}..{years[-1]} ({len(years)}), brands={args.brands}, out={args.out}",
          file=sys.stderr)

    totals = {"motorcycles": 0, "comments": 0}

    with (out_dir / "motorcycles.jsonl").open("a", encoding="utf-8") as moto_file, \
         (out_dir / "comments.jsonl").open("a", encoding="utf-8") as comments_file, \
         (out_dir / "threads_done.txt").open("a", encoding="utf-8") as threads_journal, \
         (out_dir / "forums_done.txt").open("a", encoding="utf-8") as forums_journal:

        def crawl_forum(discussion_url: str, motorcycle_url: str) -> None:
            try:
                thread_urls = list_thread_urls(discussion_url)
            except Exception as exc:  # noqa: BLE001 - retried via next bike/run
                print(f"  ! failed forum listing {discussion_url}: {exc}", file=sys.stderr)
                return

            todo = [t for t in thread_urls if t not in done_threads]
            if todo:
                print(f"        forum: {len(todo)}/{len(thread_urls)} threads to fetch...",
                      file=sys.stderr, flush=True)

            forum_comments = 0
            for n, thread_url in enumerate(todo, start=1):
                if n % 10 == 0:
                    print(f"        thread {n}/{len(todo)} ({forum_comments} comments)...",
                          file=sys.stderr, flush=True)
                try:
                    comments = fetch_thread_comments(thread_url)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! failed thread fetch {thread_url}: {exc}", file=sys.stderr)
                    continue
                for comment in comments:
                    comments_file.write(
                        json.dumps(
                            {
                                "motorcycle_url": motorcycle_url,
                                "thread_url": thread_url,
                                **dataclasses.asdict(comment),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    forum_comments += 1
                    totals["comments"] += 1
                comments_file.flush()
                # Journal the thread only after its comments are on disk —
                # an interrupt between the two refetches, never loses.
                threads_journal.write(thread_url + "\n")
                threads_journal.flush()
                done_threads.add(thread_url)

            if forum_comments:
                print(f"        forum: {forum_comments} comments "
                      f"({totals['comments']} total)", file=sys.stderr, flush=True)

            # Only now is the forum complete — journaled after every thread.
            forums_journal.write(discussion_url + "\n")
            forums_journal.flush()
            forums_done.add(discussion_url)

        pending = interrupted_forums(out_dir, forums_done)
        if pending:
            print(f"Resuming {len(pending)} forums whose crawl was interrupted...", file=sys.stderr)
            for discussion_url, motorcycle_url in pending:
                crawl_forum(discussion_url, motorcycle_url)

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
                totals["motorcycles"] += 1

                print(f"  [{year} {i}/{len(listings)}] + {listing.brand} {listing.model}",
                      file=sys.stderr, flush=True)

                discussion_url = detail.discussion_url
                if discussion_url and discussion_url not in forums_done:
                    crawl_forum(discussion_url, listing.url)

    print(f"\nDone. {totals['motorcycles']} motorcycles, {totals['comments']} comments -> {out_dir}",
          file=sys.stderr)


if __name__ == "__main__":
    main()

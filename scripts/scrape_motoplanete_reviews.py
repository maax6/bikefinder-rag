#!/usr/bin/env python3
"""Scrape French owner reviews ("Avis des motards") from motoplanete.com.

Why: the review corpus was English-only (bikez.com forums) while the
product targets a French buyer. motoplanete's fiches carry owner reviews
written in French with a /5 rating — see
src/bikefinder_rag/scraper/motoplanete_reviews.py for the page anatomy.

Same source, same rules as scripts/scrape_motoplanete_prices.py (verified
again 2026-09-02): robots.txt allows the fiche pages with `Crawl-delay: 10`,
the CGU forbid commercial reuse and say nothing about extraction. This
scraper defaults to the 10s the site asks for; --delay lowers it at the
operator's responsibility, with the shared 429/5xx backoff.

Reviews are pooled per model, not per model-year (the 2014 and 2016
MT-07 fiches show the same reviews), so the crawl visits ONE fiche per
(brand, model) — the most recent year — from the price crawl's
prices.jsonl: 3,673 pages instead of 11,418. Comment ids deduplicate
whatever pooling differs from that assumption.

Resumable via reviews_done.txt. Output: data/motoplanete/reviews.jsonl,
one row per review (roots and replies, flagged).

    PYTHONPATH=src .venv/bin/python scripts/scrape_motoplanete_reviews.py \\
        --data data/motoplanete [--delay 10] [--limit 20]
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import scrape_motoplanete_prices as prices_scraper  # noqa: E402  (shared session, UA, backoff)
from bikefinder_rag.scraper.motoplanete_reviews import declared_review_count, parse_reviews  # noqa: E402

ROBOTS_DELAY_SECONDS = 10.0


def one_fiche_per_model(prices_path: Path) -> list[dict]:
    """The most recent fiche of every (brand, model) in prices.jsonl."""
    best: dict[tuple[str, str], dict] = {}
    with prices_path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            key = (row["brand"], row["model"].lower())
            if key not in best or row["year"] > best[key]["year"]:
                best[key] = row
    # Most recent models first: a partial crawl is then already useful to a
    # buyer (and those fiches are the ones that actually carry reviews).
    return sorted(best.values(), key=lambda r: (-r["year"], r["brand"], r["model"].lower()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=Path("data/motoplanete"))
    parser.add_argument("--delay", type=float, default=ROBOTS_DELAY_SECONDS,
                        help=f"Seconds between requests (robots.txt asks for {ROBOTS_DELAY_SECONDS:g}).")
    parser.add_argument("--limit", type=int, default=None, help="Pilot: stop after N fiches.")
    args = parser.parse_args()
    prices_scraper.DELAY_SECONDS = args.delay

    prices_path = args.data / "prices.jsonl"
    out_path = args.data / "reviews.jsonl"
    done_path = args.data / "reviews_done.txt"
    if not prices_path.exists():
        sys.exit(f"{prices_path} missing — run scrape_motoplanete_prices.py first")

    fiches = one_fiche_per_model(prices_path)
    done = set(done_path.read_text().splitlines()) if done_path.exists() else set()
    todo = [f for f in fiches if f["url"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(fiches)} models, {len(done)} fiches already done, {len(todo)} to fetch "
          f"(~{len(todo) * args.delay / 3600:.1f}h at {args.delay:g}s/page)", file=sys.stderr)

    seen_ids: set[str] = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as fh:
            seen_ids.update(json.loads(l)["comment_id"] for l in fh if l.strip())

    fetched = reviews_written = 0
    started = time.monotonic()
    with out_path.open("a", encoding="utf-8") as out, done_path.open("a") as done_out:
        for fiche in todo:
            url = fiche["url"]
            try:
                resp = prices_scraper.get(url)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {url}: {exc} — left undone", file=sys.stderr)
                time.sleep(prices_scraper.BACKOFF_SECONDS)
                continue
            if resp.status_code == 404:
                done_out.write(url + "\n"); done_out.flush()
                continue
            if resp.status_code != 200:
                print(f"  ! {url}: HTTP {resp.status_code} — left undone", file=sys.stderr)
                continue
            reviews = parse_reviews(resp.text)
            declared = declared_review_count(resp.text)
            new = 0
            for r in reviews:
                if r["comment_id"] in seen_ids:
                    continue
                seen_ids.add(r["comment_id"])
                out.write(json.dumps({
                    "fiche_url": url, "brand": fiche["brand"], "model": fiche["model"],
                    "fiche_year": fiche["year"], "declared_count": declared, **r,
                }, ensure_ascii=False) + "\n")
                new += 1
            out.flush()
            done_out.write(url + "\n"); done_out.flush()
            fetched += 1
            reviews_written += new
            if fetched % 25 == 0 or new:
                elapsed = time.monotonic() - started
                print(f"  {fetched}/{len(todo)} fiches · {reviews_written} reviews · "
                      f"{elapsed / 60:.0f} min · {fiche['brand']} {fiche['model']}: +{new}", file=sys.stderr)
    print(f"done: {fetched} fiches fetched, {reviews_written} reviews written to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Scrape French launch prices (and a clean category) from motoplanete.com.

Why motoplanete: bikez.com has no price field at all, so the database's
msrp_eur is sparse and price questions mostly end in "no price data".
motoplanete publishes the French MSRP of ~11,500 fiches in a schema.org
FAQ block ("Le prix de la X est de N € en France"), from old models
(CBR 1000 RR 2008) to the current lineup. Its robots.txt allows the fiche
pages (`Allow: /`, and they are listed in a dedicated sitemap_moto index)
with a `Crawl-delay: 10`, which this scraper respects by default. The
fiches also carry a curated category badge (Sportive, Roadster, Trail...)
that is far cleaner than bikez's loose 'Category' field — harvested too,
as a future cross-check.

Resumable at page level via urls_done.txt, same pattern as the bikez
scrapers. Output: one JSONL row per fiche, matched to our DB later by a
separate loader (brand/model/year fuzzy matching).

Run (~6.5h at the default 2s/page — robots.txt asks for 10s (~32h), the
lower default is the operator's call and the 429/5xx backoff keeps it
honest; use --limit for a pilot):
    PYTHONPATH=src .venv/bin/python scripts/scrape_motoplanete_prices.py \\
        --out data/motoplanete [--delay 10] [--limit 20]
"""

import argparse
import html as htmllib
import json
import re
import sys
import time
from pathlib import Path

import requests

BASE_URL = "https://www.motoplanete.com"
SITEMAP_INDEX = f"{BASE_URL}/sitemap_moto.php"

USER_AGENT = (
    "bikefinder-rag-project/0.1 "
    "(learning/portfolio RAG project; polite scraper; "
    "https://github.com/maax6/Bikefinder)"
)

# robots.txt asks for `Crawl-delay: 10` (~32h for the full crawl). The
# --delay flag defaults lower at the operator's responsibility; the hard
# backoff below on 429/5xx is what keeps a low delay honest — if the
# server signals stress, we stop pushing.
DEFAULT_DELAY_SECONDS = 2.0
DELAY_SECONDS = DEFAULT_DELAY_SECONDS
BACKOFF_SECONDS = 60.0
_BACKOFF_STATUSES = {429, 500, 502, 503, 504}

_FICHE_URL_RE = re.compile(
    r"motoplanete\.com/([^/]+)/(\d+)/(.+)-(\d{4})/contact\.html$"
)
# "Le prix de la G 310 R 2025 est de <strong><span ...>5&nbsp;700 €</span>..."
_PRICE_RE = re.compile(
    r"Le prix de .{0,120}? est de\s*(?:<[^>]+>\s*)*((?:\d+|&nbsp;|\s)+)€", re.S
)
# "Quel est le prix de la CBR 1000 RR Fireblade 2008 ?"
_NAME_RE = re.compile(r"Quel est le prix de (?:la |le |l')?(.*?) \?")
# The category badge near the top of the fiche: <em class="icon-sportive"></em>Sportive
_CATEGORY_RE = re.compile(r'<em class="icon-[a-z-]+"></em>([^<]+)')

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})
_last_request_at = 0.0


def get(url: str) -> requests.Response:
    global _last_request_at
    wait = DELAY_SECONDS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    response = _session.get(url, timeout=30)
    _last_request_at = time.monotonic()
    if response.status_code in _BACKOFF_STATUSES:
        time.sleep(BACKOFF_SECONDS)
        response = _session.get(url, timeout=30)
        _last_request_at = time.monotonic()
    response.raise_for_status()
    return response


def fiche_urls(cache_path: Path) -> list[str]:
    """Every fiche URL from the sitemap_moto index, deduplicated, in order.
    Cached on disk so a resumed crawl doesn't refetch 14 sitemaps; delete
    the cache file (or pass --refresh-sitemaps) to pick up new fiches."""
    if cache_path.exists():
        urls = cache_path.read_text().splitlines()
        print(f"{len(urls)} fiche URLs from cache ({cache_path.name}); "
              "use --refresh-sitemaps to refetch.", file=sys.stderr)
        return urls

    index = get(SITEMAP_INDEX).text
    sitemap_urls = re.findall(r"<loc>(.*?)</loc>", index)
    urls: list[str] = []
    for i, sitemap_url in enumerate(sitemap_urls, 1):
        body = get(sitemap_url).text
        found = [u for u in re.findall(r"<loc>(.*?)</loc>", body) if _FICHE_URL_RE.search(u)]
        urls.extend(found)
        print(f"  sitemap {i}/{len(sitemap_urls)}: {len(found)} fiches "
              f"({len(urls)} total)", file=sys.stderr)
    urls = list(dict.fromkeys(urls))
    cache_path.write_text("\n".join(urls) + "\n")
    return urls


def parse_fiche(url: str, page: str) -> dict:
    brand_slug, _, model_slug, year = _FICHE_URL_RE.search(url).groups()

    price_eur = None
    if m := _PRICE_RE.search(page):
        digits = re.sub(r"\D", "", m.group(1))
        if digits:
            price_eur = int(digits)

    # Prefer the display name from the FAQ block over the URL slug; strip
    # the trailing year it always carries.
    name = None
    if m := _NAME_RE.search(page):
        name = htmllib.unescape(m.group(1)).removesuffix(f" {year}").strip()

    category = None
    if m := _CATEGORY_RE.search(page):
        category = htmllib.unescape(m.group(1)).strip()

    return {
        "url": url,
        "brand": brand_slug.replace("-", " "),
        "model": name or model_slug.replace("-", " "),
        "year": int(year),
        "price_eur": price_eur,
        "category_fr": category,
    }


def main() -> None:
    global DELAY_SECONDS

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/motoplanete")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N new pages (pilot runs).")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS,
                        help="Seconds between requests (robots.txt asks for 10; "
                             f"default {DEFAULT_DELAY_SECONDS} at your own responsibility).")
    parser.add_argument("--refresh-sitemaps", action="store_true",
                        help="Refetch the sitemaps instead of using the cached URL list.")
    args = parser.parse_args()
    DELAY_SECONDS = args.delay

    out_dir = Path(__file__).resolve().parent.parent / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    prices_path = out_dir / "prices.jsonl"
    done_path = out_dir / "urls_done.txt"
    sitemap_cache = out_dir / "fiche_urls.txt"

    done = set(done_path.read_text().splitlines()) if done_path.exists() else set()

    if args.refresh_sitemaps and sitemap_cache.exists():
        sitemap_cache.unlink()
    urls = fiche_urls(sitemap_cache)
    todo = [u for u in urls if u not in done]
    eta_h = len(todo) * args.delay / 3600
    print(f"{len(urls)} fiches in sitemaps, {len(done)} already done, "
          f"{len(todo)} to fetch at {args.delay}s/page (~{eta_h:.1f}h).", file=sys.stderr)

    scraped = 0
    started = time.monotonic()
    with prices_path.open("a", encoding="utf-8") as out, done_path.open("a") as done_out:
        for url in todo:
            if args.limit is not None and scraped >= args.limit:
                break
            try:
                page = get(url).text
            except requests.HTTPError as exc:
                # A dead fiche shouldn't block the crawl; mark it done.
                print(f"  skip {url}: {exc}", file=sys.stderr)
                done_out.write(url + "\n")
                done_out.flush()
                continue
            except requests.RequestException as exc:
                # Transient network trouble (read timeout, reset...) must not
                # kill a 32h crawl: back off and move on, leaving the URL
                # undone so the next run retries it.
                print(f"  network error, will retry next run: {url}: {exc}", file=sys.stderr)
                time.sleep(BACKOFF_SECONDS)
                continue
            row = parse_fiche(url, page)
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            done_out.write(url + "\n")
            done_out.flush()
            scraped += 1
            price = f"{row['price_eur']} €" if row["price_eur"] else "prix absent"
            print(f"[{scraped}/{len(todo)}] {row['brand']} {row['model']} "
                  f"{row['year']} — {price} ({row['category_fr'] or '?'})", file=sys.stderr)
            if scraped % 50 == 0:
                rate = scraped / (time.monotonic() - started)
                remaining_h = (len(todo) - scraped) / rate / 3600 if rate else 0
                print(f"  --- {rate:.2f} pages/s, ~{remaining_h:.1f}h restantes", file=sys.stderr)

    print(f"Done: {scraped} fiches scraped this run -> {prices_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

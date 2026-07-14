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

Run (full crawl is ~32h at the robots.txt-mandated 10s/page; use --limit
for a pilot):
    PYTHONPATH=src .venv/bin/python scripts/scrape_motoplanete_prices.py \\
        --out data/motoplanete --limit 20
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

# robots.txt says `Crawl-delay: 10` — that is the floor, not a suggestion.
DELAY_SECONDS = 10.0
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


def fiche_urls() -> list[str]:
    """Every fiche URL from the sitemap_moto index, deduplicated, in order."""
    index = get(SITEMAP_INDEX).text
    urls: list[str] = []
    for sitemap_url in re.findall(r"<loc>(.*?)</loc>", index):
        body = get(sitemap_url).text
        urls.extend(u for u in re.findall(r"<loc>(.*?)</loc>", body) if _FICHE_URL_RE.search(u))
    return list(dict.fromkeys(urls))


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/motoplanete")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N new pages (pilot runs).")
    args = parser.parse_args()

    out_dir = Path(__file__).resolve().parent.parent / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    prices_path = out_dir / "prices.jsonl"
    done_path = out_dir / "urls_done.txt"

    done = set(done_path.read_text().splitlines()) if done_path.exists() else set()

    urls = fiche_urls()
    todo = [u for u in urls if u not in done]
    print(f"{len(urls)} fiches in sitemaps, {len(done)} already done, "
          f"{len(todo)} to fetch.", file=sys.stderr)

    scraped = 0
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
            row = parse_fiche(url, page)
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            done_out.write(url + "\n")
            done_out.flush()
            scraped += 1
            if scraped % 25 == 0:
                print(f"  {scraped}/{len(todo)} fetched", file=sys.stderr)

    print(f"Done: {scraped} fiches scraped this run -> {prices_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

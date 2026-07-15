#!/usr/bin/env python3
"""Load motoplanete French launch prices and categories into motorcycles.

Input: data/motoplanete/prices.jsonl from scrape_motoplanete_prices.py
(one row per fiche: brand, model, year, price_eur, category_fr).

Matching (fiche -> our rows): token-level containment over the
concatenated brand+model of both sides — every fiche token must be a
token of the row, and the row with the fewest extra tokens wins. The
concatenation is what heals our bikez scrape's multi-word-brand split
(brand='MV' model='Agusta Brutale...'); a second pass drops the fiche's
displacement-suffix tokens ('YZF-R1 1000' vs 'YZF-R1'), and a ±1-year
fallback covers the launch-year/model-year off-by-one between the sites.

Updates:
- msrp_eur: overwritten with the motoplanete price (bikez has no price
  field; what little msrp_eur held before came from nowhere better).
- category_fr: new column, motoplanete's curated badge (Roadster,
  Sportive, Trail, Supermotard...) — far cleaner than bikez's Category
  and usable as a cross-check.

Fiche years outside 1894-2027 are slug artifacts (the URL's trailing
digits are not always a year) and are skipped.

Run:
    PYTHONPATH=src .venv/bin/python scripts/load_motoplanete_prices.py
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
load_dotenv()

from bikefinder_rag.db.client import get_connection

PRICES_PATH = Path(__file__).resolve().parent.parent / "data/motoplanete/prices.jsonl"

ALTER = "ALTER TABLE motorcycles ADD COLUMN IF NOT EXISTS category_fr TEXT"


def _tokens(s: str) -> list[str]:
    """Alternating alpha/digit tokens: 'ZX-10R 1000' -> ['zx','10','r','1000'].
    Token-level (not substring) matching is what keeps '1098 R' from
    matching 'Superbike 1098 S' via the 'r' inside 'Superbike'."""
    return re.findall(r"[a-z]+|\d+", str(s).lower())


# motoplanete brand slugs vs how our bikez scrape (mis)split multi-word
# brands (brand='MV' model='Agusta ...', brand='Moto' model='Guzzi ...').
# Matching runs on the concatenated brand+model tokens so most of those
# heal by themselves; these aliases cover the slugs whose tokens differ.
_BRAND_ALIASES = {
    "cfmoto": "cf moto",
    "victory usa": "victory",
    "zero motorcycles": "zero",
    "royal enfield": "enfield",
    "mz  muz": "mz",
}


def main() -> None:
    fiches = [json.loads(line) for line in PRICES_PATH.open(encoding="utf-8")]
    fiches = [f for f in fiches if 1894 <= f["year"] <= 2027]
    print(f"{len(fiches)} fiches with a plausible year.", file=sys.stderr)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(ALTER)

        by_year: dict[int, list] = defaultdict(list)
        with conn.cursor() as cur:
            cur.execute("SELECT id, brand, model, year FROM motorcycles")
            for mid, brand, model, year in cur.fetchall():
                by_year[year].append((mid, set(_tokens(f"{brand} {model}"))))

        def match_year(fiche_tokens: list[str], year: int) -> list[int]:
            """Rows of `year` whose brand+model tokens contain every fiche
            token; tightest (fewest extra tokens) wins. Second pass drops the
            fiche's displacement-suffix tokens ('YZF-R1 1000') if the strict
            pass found nothing."""
            for required in (fiche_tokens,
                             [t for t in fiche_tokens if not (t.isdigit() and int(t) >= 50)]):
                if not required:
                    continue
                best_extra, best_ids = None, []
                for mid, row_tokens in by_year.get(year, []):
                    if not all(t in row_tokens for t in required):
                        continue
                    extra = len(row_tokens - set(required))
                    if best_extra is None or extra < best_extra:
                        best_extra, best_ids = extra, [mid]
                    elif extra == best_extra:
                        best_ids.append(mid)
                if best_ids:
                    return best_ids

            # Reverse direction: the fiche is the verbose side ('CBR 1000 RR
            # Fireblade' vs our 'CBR 1000 RR') — every row token must appear
            # in the fiche, most-specific (most tokens) row wins. Two tokens
            # minimum, otherwise a bare brand row would match anything.
            fiche_set = set(fiche_tokens)
            best_size, best_ids = 0, []
            for mid, row_tokens in by_year.get(year, []):
                if len(row_tokens) < 3 or not row_tokens <= fiche_set:
                    continue
                if len(row_tokens) > best_size:
                    best_size, best_ids = len(row_tokens), [mid]
                elif len(row_tokens) == best_size:
                    best_ids.append(mid)
            return best_ids

        priced = categorized = matched_fiches = year_shifted = 0
        with conn.cursor() as cur:
            for fiche in fiches:
                brand = _BRAND_ALIASES.get(fiche["brand"], fiche["brand"])
                fiche_tokens = _tokens(f"{brand} {fiche['model']}")

                best_ids = match_year(fiche_tokens, fiche["year"])
                # Launch year vs model year is often off by one between the
                # two sites; a ±1 fallback keeps the price representative.
                if not best_ids:
                    for dy in (-1, 1):
                        best_ids = match_year(fiche_tokens, fiche["year"] + dy)
                        if best_ids:
                            year_shifted += 1
                            break
                if not best_ids:
                    continue
                matched_fiches += 1
                if fiche["price_eur"]:
                    cur.execute(
                        "UPDATE motorcycles SET msrp_eur = %s WHERE id = ANY(%s)",
                        (fiche["price_eur"], best_ids),
                    )
                    priced += cur.rowcount
                if fiche["category_fr"]:
                    cur.execute(
                        "UPDATE motorcycles SET category_fr = %s WHERE id = ANY(%s)",
                        (fiche["category_fr"], best_ids),
                    )
                    categorized += cur.rowcount

        print(f"{matched_fiches} fiches matched ({year_shifted} via the ±1-year "
              f"fallback); {priced} motorcycles got a price, "
              f"{categorized} a French category.", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

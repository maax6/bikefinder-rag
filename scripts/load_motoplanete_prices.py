#!/usr/bin/env python3
"""Load motoplanete French launch prices and categories into motorcycles.

Input: data/motoplanete/prices.jsonl from scrape_motoplanete_prices.py
(one row per fiche: brand, model, year, price_eur, category_fr).

Matching (fiche -> our rows): motoplanete's names tend to be supersets of
bikez's ('CBR 1000 RR Fireblade' vs 'CBR 1000 RR'), so a fiche is matched
to the motorcycles of the same normalized brand and year whose model
words ALL appear in the fiche's model text — and only the best (longest)
such match wins, so a 'GSF 1200 S Bandit' fiche lands on the S, not on
every Bandit trim of that year.

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


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def main() -> None:
    fiches = [json.loads(line) for line in PRICES_PATH.open(encoding="utf-8")]
    fiches = [f for f in fiches if 1894 <= f["year"] <= 2027]
    print(f"{len(fiches)} fiches with a plausible year.", file=sys.stderr)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(ALTER)

        by_brand_year: dict[tuple[str, int], list] = defaultdict(list)
        with conn.cursor() as cur:
            cur.execute("SELECT id, brand, model, year FROM motorcycles")
            for mid, brand, model, year in cur.fetchall():
                words = re.sub(r"[^a-z0-9 ]", "", model.lower()).split()
                by_brand_year[(_norm(brand), year)].append((mid, words))

        priced = categorized = matched_fiches = 0
        with conn.cursor() as cur:
            for fiche in fiches:
                candidates = by_brand_year.get((_norm(fiche["brand"]), fiche["year"]))
                if not candidates:
                    continue
                text = _norm(fiche["model"])
                best_len, best_ids = 0, []
                for mid, words in candidates:
                    if not words or not all(w in text for w in words):
                        continue
                    length = len("".join(words))
                    if length > best_len:
                        best_len, best_ids = length, [mid]
                    elif length == best_len:
                        best_ids.append(mid)
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

        print(f"{matched_fiches} fiches matched; {priced} motorcycles got a price, "
              f"{categorized} a French category.", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

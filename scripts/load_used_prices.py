#!/usr/bin/env python3
"""Load indicative used-market prices from the Kaggle motorbike marketplace.

Source: mexwell/motorbike-marketplace on Kaggle (~35k European AutoScout24
listings captured in 2022 — registration years top out there). Asking
prices, not sale prices, and a single snapshot: good enough for an
*indicative* cote ("a 2002 GSF 1200 S with 46k km listed around 3,300 €"),
not a pricing service. The snapshot year is stored so the agent can say
how old the estimate is.

Listings are matched to our model families the same way as NHTSA recalls
(normalized brand prefix + every family-name word present + registration
year inside the family's production window), junk prices are dropped
(outside 200-80,000 €), and what lands in Postgres is aggregates only:
median/quartiles per (family, registration year), plus one family-level
rollup row (reg_year NULL) — no listing-level data is republished.

Run (downloads the dataset via kagglehub on first use, ~2 MB):
    PYTHONPATH=src .venv/bin/python scripts/load_used_prices.py
"""

import sys
from pathlib import Path

import kagglehub
import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
load_dotenv()

from bikefinder_rag.db.client import get_connection
from bikefinder_rag.matching import MotorcycleMatcher

KAGGLE_DATASET = "mexwell/motorbike-marketplace"
SNAPSHOT_YEAR = 2022
PRICE_MIN, PRICE_MAX = 200, 80_000
MIN_LISTINGS_PER_CELL = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS used_price_estimates (
    id              SERIAL PRIMARY KEY,
    family_id       INTEGER NOT NULL REFERENCES model_families(id),
    reg_year        INTEGER,            -- NULL = all years of the family
    n_listings      INTEGER NOT NULL,
    price_median    INTEGER NOT NULL,
    price_p25       INTEGER NOT NULL,
    price_p75       INTEGER NOT NULL,
    mileage_median  INTEGER,
    snapshot_year   INTEGER NOT NULL,
    UNIQUE NULLS NOT DISTINCT (family_id, reg_year)
);
CREATE INDEX IF NOT EXISTS used_price_family_idx ON used_price_estimates (family_id);
"""


def match_listings(df: pd.DataFrame, conn) -> pd.Series:
    """family_id per listing (NaN when unmatched). Listings are matched
    against concrete model-year rows with the shared token matcher, then
    rolled up to the row's family — precise by construction, and immune to
    bikez's family split ('Bandit' vs 'GSF 1200 Bandit' are different
    forums, but their bikes carry the right family_id). Registration year
    lags model year, hence the backward-leaning offsets. A listing whose
    tightest matches straddle several families is ambiguous and dropped."""
    with conn.cursor() as cur:
        cur.execute("SELECT family_id, brand, model, year FROM motorcycles WHERE family_id IS NOT NULL")
        matcher = MotorcycleMatcher((fid, b, m, y) for fid, b, m, y in cur.fetchall())

    def match(text: str, reg_year: float):
        fids, _ = matcher.match("", text, int(reg_year), year_offsets=(0, -1, -2, -3, 1))
        distinct = set(fids)
        return fids[0] if len(distinct) == 1 else None

    return df.apply(lambda r: match(r["text"], r["reg_year"]), axis=1)


def main() -> None:
    path = Path(kagglehub.dataset_download(KAGGLE_DATASET)) / "europe-motorbikes-zenrows.csv"
    df = pd.read_csv(path)
    df["text"] = df.make_model.fillna("") + " " + df.version.fillna("")
    df["reg_year"] = pd.to_numeric(df.date.str.extract(r"/(\d{4})")[0], errors="coerce")

    df = df[df.price.between(PRICE_MIN, PRICE_MAX) & (df.offer_type == "Used") & df.reg_year.notna()]
    print(f"{len(df)} plausible used listings after filtering.", file=sys.stderr)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)

        df = df.assign(family_id=match_listings(df, conn))
        matched = df[df.family_id.notna()]
        print(f"{len(matched)} listings matched to a model family.", file=sys.stderr)

        rows = 0
        with conn.cursor() as cur:
            cur.execute("DELETE FROM used_price_estimates WHERE snapshot_year = %s", (SNAPSHOT_YEAR,))
            groups = [(keys, g) for keys, g in matched.groupby(["family_id", "reg_year"])]
            groups += [((fid, None), g) for fid, g in matched.groupby("family_id")]
            for (fid, reg_year), g in groups:
                if len(g) < MIN_LISTINGS_PER_CELL:
                    continue
                cur.execute(
                    """
                    INSERT INTO used_price_estimates
                        (family_id, reg_year, n_listings, price_median, price_p25,
                         price_p75, mileage_median, snapshot_year)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (family_id, reg_year) DO NOTHING
                    """,
                    (
                        int(fid), int(reg_year) if reg_year is not None else None, len(g),
                        int(g.price.median()), int(g.price.quantile(0.25)),
                        int(g.price.quantile(0.75)),
                        int(g.mileage.median()) if g.mileage.notna().any() else None,
                        SNAPSHOT_YEAR,
                    ),
                )
                rows += cur.rowcount
        print(f"{rows} (family, reg_year) aggregate rows written "
              f"(min {MIN_LISTINGS_PER_CELL} listings per cell).", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

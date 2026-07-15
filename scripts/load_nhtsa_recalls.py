#!/usr/bin/env python3
"""Load NHTSA safety recalls and attach them to our model families.

NHTSA's Office of Defects Investigation publishes every US recall
campaign since 1967 as free flat files (no key, no rate limit):
    https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_PRE_2010.zip
    https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip

This is the project's only *objective* reliability signal — owner
comments say "mine broke down", a recall says the manufacturer filed a
defect report and how many units it touched.

The files have no vehicle-type field and car makers share MAKETXT with
their motorcycle divisions (HONDA covers Accords and CB 500s alike), so
a row is kept only when its make matches one of our brands AND every
word of one of our family names appears in its MODELTXT AND the model
year is compatible with the family's year range (9999 = unknown, kept).
Families whose normalized name is shorter than 3 characters are skipped
as join keys — too ambiguous.

Run (downloads ~22 MB zipped on first use, cached in data/nhtsa/):
    PYTHONPATH=src .venv/bin/python scripts/load_nhtsa_recalls.py
"""

import csv
import io
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
load_dotenv()

from bikefinder_rag.db.client import get_connection

FLAT_FILES = [
    "https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_PRE_2010.zip",
    "https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip",
]
CACHE_DIR = Path(__file__).resolve().parent.parent / "data/nhtsa"

SCHEMA = """
CREATE TABLE IF NOT EXISTS recalls (
    id SERIAL PRIMARY KEY,
    family_id INTEGER NOT NULL REFERENCES model_families(id),
    campno TEXT NOT NULL,
    nhtsa_make TEXT NOT NULL,
    nhtsa_model TEXT NOT NULL,
    model_year INTEGER,
    component TEXT,
    defect TEXT,
    consequence TEXT,
    corrective TEXT,
    units_affected INTEGER,
    report_date DATE,
    UNIQUE NULLS NOT DISTINCT (campno, family_id, model_year)
);
CREATE INDEX IF NOT EXISTS recalls_family_idx ON recalls (family_id);
"""

csv.field_size_limit(10**7)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _parse_date(yyyymmdd: str) -> date | None:
    if not re.fullmatch(r"\d{8}", yyyymmdd or ""):
        return None
    try:
        return date(int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))
    except ValueError:
        return None


def _flat_file_rows():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for url in FLAT_FILES:
        cached = CACHE_DIR / url.rsplit("/", 1)[1]
        if not cached.exists():
            print(f"Downloading {url}...", file=sys.stderr)
            cached.write_bytes(requests.get(url, timeout=120).content)
        with zipfile.ZipFile(cached) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as raw:
                text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
                yield from csv.reader(text, delimiter="\t", quoting=csv.QUOTE_NONE)


def load_families(conn) -> dict[str, list[tuple[int, list[str], int, int]]]:
    """brand(normalized) -> [(family_id, name words, year_min, year_max)]."""
    by_brand: dict[str, list] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT id, brand, family_name, year_min, year_max FROM model_families")
        for fid, brand, name, ymin, ymax in cur.fetchall():
            words = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
            if len("".join(words)) < 3:
                continue  # 'R', 'GS'... would match half the recall file
            by_brand.setdefault(_norm(brand), []).append((fid, words, ymin, ymax))
    return by_brand


def main() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)

        by_brand = load_families(conn)
        scanned = inserted = 0
        with conn.cursor() as cur:
            for rec in _flat_file_rows():
                if len(rec) < 23:
                    continue
                make = _norm(rec[2])
                candidates = by_brand.get(make)
                if not candidates:
                    continue
                scanned += 1
                model_normed = _norm(rec[3])
                year = int(rec[4]) if re.fullmatch(r"\d{4}", rec[4]) else None
                if year == 9999:
                    year = None
                for fid, words, ymin, ymax in candidates:
                    if not all(w in model_normed for w in words):
                        continue
                    # A model-year outside the family's production range is
                    # a different vehicle that happens to share name words.
                    if year is not None and not (ymin - 1 <= year <= ymax + 1):
                        continue
                    cur.execute(
                        """
                        INSERT INTO recalls (family_id, campno, nhtsa_make, nhtsa_model,
                                             model_year, component, defect, consequence,
                                             corrective, units_affected, report_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (campno, family_id, model_year) DO NOTHING
                        """,
                        (
                            fid, rec[1], rec[2], rec[3], year, rec[6] or None,
                            rec[19] or None, rec[20] or None, rec[21] or None,
                            int(rec[11]) if rec[11].isdigit() else None,
                            _parse_date(rec[15]),
                        ),
                    )
                    inserted += cur.rowcount

        print(f"{scanned} recall rows carried one of our brands; "
              f"{inserted} (campaign, family, year) rows inserted.", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

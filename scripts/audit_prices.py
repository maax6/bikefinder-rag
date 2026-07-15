#!/usr/bin/env python3
"""Human ground-truth audit of the price matching (layer: data quality).

The price pipeline's failure mode isn't motoplanete being wrong — it's
OUR matching attaching a fiche's price to the wrong bike (wrong trim,
wrong year). Prices are cheap for a human to verify (one look at the
fiche), unlike forum comments, so this is where a manual ground truth
pays: audit a stratified sample, publish the measured precision.

Two modes:

    # 1. Generate the sample to review (stratified over the match rules,
    #    riskiest buckets oversampled):
    PYTHONPATH=src .venv/bin/python scripts/audit_prices.py generate

    # 2. After a human filled the `verdict` column with ok/ko:
    PYTHONPATH=src .venv/bin/python scripts/audit_prices.py score

The sample lives in eval_results/prices/audit_sample.md — the filled
file IS the ground truth, committed as-is; `score` appends the measured
precision to the report JSON next to it.
"""

import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
load_dotenv()

from bikefinder_rag.db.client import get_connection
from bikefinder_rag.matching import MotorcycleMatcher

ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = ROOT / "data/motoplanete/prices.jsonl"
SAMPLE_PATH = ROOT / "eval_results/prices/audit_sample.md"
REPORT_PATH = ROOT / "eval_results/prices/audit_report.json"

# Per-bucket sample sizes: the fallback rules are the risky ones, so they
# are oversampled relative to their share of matches.
SAMPLE_PLAN = {"forward+0": 20, "shifted": 15, "reverse": 15}
SEED = 42

_BRAND_ALIASES = {
    "cfmoto": "cf moto",
    "victory usa": "victory",
    "zero motorcycles": "zero",
    "royal enfield": "enfield",
    "mz  muz": "mz",
}


def replay_matches(conn):
    """(fiche, bike row, dy, pass) for every priced fiche the loader
    matches — same inputs, same matcher, same outcome as the loader."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, brand, model, year FROM motorcycles")
        rows = cur.fetchall()
    by_id = {r[0]: r for r in rows}
    matcher = MotorcycleMatcher(rows)

    out = []
    for line in PRICES_PATH.open(encoding="utf-8"):
        fiche = json.loads(line)
        if not (1894 <= fiche["year"] <= 2027) or not fiche["price_eur"]:
            continue
        brand = _BRAND_ALIASES.get(fiche["brand"], fiche["brand"])
        ids, dy, how = matcher.match_explained(brand, fiche["model"], fiche["year"])
        if ids:
            out.append((fiche, by_id[ids[0]], dy, how))
    return out


def bucket(dy, how):
    if how == "reverse":
        return "reverse"
    return "forward+0" if dy == 0 else "shifted"


def generate() -> None:
    conn = get_connection()
    try:
        matches = replay_matches(conn)
    finally:
        conn.close()

    by_bucket = defaultdict(list)
    for m in matches:
        by_bucket[bucket(m[2], m[3])].append(m)

    rng = random.Random(SEED)
    lines = [
        "# Audit humain du matching prix (échantillon stratifié)",
        "",
        "Pour chaque ligne : ouvrir l'URL, vérifier que la fiche motoplanete",
        "correspond bien à **notre moto** (bonne variante, bonne année) et que",
        "le prix affiché est celui de la fiche. Remplir `verdict` avec `ok`",
        "ou `ko` (et un mot de raison après `ko:` si utile).",
        "",
        "| # | verdict | notre moto | prix retenu | fiche motoplanete | match | url |",
        "|---|---------|-----------|-------------|-------------------|-------|-----|",
    ]
    i = 0
    for bkt, want in SAMPLE_PLAN.items():
        pool = by_bucket.get(bkt, [])
        for fiche, (mid, brand, model, year), dy, how in rng.sample(pool, min(want, len(pool))):
            i += 1
            kind = bkt if bkt != "shifted" else f"année{dy:+d}"
            lines.append(
                f"| {i} | ? | {brand} {model} {year} | {fiche['price_eur']} € "
                f"| {fiche['brand']} {fiche['model']} {fiche['year']} | {kind} | {fiche['url']} |"
            )
    print("buckets disponibles:", {k: len(v) for k, v in by_bucket.items()}, file=sys.stderr)

    SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAMPLE_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{i} lignes à auditer -> {SAMPLE_PATH}", file=sys.stderr)


def score() -> None:
    verdicts = defaultdict(lambda: {"ok": 0, "ko": 0, "pending": 0})
    for line in SAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*\d+\s*\|\s*(\S+)\s*\|.*\|\s*(\S+)\s*\|\s*\S+\s*\|$", line)
        if not m:
            continue
        verdict, kind = m.group(1).lower(), m.group(2)
        kind = "shifted" if kind.startswith("année") else kind
        if verdict.startswith("ok"):
            verdicts[kind]["ok"] += 1
        elif verdict.startswith("ko"):
            verdicts[kind]["ko"] += 1
        else:
            verdicts[kind]["pending"] += 1

    total_ok = sum(v["ok"] for v in verdicts.values())
    total_ko = sum(v["ko"] for v in verdicts.values())
    pending = sum(v["pending"] for v in verdicts.values())
    if pending:
        print(f"{pending} lignes sans verdict — audit incomplet.", file=sys.stderr)
    report = {
        "audited": total_ok + total_ko,
        "ok": total_ok,
        "ko": total_ko,
        "precision": round(total_ok / (total_ok + total_ko), 4) if total_ok + total_ko else None,
        "per_bucket": {k: {**v, "precision": round(v["ok"] / (v["ok"] + v["ko"]), 4)
                           if v["ok"] + v["ko"] else None}
                       for k, v in verdicts.items()},
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    {"generate": generate, "score": score}.get(
        sys.argv[1] if len(sys.argv) > 1 else "generate", generate)()

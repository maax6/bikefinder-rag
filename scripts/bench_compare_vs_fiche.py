#!/usr/bin/env python3
"""Measure fiche-by-fiche vs comparator collection on the same sample, same pacing."""
import json, sys, time, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bikefinder_rag.scraper.motoplanete_compare import CompareClient, crawl_batched
from bikefinder_rag.scraper.motoplanete_technical import parse_technical_page
from bikefinder_rag.scraper.technical_crawl import CrawlStore, crawl

urls_file, n = Path(sys.argv[1]), int(sys.argv[2])
all_urls = [u for u in urls_file.read_text().split() if u]
step = max(1, len(all_urls) // n)
sample = all_urls[::step][:n]
client = CompareClient(10.0)
count = {"n": 0}
orig_get = client.session.get
def counting_get(*a, **k):
    count["n"] += 1
    return orig_get(*a, **k)
client.session.get = counting_get
work = Path(tempfile.mkdtemp(prefix="bench-mp-"))
client.check_access(work)
results = {}
for name, fn in (("fiche", lambda s: crawl(s, client, parse_technical_page, limit=None)),
                 ("compare", lambda s: crawl_batched(s, client, parse_technical_page, limit=None, on_progress=None))):
    store = CrawlStore(work / name); store.seed(sample)
    before, t0 = count["n"], time.monotonic()
    rep = fn(store)
    rows = {r[0]: json.loads(r[1]) for r in store.conn.execute("SELECT url,result FROM pages WHERE result IS NOT NULL")}
    results[name] = {"seconds": round(time.monotonic() - t0, 1), "requests": count["n"] - before,
                     "states": rep["states"], "rows": rows}
    print(name, {k: v for k, v in results[name].items() if k != "rows"}, flush=True)
norm = lambda v: "".join(v.split()).replace("*", "").replace(",", ".").casefold()
cover = []
for u in sample:
    f, c = results["fiche"]["rows"].get(u), results["compare"]["rows"].get(u)
    if not f or not c:
        cover.append((u, None)); continue
    cvals = " | ".join(norm(r["value"]) + " " + norm(r["label"]) for r in c["spec_rows"])
    fvals = [norm(r["value"]) for r in f["spec_rows"]]
    missing = [r for r in f["spec_rows"] if norm(r["value"]) not in cvals]
    cover.append((u, {"fiche_rows": len(fvals), "compare_rows": len(c["spec_rows"]),
                      "fiche_values_found": len(fvals) - len(missing), "missing": missing,
                      "colors_fiche": sum(r["section"] == "Coloris" for r in f["spec_rows"]),
                      "colors_compare": sum(r["section"] == "Coloris" for r in c["spec_rows"]),
                      "equip_fiche": len(f["equipment_evidence"]), "equip_compare": len(c["equipment_evidence"]),
                      "identity_same": (f["identity"]["brand"], f["identity"]["model"], f["identity"]["year"]) ==
                                       (c["identity"]["brand"], c["identity"]["model"], c["identity"]["year"])}))
out = {"sample": sample, "summary": {k: {x: y for x, y in v.items() if x != "rows"} for k, v in results.items()},
       "coverage": cover, "workdir": str(work)}
Path(work / "bench.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
tot_f = sum(c["fiche_rows"] for _, c in cover if c); tot_found = sum(c["fiche_values_found"] for _, c in cover if c)
print("value recall", tot_found, "/", tot_f, "workdir", work)

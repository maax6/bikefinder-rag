"""Prepare offline constructor snapshots and a small SQL/BGE experiment index."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

from bs4 import BeautifulSoup
from dotenv import load_dotenv
import numpy as np
import requests

from bikefinder_rag.catalog.enriched import _rows
from bikefinder_rag.catalog.research import load_index
from bikefinder_rag.catalog.technical_rag import documents, normalized_vectors
from bikefinder_rag.db.client import get_connection
from bikefinder_rag.embeddings import embedder

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "src/bikefinder_rag/catalog/manufacturer_sources.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_documents(source, snapshot):
    soup = BeautifulSoup(snapshot.read_bytes(), "html.parser")
    article = soup.select_one("#article-text, #release-media") or soup.find("article")
    if article is None:
        raise ValueError("Source article not found; never index the navigation")
    title_node = soup.select_one(".article-detail h1") or article.find("h1")
    if title_node is None:
        raise ValueError("Article title not found")
    title = title_node.get_text(" ", strip=True)
    date_node = soup.select_one(".title__timeplace, .article-detail h5, .visibilitydate")
    if date_node is None:
        raise ValueError("Source publication date not found")
    date_text = date_node.get_text(" ", strip=True)
    if source["publisher"] == "Honda" and source["market"] == "France":
        months = {"janv.": 1, "févr.": 2, "mars": 3, "avr.": 4, "mai": 5,
                  "juin": 6, "juil.": 7, "août": 8, "sept.": 9, "oct.": 10,
                  "nov.": 11, "déc.": 12}
        day, month, year = date_text.split()
        published = datetime(int(year), months[month], int(day)).date().isoformat()
    elif source["publisher"] == "Honda":
        published = datetime.strptime(date_text.split(", U.S.A.")[0], "%B %d, %Y").date().isoformat()
    else:
        parts = date_text.split()
        published = datetime.strptime(" ".join(parts[1:3]) + " " + re.search(r"\b20\d{2}\b", date_text)[0], "%b %d %Y").date().isoformat()
    if published != source["published"] or (source["model_year"] is not None and str(source["model_year"]) not in title):
        raise ValueError("Declared temporal metadata does not match the original heading")
    section, result = title, []
    for node in article.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        if node.find_parent(["p", "li"]) is not None:
            continue
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if not text:
            continue
        if text == "Video Gallery":
            break
        if node.name.startswith("h") or (node.name == "p" and (
                (len(text) < 140 and re.match(r"^\d+\.\d+\.\s", text)) or
                (len(text) < 45 and not re.search(r"\d|[.!?:,]|\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\b", text, re.I)))):
            section = text
            continue
        doc = {"id": f"{source['id']}:paragraph:{len(result)}", "object_id": source["id"],
               "brand": source["brand"], "model": source["model"], "year": source["model_year"],
               "publisher": source["publisher"], "kind": "manufacturer", "market": source["market"],
               "published": source["published"], "family": source["family"], "binding_year": source["catalog_binding_year"],
               "source_url": source["url"], "source_sha256": digest(snapshot),
               "section": section, "original_text": text,
               "text": f"{title}\n{source['market']} ; publication {source['published']}\n{section}\n{text}"}
        result.append(doc)
    if not result:
        raise ValueError("Constructor source contains no usable passages")
    return result


def prepare(root, snapshots):
    load_dotenv(ROOT / ".env")
    started = time.perf_counter()
    if (root / "manifest.json").exists():
        raise FileExistsError("Prepared evidence is immutable; choose a fresh directory")
    root.mkdir(parents=True, exist_ok=True)
    snapshots.mkdir(parents=True, exist_ok=True)
    sources = json.loads(CONFIG.read_text())["sources"]
    with requests.Session() as session:
        session.trust_env = False
        session.headers["User-Agent"] = "Mozilla/5.0"
        for source in sources:
            snapshot = snapshots / (source["id"] + ".html")
            if not snapshot.exists():
                response = session.get(source["url"], timeout=20, allow_redirects=False)
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("Source redirected; verify the new source explicitly")
                snapshot.write_bytes(response.content)
    docs, rows, bindings = [], {}, {}
    with get_connection() as conn:
        conn.execute("SET default_transaction_read_only = on")
        for source in sources:
            found = _rows(conn, "SELECT id,brand,model,year,source_url,source_sha256,record FROM technical_fiches WHERE lower(brand)=lower(%s) AND model ~* %s ORDER BY year,model,id",
                          [source["brand"], source["sql_model_pattern"]])
            family_rows = [r for r in found if r["year"] == source["catalog_binding_year"] and re.search(source["binding_pattern"], r["model"], re.I)]
            if not family_rows:
                raise ValueError("Constructor model lacks a verified SQL catalogue binding")
            bindings[source["id"]] = [{k: r[k] for k in ["id", "brand", "model", "year", "source_sha256"]} for r in family_rows]
            for row in found:
                if row["id"] not in rows:
                    rows[row["id"]] = row
                    docs.extend({**d, "kind": "catalogue", "publisher": "Motoplanète", "family": source["family"], "market": "Non établi", "published": None} for d in documents(row))
    base = ROOT / "data/technical/retrieval-benchmark-20261013/index"
    files = [base / name for name in ["index-manifest.json", "documents.jsonl", "vectors.npy", "protocol.json"]]
    indexed, vectors = load_index(str(base), tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in files))
    selected = []
    for doc in docs:
        i, saved = indexed[doc["id"]]
        if any(doc[k] != saved[k] for k in ["original_text", "text", "source_sha256", "model", "year"]):
            raise ValueError("Existing embedding is not bound to this live source")
        selected.append(i)
    constructor = [d for s in sources for d in source_documents(s, snapshots / (s["id"] + ".html"))]
    encoding_started = time.perf_counter()
    encoded = normalized_vectors(embedder.embed_texts([d["text"] for d in constructor]), len(constructor))
    encoding_seconds = time.perf_counter() - encoding_started
    values = np.concatenate([normalized_vectors(vectors[selected], len(docs)), encoded])
    docs += constructor
    (root / "documents.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs))
    np.save(root / "vectors.npy", values, allow_pickle=False)
    manifest = {"created": datetime.now(timezone.utc).isoformat(), "revision": embedder.MODEL_REVISION,
        "documents": len(docs), "constructor_passages": len(constructor), "sql_fiches": len(rows),
        "files": {p.name: digest(p) for p in [root / "documents.jsonl", root / "vectors.npy"]},
        "sources": [{**s, "snapshot": str((snapshots / (s["id"] + ".html")).resolve()), "sha256": digest(snapshots / (s["id"] + ".html")), "sql_bindings": bindings[s["id"]]} for s in sources],
        "constructor_encoding_seconds": encoding_seconds, "preparation_seconds": time.perf_counter() - started}
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: manifest[k] for k in ["documents", "constructor_passages", "sql_fiches", "constructor_encoding_seconds", "preparation_seconds"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.out, args.snapshots)

#!/usr/bin/env python3
"""Isolated SQL and offline BGE-M3 index of a frozen technical-data POC.

Neither the collector's SQLite database nor the production catalog is opened.
Source passages remain verbatim; identity and model-year filtering happens in
SQL before dense retrieval. All unknown markets remain unknown.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data/technical/hybrid-poc"
DEFAULT_DB = DEFAULT_OUT / "index.sqlite3"
VECTOR_DIM = 1024
STATUSES = {"standard", "optional", "explicitly_absent", "unknown"}


def _read_json(value: Path | str | dict) -> dict:
    if isinstance(value, dict):
        return value
    return json.loads(Path(value).read_text())


def _connect(db_path: Path | str, *, readonly: bool = True) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) if readonly else sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if readonly:
        conn.execute("PRAGMA query_only=ON")
    return conn


def build_index(dataset: Path | str | dict, db_path: Path | str = DEFAULT_DB) -> dict:
    """Replace this POC's SQL tables using only a frozen JSON dataset.

    The raw record, duplicate specification labels, and verbatim passages are
    retained. Equipment decisions are deliberately empty until separately
    supplied; a raw mention never silently becomes a standard-equipment fact.
    """
    data = _read_json(dataset)
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    source_digest = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    with closing(_connect(path, readonly=False)) as conn, conn:
        conn.executescript("""
            DROP TABLE IF EXISTS equipment_decisions;
            DROP TABLE IF EXISTS specifications;
            DROP TABLE IF EXISTS passages;
            DROP TABLE IF EXISTS records;
            DROP TABLE IF EXISTS metadata;
            CREATE TABLE records (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, brand TEXT, model TEXT,
                year INTEGER, market TEXT, source_url TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );
            CREATE INDEX identity_scope ON records(year, brand, model);
            CREATE TABLE specifications (
                object_id TEXT NOT NULL REFERENCES records(id), ordinal INTEGER,
                section TEXT, label TEXT, value TEXT,
                PRIMARY KEY(object_id, ordinal)
            );
            CREATE TABLE passages (
                id TEXT PRIMARY KEY, object_id TEXT NOT NULL REFERENCES records(id),
                section TEXT NOT NULL, text TEXT NOT NULL, source_url TEXT NOT NULL,
                vector_idx INTEGER UNIQUE
            );
            CREATE INDEX passage_scope ON passages(object_id);
            CREATE TABLE equipment_decisions (
                object_id TEXT NOT NULL REFERENCES records(id), equipment TEXT NOT NULL,
                provider TEXT NOT NULL, status TEXT NOT NULL
                  CHECK(status IN ('standard','optional','explicitly_absent','unknown')),
                market TEXT, confidence REAL, evidence_json TEXT, case_id TEXT,
                PRIMARY KEY(object_id, equipment, provider)
            );
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        for record in data["records"]:
            identity = record.get("identity", {})
            conn.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?)", (
                record["id"], record.get("name") or identity.get("raw_name", ""),
                record.get("brand", identity.get("brand")), record.get("model", identity.get("model")),
                record.get("year", identity.get("year")), identity.get("market"),
                record.get("source_url") or record["url"], json.dumps(record, ensure_ascii=False)))
            conn.executemany("INSERT INTO specifications VALUES(?,?,?,?,?)", (
                (record["id"], i, row.get("section", ""), row.get("label", ""), row.get("value", ""))
                for i, row in enumerate(record.get("spec_rows", []))))
        conn.executemany("INSERT INTO passages VALUES(?,?,?,?,?,NULL)", (
            (p["id"], p["object_id"], p["section"], p["text"], p["source_url"])
            for p in data["passages"] if p.get("text", "").strip()))
        conn.executemany("INSERT INTO metadata VALUES(?,?)", [
            ("dataset_sha256", source_digest), ("dataset_created_at", data.get("created_at", "")),
            ("schema_version", "hybrid-retrieval-poc-v1")])
        counts = {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                  for name in ["records", "passages", "specifications"]}
    return counts | {"database": str(path.resolve()), "dataset_sha256": source_digest}


def ingest_decisions(rows: Iterable[dict], db_path: Path | str = DEFAULT_DB, *, provider: str | None = None) -> int:
    """Ingest externally evaluated decisions without loading any model.

    Required keys: object_id, equipment, provider (or keyword), status. A nested
    prediction={status,market} is accepted for benchmark outputs. Errors are not
    converted into facts, and duplicate decisions for one provider must agree.
    """
    prepared = {}
    for row in rows:
        if row.get("error") or row.get("error_type"):
            continue
        prediction = row.get("prediction", row)
        status = prediction.get("status")
        if status not in STATUSES:
            raise ValueError(f"Invalid equipment status: {status!r}")
        source = provider or row.get("provider")
        if not source:
            raise ValueError("A decision provider is required")
        key = (row["object_id"], row["equipment"], source)
        market = prediction.get("market")
        market = None if market in (None, "unknown", "") else market
        value = (status, market)
        if key in prepared and prepared[key][0] != value:
            raise ValueError(f"Conflicting decisions for {key}")
        prepared[key] = (value, row)
    with closing(_connect(db_path, readonly=False)) as conn, conn:
        for key, ((status, market), row) in prepared.items():
            conn.execute("""INSERT INTO equipment_decisions VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(object_id,equipment,provider) DO UPDATE SET
                    status=excluded.status, market=excluded.market,
                    confidence=excluded.confidence, evidence_json=excluded.evidence_json,
                    case_id=excluded.case_id""", (*key, status, market, row.get("confidence"),
                    json.dumps(row.get("evidence", row.get("passages", [])), ensure_ascii=False),
                    row.get("case_id", row.get("id"))))
    return len(prepared)


def _scope(filters: dict[str, Any], *, equipment: bool = True) -> tuple[str, list]:
    conditions, args = [], []
    known = {"year", "brand", "model", "name", "market", "object_ids", "equipment", "status", "provider"}
    unknown = set(filters) - known
    if unknown:
        raise ValueError(f"Unsupported filters: {sorted(unknown)}")
    for field in ["year", "brand", "model", "name"]:
        if filters.get(field) is not None:
            conditions.append(f"r.{field} = ?")
            args.append(filters[field])
    if "market" in filters:
        if filters["market"] in (None, "unknown"):
            conditions.append("r.market IS NULL")
        else:
            conditions.append("r.market = ?")
            args.append(filters["market"])
    if filters.get("object_ids") is not None:
        ids = filters["object_ids"]
        if not ids:
            conditions.append("0")
        else:
            conditions.append(f"r.id IN ({','.join('?' for _ in ids)})")
            args.extend(ids)
    if filters.get("status") is not None and not filters.get("equipment"):
        raise ValueError("A status filter needs a named equipment")
    if equipment and filters.get("equipment"):
        if not filters.get("provider"):
            raise ValueError("Equipment queries need an explicit decision provider")
        decision = ["d.object_id = r.id", "d.equipment = ?", "d.provider = ?"]
        args.extend([filters["equipment"], filters["provider"]])
        if filters.get("status") is not None:
            if filters["status"] not in STATUSES:
                raise ValueError("Invalid equipment status filter")
            decision.append("d.status = ?")
            args.append(filters["status"])
        conditions.append("EXISTS (SELECT 1 FROM equipment_decisions d WHERE " + " AND ".join(decision) + ")")
    return (" AND ".join(conditions) or "1"), args


def sql_filter(*, db_path: Path | str = DEFAULT_DB, limit: int | None = None, offset: int = 0, **filters) -> list[dict]:
    """Complete structured filtering; limit=None returns all matching objects.

    Equipment availability is never inferred from vector similarity. Callers
    must choose the evaluated decision provider and exact status they require.
    """
    if offset < 0 or (limit is not None and limit < 0):
        raise ValueError("Invalid SQL pagination")
    where, args = _scope(filters)
    query = "SELECT r.id,r.name,r.brand,r.model,r.year,r.market,r.source_url FROM records r WHERE " + where + " ORDER BY r.year,r.brand,r.name,r.id"
    if limit is not None or offset:
        query += " LIMIT ? OFFSET ?"
        args.extend([-1 if limit is None else limit, offset])
    with closing(_connect(db_path)) as conn:
        result = [dict(row) for row in conn.execute(query, args)]
        if filters.get("equipment"):
            for row in result:
                decision = conn.execute("SELECT status,market,confidence FROM equipment_decisions WHERE object_id=? AND equipment=? AND provider=?",
                    (row["id"], filters["equipment"], filters["provider"])).fetchone()
                row["equipment"] = filters["equipment"]
                row["equipment_status"] = decision["status"]
                row["equipment_market"] = decision["market"]
    return result


@lru_cache(maxsize=1)
def _bge_model():
    """Load only the already installed local snapshot, on CPU, with four threads."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    cache = Path(os.getenv("HF_HUB_CACHE", str(Path.home() / ".cache/huggingface/hub"))) / "models--BAAI--bge-m3"
    revision = (cache / "refs/main").read_text().strip()
    snapshot = cache / "snapshots" / revision
    if not snapshot.is_dir():
        raise FileNotFoundError("BGE-M3 local snapshot is unavailable; downloads are disabled")
    model = SentenceTransformer(str(snapshot), device="cpu", local_files_only=True)
    model.max_seq_length = 512
    return model


def _encode(texts: list[str]):
    return _bge_model().encode(texts, batch_size=24, normalize_embeddings=True,
                               show_progress_bar=False, convert_to_numpy=True)


def save_vectors(passage_ids: list[str], vectors, db_path: Path | str = DEFAULT_DB) -> dict:
    """Persist a normalized 1024-dimensional matrix with exact passage mapping."""
    import numpy as np
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.shape != (len(passage_ids), VECTOR_DIM):
        raise ValueError("Expected one 1024-dimensional vector per passage")
    if not np.isfinite(matrix).all() or len(set(passage_ids)) != len(passage_ids):
        raise ValueError("Invalid or duplicate passage vectors")
    norm = np.linalg.norm(matrix, axis=1, keepdims=True)
    if (norm == 0).any():
        raise ValueError("Zero embedding vector")
    matrix = matrix / norm
    path = Path(db_path).with_suffix(".vectors.npy")
    with closing(_connect(db_path, readonly=False)) as conn:
        existing = {row[0] for row in conn.execute("SELECT id FROM passages")}
        if not set(passage_ids) <= existing:
            raise ValueError("Embedding references an unknown source passage")
        # Write the matrix first; mapping transaction is committed afterwards.
        temporary = path.with_suffix(".tmp.npy")
        np.save(temporary, matrix, allow_pickle=False)
        temporary.replace(path)
        with conn:
            conn.execute("UPDATE passages SET vector_idx=NULL")
            conn.executemany("UPDATE passages SET vector_idx=? WHERE id=?", enumerate(passage_ids))
            conn.execute("INSERT OR REPLACE INTO metadata VALUES(?,?)", ("vectors_path", str(path.resolve())))
    return {"embedded_passages": len(passage_ids), "dimensions": VECTOR_DIM, "vectors_path": str(path.resolve())}


def embed_passages(db_path: Path | str = DEFAULT_DB, *, object_ids: list[str] | None = None, max_passages: int | None = None) -> dict:
    """Embed original technical sections, optionally a documented subset.

    Passages are not relabelled or translated. Numeric specs and price sections
    stay exactly as collected. Each batch is limited to 24 CPU encodings.
    """
    filters = {} if object_ids is None else {"object_ids": object_ids}
    where, args = _scope(filters)
    query = "SELECT p.id,p.text FROM passages p JOIN records r ON r.id=p.object_id WHERE " + where + " ORDER BY p.id"
    if max_passages is not None:
        query += " LIMIT ?"
        args.append(max_passages)
    with closing(_connect(db_path)) as conn:
        rows = list(conn.execute(query, args))
        source_digest = conn.execute("SELECT value FROM metadata WHERE key='dataset_sha256'").fetchone()[0]
    if not rows:
        raise ValueError("No passages selected for embedding")
    started = time.perf_counter()
    import numpy as np
    # Duplicate text is encoded once; source IDs are never deduplicated. The
    # dense matrix maps every original passage to that text's embedding.
    unique_texts = list(dict.fromkeys(row["text"] for row in rows))
    text_index = {text: i for i, text in enumerate(unique_texts)}
    model = _bge_model()
    token_lengths = model.tokenizer(unique_texts, truncation=False, return_length=True)["length"]
    vectors = []
    for start in range(0, len(unique_texts), 24):
        batch = unique_texts[start:start + 24]
        vectors.append(_encode(batch))
        print(json.dumps({"stage": "bge_embeddings", "completed_unique_texts": start + len(batch),
                          "total_unique_texts": len(unique_texts), "original_passages": len(rows)}, ensure_ascii=False), flush=True)
    unique_vectors = np.concatenate(vectors)
    matrix = unique_vectors[[text_index[row["text"]] for row in rows]]
    stats = save_vectors([row["id"] for row in rows], matrix, db_path)
    stats.update(model="BAAI/bge-m3", model_snapshot=Path(model[0].auto_model.config._name_or_path).name,
                 device="cpu", max_seq_length=512, threads=4, normalize_embeddings=True, dtype="float32",
                 batch_size=24, dataset_sha256=source_digest,
                 seconds=round(time.perf_counter() - started, 3), unique_texts=len(unique_texts),
                 tokens_max=int(max(token_lengths)), truncated_unique_texts=sum(length > 512 for length in token_lengths),
                 selection={"object_ids": object_ids, "max_passages": max_passages})
    Path(db_path).with_suffix(".embeddings.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n")
    return stats


def retrieve(question: str, filters: dict | None = None, topk: int = 5, *, db_path: Path | str = DEFAULT_DB, query_vector=None) -> list[dict]:
    """Retrieve within SQL scope BEFORE cosine ranking; never relax filters.

    An empty or unembedded scope returns no result, not a nearby model/year.
    query_vector permits deterministic integration checks without loading BGE.
    Dense top-k is evidence retrieval, never an exhaustive list of motorcycles.
    """
    if topk < 1:
        raise ValueError("topk must be positive")
    where, args = _scope(filters or {})
    with closing(_connect(db_path)) as conn:
        rows = [dict(row) for row in conn.execute("""SELECT p.id,p.object_id,p.section,p.text,p.source_url,p.vector_idx,
                    r.name,r.brand,r.model,r.year,r.market FROM passages p
                    JOIN records r ON r.id=p.object_id WHERE p.vector_idx IS NOT NULL AND """ + where, args)]
    if not rows:
        return []
    import numpy as np
    vector = np.asarray(_encode([question])[0] if query_vector is None else query_vector, dtype=np.float32)
    if vector.shape != (VECTOR_DIM,) or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
        raise ValueError("Invalid query embedding")
    vector /= np.linalg.norm(vector)
    matrix = np.load(Path(db_path).with_suffix(".vectors.npy"), mmap_mode="r", allow_pickle=False)
    scores = matrix[[r["vector_idx"] for r in rows]] @ vector
    order = np.argsort(-scores, kind="stable")[:topk]
    return [({key: value for key, value in rows[index].items() if key != "vector_idx"}
             | {"score": round(float(scores[index]), 6)}) for index in order]


def evaluate_retrieval(dataset: Path | str | dict, db_path: Path | str = DEFAULT_DB, *, count: int = 60) -> dict:
    """Compare scoped and unscoped BGE on real original source passages.

    Gold relevance is the original section containing a requested factual
    specification, not a model-generated answer. This assesses finding the
    correct evidence and model-year, not the truth of a manufacturer's claim.
    """
    data = _read_json(dataset)
    records = {row["id"]: row for row in data["records"]}
    queries = []
    rng = random.Random(20261010)
    categories = [
        ("seat_height", "Châssis", "hauteur de selle", "Quelle est la hauteur de selle"),
        ("power", "Moteur", "ch", "Quelle est la puissance du moteur"),
        ("fork", "Train avant", "fourche", "Quel type de fourche et quel débattement avant"),
        ("rear_brake", "Train arrière", "freinage", "Quels sont les freins arrière"),
        ("transmission", "Transmission", "", "Quelle est la transmission et combien de rapports"),
        ("abs", "Équipement de série", "abs", "Que dit la fiche sur l'ABS, de série ou en option"),
    ]
    per_category = max(1, count // len(categories))
    for category, section, needle, question in categories:
        candidates = [p for p in data["passages"] if p["section"] == section and needle in p["text"].lower()]
        rng.shuffle(candidates)
        selected = candidates[:per_category]
        for passage in selected:
            record = records[passage["object_id"]]
            filters = {key: record[key] for key in ["brand", "model", "year"]}
            relevant_objects = {r["id"] for r in records.values() if all(r[key] == value for key, value in filters.items())}
            gold_ids = [p["id"] for p in data["passages"] if p["object_id"] in relevant_objects and p["section"] == section]
            queries.append({"id": f"retrieval-{len(queries)+1:03d}", "category": category,
                            "question": f"{question} pour {record['name']} ?", "filters": filters,
                            "object_id": record["id"], "gold_passage_ids": gold_ids,
                            "gold_text": passage["text"], "source_url": passage["source_url"]})
    if not queries:
        raise ValueError("No original source queries available")
    started = time.perf_counter()
    query_vectors = _encode([query["question"] for query in queries])
    rows = []
    for query, vector in zip(queries, query_vectors):
        row = dict(query)
        for scope, filters in [("scoped", query["filters"]), ("unscoped", {})]:
            before = time.perf_counter()
            found = retrieve(query["question"], filters, 3, db_path=db_path, query_vector=vector)
            row[scope] = {
                "hits": found,
                "recall_at_1": bool(found and found[0]["id"] in query["gold_passage_ids"]),
                "recall_at_3": any(hit["id"] in query["gold_passage_ids"] for hit in found),
                "identity_at_1": bool(found and all(found[0][key] == value for key, value in query["filters"].items())),
                "seconds": round(time.perf_counter() - before, 4),
            }
        rows.append(row)
    summary = {scope: {metric: sum(row[scope][metric] for row in rows) / len(rows)
                       for metric in ["recall_at_1", "recall_at_3", "identity_at_1"]}
               for scope in ["scoped", "unscoped"]}
    report = {"queries": len(rows), "method": "source_section_gold_model_year_scope_v1",
              "semantic_task": "Retrieve the original specification section for an exact motorcycle model-year",
              "seconds_including_query_embeddings": round(time.perf_counter() - started, 3),
              "summary": summary, "results": rows}
    Path(db_path).with_suffix(".retrieval-evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return {key: value for key, value in report.items() if key != "results"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--dataset", type=Path, default=DEFAULT_OUT / "dataset.json")
    embedding = commands.add_parser("embed")
    embedding.add_argument("--max-passages", type=int)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--dataset", type=Path, default=DEFAULT_OUT / "dataset.json")
    evaluate.add_argument("--count", type=int, default=60)
    query = commands.add_parser("query")
    query.add_argument("question")
    query.add_argument("--year", type=int)
    query.add_argument("--brand")
    query.add_argument("--model")
    query.add_argument("--topk", type=int, default=5)
    args = parser.parse_args()
    if args.command == "build":
        result = build_index(args.dataset, args.db)
    elif args.command == "embed":
        result = embed_passages(args.db, max_passages=args.max_passages)
    elif args.command == "evaluate":
        result = evaluate_retrieval(args.dataset, args.db, count=args.count)
    else:
        filters = {k: getattr(args, k) for k in ["year", "brand", "model"] if getattr(args, k) is not None}
        result = retrieve(args.question, filters, args.topk, db_path=args.db)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Small, read-only run manifests and generation-aware answer caches.

Collecting a manifest does not load an embedding model or run a generator.
It reads the local database and, for Ollama generation, its installed-model
list. The corpus checksum includes stored vectors and enrichment rows: equal
row counts alone are not a sufficient identity for cached tool contexts.
Retrieval model names/configuration and library versions are recorded, but
the Hugging Face model weight files are not hashed or revision-pinned here.
"""

import hashlib
import json
import os
import platform
import subprocess
import tempfile
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CACHE_VERSION = 1
GENERATION_PACKAGES = ("requests", "anthropic", "psycopg", "pgvector",
                       "sentence-transformers", "transformers", "torch")
CORPUS_TABLES = ("motorcycles", "model_families", "review_chunks", "recalls",
                 "used_price_estimates")


def fingerprint(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def git_state(root: Path = ROOT) -> dict:
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    try:
        return {"sha": git("rev-parse", "HEAD"),
                "dirty": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.CalledProcessError):
        return {"sha": None, "dirty": None}


def corpus_snapshot(conn) -> dict:
    """Hash rows in ID order, including vectors, without exporting their text.

    Each row is hashed before aggregation to bound aggregate memory. This
    scans the corpus once; it is deliberately stronger than counts/timestamps
    and is intended for occasional local POC evaluations, not each chat turn.
    """
    snapshot = {}
    with conn.cursor() as cur:
        # Fixed table names from the schema; no user input enters this SQL.
        for table in CORPUS_TABLES:
            cur.execute(f"""
                SELECT count(*), max(id),
                       md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY id), ''))
                FROM {table} t
            """)
            count, max_id, checksum = cur.fetchone()
            snapshot[table] = {"rows": count, "max_id": max_id,
                               "rows_md5": checksum}
        cur.execute("SELECT lang, source, count(*) FROM review_chunks GROUP BY lang, source ORDER BY lang, source")
        snapshot["review_languages"] = [
            {"lang": lang, "source": source, "rows": count}
            for lang, source, count in cur.fetchall()
        ]
        cur.execute("SELECT current_setting('server_version'), extversion FROM pg_extension WHERE extname = 'vector'")
        postgres, pgvector = cur.fetchone()
        snapshot["database_versions"] = {"postgres": postgres, "pgvector": pgvector}
    return snapshot


def ollama_model_identity(model: str, host: str) -> dict:
    """Resolve a mutable Ollama tag to its installed digest; no model load."""
    import requests

    try:
        response = requests.get(f"{host.rstrip('/')}/api/tags", timeout=10)
        response.raise_for_status()
        models = response.json()["models"]
        wanted = model if ":" in model.rsplit("/", 1)[-1] else f"{model}:latest"
        for entry in models:
            if entry.get("name") in (model, wanted) or entry.get("model") in (model, wanted):
                if entry.get("digest"):
                    return {"model": entry.get("name") or entry["model"],
                            "requested_model": model, "digest": entry["digest"]}
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Cannot identify the installed Ollama model; check OLLAMA_HOST and model availability.") from exc
    raise RuntimeError(f"Ollama model {model!r} has no installed digest; install it before evaluating.")


def collect_provenance(conn, *, generation: bool = False) -> dict:
    from bikefinder_rag.embeddings import embedder, reranker

    packages = {}
    for package in (*GENERATION_PACKAGES, "ragas", "langchain-ollama"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    sources = ("agent/tools.py", "embeddings/embedder.py", "embeddings/reranker.py")
    if generation:
        sources += ("agent/loop.py",)
    source_hashes = {
        name: hashlib.sha256((ROOT / "src/bikefinder_rag" / name).read_bytes()).hexdigest()
        for name in sources
    }
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "git": git_state(),
        "python": platform.python_version(),
        "package_versions": packages,
        "implementation_sha256": source_hashes,
        "corpus": corpus_snapshot(conn),
        "retrieval": {
            "embedder_model": embedder.MODEL_NAME,
            "embedding_dimensions": embedder.EMBEDDING_DIM,
            "device": os.environ.get("EMBEDDER_DEVICE") or "auto",
            "reranker_model": reranker.MODEL_NAME,
            "reranker_enabled": reranker.enabled(),
            "weight_revision_tracking": "model names and packages; HF weight files are not hashed or pinned",
        },
    }
    if generation:
        from bikefinder_rag.agent import loop
        from bikefinder_rag.agent.tools import TOOLS

        model = {"anthropic": loop.MODEL, "ollama": loop.OLLAMA_MODEL,
                 "openrouter": loop.OPENROUTER_MODEL}[loop.BACKEND]
        identity = {"model": model}
        if loop.BACKEND == "ollama":
            identity = ollama_model_identity(model, loop.OLLAMA_HOST)
        manifest["generation"] = {
            "backend": loop.BACKEND, **identity,
            "system_prompt_sha256": fingerprint(loop.SYSTEM_PROMPT),
            "tool_schema_sha256": fingerprint(TOOLS),
            "max_tool_turns": loop.MAX_TOOL_TURNS,
        }
        if loop.BACKEND == "ollama":
            manifest["generation"]["options"] = {"temperature": 0, "num_ctx": 16384}
    return manifest


def generation_identity(manifest: dict) -> dict:
    """Keep the judge/run date/Git docs changes out of answer-cache identity."""
    return {key: manifest[key] for key in
            ("generation", "corpus", "retrieval", "implementation_sha256", "python")} | {
        "package_versions": {name: manifest["package_versions"].get(name)
                             for name in GENERATION_PACKAGES}
    }


class CacheMismatchError(ValueError):
    pass


def load_answers_cache(path: Path, identity: dict, *, regenerate: bool = False) -> list[dict]:
    if regenerate or not path.exists():
        return []
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise CacheMismatchError("Unreadable answer cache; use --regenerate.") from exc
    if not isinstance(cache, dict) or cache.get("cache_version") != CACHE_VERSION:
        raise CacheMismatchError("Legacy/unversioned answer cache; use --regenerate.")
    if cache.get("generation_fingerprint") != fingerprint(identity) or cache.get("generation_identity") != identity:
        raise CacheMismatchError("Answer cache belongs to a different generator, prompt, tools or corpus; use --regenerate.")
    rows = cache.get("rows")
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("question"), str)
        or not isinstance(row.get("answer"), str) or not isinstance(row.get("contexts"), list)
        or not isinstance(row.get("generated_at_utc"), str)
        or any(not isinstance(context, str) for context in row.get("contexts", []))
        for row in rows
    ):
        raise CacheMismatchError("Invalid answer-cache rows; use --regenerate.")
    if len({row["question"] for row in rows}) != len(rows):
        raise CacheMismatchError("Duplicate questions in answer cache; use --regenerate.")
    return rows


def save_answers_cache(path: Path, identity: dict, rows: list[dict]) -> None:
    payload = json.dumps({"cache_version": CACHE_VERSION,
                          "generation_identity": identity,
                          "generation_fingerprint": fingerprint(identity),
                          "rows": rows}, indent=2, ensure_ascii=False)
    # Replace in the same directory: interruption cannot truncate the previous
    # usable cache after hours of local generation.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", suffix=".tmp", delete=False) as file:
        temporary = Path(file.name)
        file.write(payload)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def dated_report_path(directory: Path, prefix: str, created_at_utc: str) -> Path:
    """Keep historical/current JSON artifacts intact on subsequent runs."""
    timestamp = datetime.fromisoformat(created_at_utc).astimezone(timezone.utc)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{prefix}_{timestamp.strftime('%Y%m%dT%H%M%S.%fZ')}.json"

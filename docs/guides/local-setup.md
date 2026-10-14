# Local setup

Run commands from the repository root. The supported project direction is
local PostgreSQL, BGE-M3 and Ollama, with Jev as the only authorized remote
service. Source collection and initial model downloads are preparation steps;
they do not imply another remote inference provider.

## Install and configure

Prerequisites: Python 3.11+, Docker Compose and Ollama. The target machine is
a Mac M5 with 32 GB of unified memory. Model files are not peak runtime memory.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
test -f .env || cp .env.example .env
```

In `.env`, configure the database and this runtime:

```dotenv
AGENT_BACKEND=ollama
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=mistral-small3.2
BIKEFINDER_JEV_ROUTER=1
BIKEFINDER_JEV_RAG=1
BIKEFINDER_CATALOG_FAST_PATH=0
JEV_ROUTER_TIMEOUT_SECONDS=5
CATALOG_SYNTHESIS_TIMEOUT_SECONDS=30
```

Set `OPENROUTER_API_KEY` locally for Jev. Do not put it in chat, commands that
print configuration, source control or a browser-visible file. The interface
uses the server key; visitors do not need one. Legacy remote-generator settings
are retained for historical code compatibility, outside this workflow.

Start Ollama if it is not already running, then prepare the reference model
and database:

```bash
ollama pull mistral-small3.2
docker compose up -d --wait postgres
```

Compose persists PostgreSQL in a named volume and exposes it only on localhost.
Its initialization SQL runs once for a new volume. The idempotent legacy schema
can be applied to an existing Compose database with:

```bash
docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < src/bikefinder_rag/db/schema.sql
```

## Load the enriched technical catalog

The full SQLite source snapshot is not distributed in Git. Use a locally
prepared export from the documented collection/enrichment process. A Git clone
alone does not recreate the 11,478-sheet demo.

If the catalog is already imported, skip this step. For the retained snapshot:

```bash
PYTHONPATH=src .venv/bin/python scripts/load_enriched_catalog.py \
  --source data/technical/enrichment-full-20261012/pass2/catalogue.enriched.sqlite3
```

The loader imports the frozen export and rebuilds its numeric projection. It
changes the database, so this is a setup operation, not a benchmark prerequisite
to repeat on the active catalog. See [catalog integration](../enriched-catalog-chat.md)
and [collection](../technical-data-collection.md).

## Start the chat

```bash
AGENT_BACKEND=ollama BIKEFINDER_JEV_ROUTER=1 PYTHONPATH=src \
  .venv/bin/python src/bikefinder_rag/app.py
```

Open `http://127.0.0.1:7860`. The CLI is also available through
`PYTHONPATH=src .venv/bin/python scripts/chat_cli.py` with the same `.env`.
Starting or restarting the interface is separate from editing files; preserve
an existing interactive session until a restart is intended.

Jev selects a validated plan; source facts can be returned directly. The
synthesis path uses one bounded local Mistral request and a Jev claim check.
An unavailable Jev decision produces a clarification. It does not silently
activate another remote generator.

## Local model preparation

With `BIKEFINDER_JEV_RAG=1`, accepted readings of exact sheets use BGE-M3.
The standalone SQL + RAG benchmark also uses it, separately from the chat. Prepare the embedder
and local reranker once before their first offline run:

```bash
PYTHONPATH=src .venv/bin/python -c 'from bikefinder_rag.embeddings.embedder import embed_text; from bikefinder_rag.embeddings.reranker import rerank; embed_text("motorcycle"); rerank("motorcycle", ["owner review"])'
```

After installation, `HF_HUB_OFFLINE=1` avoids Hugging Face metadata/download
requests while loading those cached models. Jev itself still requires Internet.
The reranker is optional in the historical review pipeline, controlled by
`RERANKER_ENABLED`; it is not currently part of technical retrieval.

## Retained local prototype

With `BIKEFINDER_JEV_ROUTER=0`, the legacy Ollama tool loop remains available.
The bundled `data/pilot` can initialize that older path using
`PYTHONPATH=src .venv/bin/python scripts/load_db.py data/pilot`. It loads a
different catalog and embeds owner comments; it is not the enriched demo above.

That loop uses a cooperative per-turn budget and request timeouts. In-flight
database/CPU work is not interrupted, so the budget is not a hard wall-clock
deadline. Its old full imports and enrichment commands remain in the
[archived notes](../history/project-notes-2026-10-13.md#running-it-locally).

[Documentation index](../README.md) · [Architecture](../reference/architecture.md)

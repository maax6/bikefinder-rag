# Bikefinder RAG

A source-based motorcycle catalog prototype for finding, filtering, counting
and comparing technical characteristics by **brand, model, model year and
variant**. Built and evaluated locally on a Mac M5 with 32 GB of unified memory.

## Interactive benchmark

**[Open the SQL + RAG model benchmark](https://maax6.github.io/bikefinder-rag/benchmark.html)**

The public report compares eight remote models in two recorded passes on the
same local catalog and the same eight cases (nine user turns per model).
Explore answers, judgments, tool calls, latency, API costs and evaluation limits.
It runs directly in your browser, without an account or installation.

The passes contain **26 → 34 entirely correct cases out of 64** per pass.
GPT-6 Luna reaches 7/8 entirely correct cases in pass 2; this small, reviewed
pilot does not establish a general winner. Tools and context settings changed
between passes, so the gains cannot be attributed to the model alone.
The [protocol and comparison report](docs/sql-rag-tools-and-comparison.md)
explains the distinction between case results and per-turn quality scores.

## Current state — 2026-10-14

The loaded Motoplanète snapshot contains **11,478 real sheets and 105,687
technical passages**. These are source records, not a complete inventory of
all motorcycles. The source snapshot, indexes and model caches stay local.

Two paths coexist:

- **Existing local chat:** Jev selects bounded operations; local SQL serves
  facts, filters, counts and calculations. With `BIKEFINDER_JEV_RAG=1`, exact
  sheet readings can use local BGE-M3 retrieval and bounded Mistral writing,
  with source and claim checks. Experimental family research is separate.
- **New standalone SQL + RAG service:** six provider-independent tools resolve
  identities, query and compare sheets, and retrieve technical passages.
  A bounded model session uses these tools and submits cited answers. It is
  evaluated separately and **is not yet connected to the Gradio chat**.

The six tools are `describe_catalog`, `resolve_models`, `query_catalog`,
`get_fiches`, `compare_fiches` and `search_passages`. SQL/Python performs the
counts and calculations; BM25 and local BGE-M3 retrieve passages. Equipment
keeps its standard/optional/explicitly absent/unknown status, original units,
model-year identity and source evidence.

After pass 2, local corrections reject unknown scope IDs, fix family matching,
expose usable citation evidence and preserve list identities under the context
budget. [Recorded regression and service checks](docs/sql-rag-remaining-failures-20261014.md)
validate these mechanisms. **No third model pass has been run:** the historical
scores remain unchanged and improved final answers are not yet demonstrated.

The existing chat uses Jev via OpenRouter as its only remote inference service.
The separate, explicitly authorized model comparison used other remote models
through OpenRouter; it does not switch the chat backend. Questions and selected
source excerpts are transmitted when remote inference is used.

## Limits and next work

The prototype does not establish current used prices, rider comfort, reliability
or legal homologation of an individual motorcycle. An A2 source mention is
not a certificate; an unknown equipment field does not mean the equipment is absent.
A fresh clone does not include the full technical dataset.

Local generation experiments have not demonstrated a generally useful assistant
within ten seconds. The remote pilot still contains incorrect answers, provider
rate limits, timeouts and citation/schema failures. Regression tests check
mechanisms; they are not a general accuracy score.

[Issue #4](https://github.com/maax6/bikefinder-rag/issues/4) tracks the current
state and remaining work: evaluate the corrected service on new questions,
choose a runtime from measured results, and connect the common service to the
chat. Earlier [catalog refactor #2](https://github.com/maax6/bikefinder-rag/issues/2)
and [retrieval benchmark #3](https://github.com/maax6/bikefinder-rag/issues/3)
retain their results and closure notes.

## Run locally

Requires Python 3.11+, Docker Compose, Ollama and an imported enriched catalog.
Prepare the snapshot and server-side Jev key using the
[setup guide](docs/guides/local-setup.md). Then start the existing chat:

```bash
AGENT_BACKEND=ollama BIKEFINDER_JEV_ROUTER=1 BIKEFINDER_JEV_RAG=1 PYTHONPATH=src \
  .venv/bin/python src/bikefinder_rag/app.py
```

Open `http://127.0.0.1:7860`. Visitors do not enter a key. The standalone
comparison has its own [commands and protocol](docs/sql-rag-tools-and-comparison.md);
it is not launched by this chat command. See the [script index](scripts/README.md).

## Validation

Publication check on 2026-10-14: **1,181 tests passed, 8 integration tests skipped**.
Keep personal runtime settings out of the regression run:

```bash
BIKEFINDER_JEV_ROUTER=0 BIKEFINDER_JEV_RAG=0 \
BIKEFINDER_CATALOG_RESEARCH=0 BIKEFINDER_CATALOG_EXPERIMENT=0 \
  .venv/bin/python -m pytest -q
```

The post-pass-2 service receipt covers all forty reference cases and verifies
an index of 105,687 passages. Its regression replay makes no new cloud calls
and does not regenerate model answers.

## Earlier demo and retrieval benchmark

[![Bikefinder: technical comparisons, equipment and autonomy](docs/brag/brag-20261013.jpg)](docs/brag/brag-20261013.mp4)

[Watch the 43-second demo](docs/brag/brag-20261013.mp4). This edited capture of
an earlier chat shortens waits; it is not a demo of the standalone service or
a latency benchmark. [Capture evidence](docs/brag/README.md).

The [local retrieval benchmark](docs/technical-retrieval-benchmark-20261013.md)
compared BM25, BGE-M3, hybrid retrieval and reranking on fifty reserved questions.
It measured retrieval, separately from generation and the later remote pilot.
See the [existing chat architecture](docs/reference/architecture.md),
[evaluation guide](docs/guides/evaluation.md) and
[archived notes](docs/history/project-notes-2026-10-13.md).

## Repository map

| Location | Purpose |
|---|---|
| [`src/bikefinder_rag/`](src/bikefinder_rag/) | Chat, catalog, common service, collection and evaluation |
| [`scripts/`](scripts/README.md) | Preparation, checks, experiments and retained legacy commands |
| [`tests/`](tests/) | Behavioral regressions and source fixtures |
| [`docs/`](docs/README.md) | Guides, reports and GitHub Pages benchmark |
| [`eval_results/`](eval_results/README.md) | Recorded protocols, results and replays |
| [`data/`](data/) | Retained datasets and ignored local snapshots/caches |
| [`deploy/`](deploy/README.md) | Historical hosting experiments |

## Code and data

The code is [MIT-licensed](LICENSE). Third-party datasets retain their own
source terms; the code license does not grant dataset redistribution rights.
See the [source and collection record](docs/technical-data-collection.md).

# Bikefinder RAG

An agentic RAG chatbot over motorcycle specs and owner reviews — a from-scratch-data,
prod-stack learning project (and portfolio piece). Ask it things like *"a light naked
bike under 600cc, and what do owners say about reliability?"* in French or English.

## Why this exists

A first RAG project meant to actually learn the mechanics (local embeddings,
hand-written pgvector similarity SQL, an explicit tool-use loop) rather than
wrap a framework. Full context and every decision trail (including the ones
that got reversed) is in the [project's Notion doc] — the short version:

- **Corpus**: self-scraped from [bikez.com](https://bikez.com) (specs + owner
  discussion forums), not a pre-packaged Kaggle dump — see [Data source](#data-source--why-self-scrape).
  Currently **9,702 motorcycles (1894–2024), 1,657 model families, 82,589
  embedded owner comments** — the full last century plus the 2024 lineup of
  the major street brands, datasets shipped in `data/`.
- **Category filter**: `Scooter` is excluded *unless* displacement ≥ 500cc
  (keeps crossovers like the Honda X-ADV or Yamaha TMAX, drops twist-and-go
  commuters), `ATV` is always excluded, everything else — including
  `Minibike` and oddball `Prototype/concept model` entries — is kept.
- **No pre-curated "top N" popular models list.** Every scraped page's forum
  is checked; a motorcycle only gets a narrative/review layer if it has ≥3
  substantive comments. The narrative subset emerges from what actually has
  discussion, not from a guessed popularity ranking.
- **Agentic RAG, raw Anthropic SDK** — no LangChain/LlamaIndex. Two tools:
  `filter_specs` (typed parameters only, parameterized SQL, the LLM never
  writes SQL) and `search_reviews` (pgvector cosine search with optional
  fuzzy/`ILIKE` metadata filters).
- **PostgreSQL + pgvector**, one database for both structured specs and
  review embeddings.
- **Comments belong to model families, not model-years.** bikez.com shares
  one discussion forum across every year and variant of a model (the same
  threads back the CB 250 K 1 1970 and the CB 250 N 1985), so comments are
  stored once per family (`model_families`), deduplicated, and every
  retrieval result carries the family's year range plus the comment's own
  post date — the agent is instructed never to attribute a comment to one
  specific model-year.
- **Local, multilingual embeddings** (`BAAI/bge-m3`) — no embeddings API key
  needed, and queries in French retrieve English-language forum comments.
- **Evaluation**: two layers, both with published results.
  [`scripts/eval_retrieval.py`](scripts/eval_retrieval.py) proves the
  retrieval layer alone, no LLM involved (self-retrieval 30/30, theme lifts
  21-82x over corpus base rate, negative controls rejected — see
  [`eval_results/retrieval/`](eval_results/retrieval/)).
  [RAGAS](https://github.com/explodinggpt/ragas)
  (faithfulness, answer relevancy) then scores the full agent over a golden
  question set — generation by mistral-small (local), and the same answers
  graded by **two independent judges**: qwen3.6 (local) gives
  **0.61 / 0.76**, Haiku via `claude -p` gives **0.71 / 0.77**
  ([`eval_results/ragas/`](eval_results/ragas/)). The judges
  converge per-question: structured-filter questions 0.9-1.0 for both,
  and both give 0.0 to the same answer where the *local generator*
  contradicts its own tool results (answering "no owner reviews" while
  real comments sit in its context) — a confirmed generation defect, not
  judge noise. Both also flag the honesty checks' correct "no data on
  record" answers, RAGAS's known penalty on refusals. An earlier pass
  caught two real retrieval bugs (substring-only model matching, dropped
  `query` arguments) whose fixes lifted narratives from 0.0 to 1.0.
  Same harness, Claude backend as *generator*: pending an API key.
- **Interface**: Gradio, deployable on Hugging Face Spaces for free — visitors
  paste their own Anthropic API key (used only for their session, never
  stored server-side).

## Data source & why self-scrape

There's an existing Kaggle dataset (`all_bikez`, CC0) scraped from bikez.com
in 2022. We scrape ourselves instead: it keeps specs *and* forum comments on
one unified pipeline, it's current rather than frozen at 2022, and it directly
extends [github.com/maax6/Bikefinder](https://github.com/maax6/Bikefinder),
which this project grew out of.

`robots.txt` on bikez.com disallows specific interactive endpoints (rating,
review submission, spec-update forms) for all crawlers, not the spec or
discussion pages themselves — a sitemap is published for exactly this kind
of discovery. The scraper (`src/bikefinder_rag/scraper/`) respects that,
identifies itself with a real User-Agent, and enforces a fixed delay between
every request (`SCRAPER_DELAY_SECONDS`, default 1.5s).

## ⚠️ Known limitation: price data

**bikez.com has no price field at all** (verified against both the 2022
Kaggle dataset's validation report and a live fetch of a well-documented,
recent model — 0% coverage either way). Price was judged important enough
to the project's original intent (this started life as "Bikefinder" — find
a motorcycle to *buy*) to be worth a second source, but the obvious French
marketplaces block that outright:

| Site | Result |
|---|---|
| Leboncoin | `robots.txt`: *"forbidden to use search robots... access only with special permission"* |
| La Centrale | DataDome anti-bot (CAPTCHA-gated) |
| ParuVendu | `robots.txt` disallows exactly the `/auto-moto/*` paths |
| **Motoplanete** | ✅ **viable** (verified 2026-07-12): `robots.txt` allows the spec pages and publishes a moto sitemap (~12k pages); CGU has no database-extraction clause (non-commercial use only); fiches carry French MSRP ("Tarifs France"), full specs *and* explicit A2-version info. Hard constraint: `Crawl-delay: 10` → targeted enrichment of our existing models, not a catalog clone. |

We don't scrape against an explicit prohibition or bypass anti-bot protection.
**Current state: `msrp_eur` is a placeholder column, populated from a
to-be-determined legitimate source (partner API, a permissive smaller
marketplace, or an existing dataset).** Until then, expect `filter_specs`
price queries to mostly return "no price data," which the agent is
instructed to say plainly rather than imply the bike is unaffordable or
doesn't exist. Real market pricing is the first item on the roadmap below.

## Architecture

```
Gradio UI (visitor's own Anthropic key)
        │
        ▼
Agent loop (raw Anthropic SDK, tool-use)
        │
        ├── filter_specs ──► PostgreSQL (typed columns, parameterized SQL)
        │
        └── search_reviews ─► PostgreSQL + pgvector (BGE-M3 embeddings,
                               optional ILIKE metadata pre-filter)
```

## Project layout

```
src/bikefinder_rag/
  scraper/        list_scraper.py, detail_scraper.py, categories.py, http.py
  db/             schema.sql, client.py
  embeddings/     embedder.py (BGE-M3)
  agent/          tools.py, loop.py
  eval/           golden_questions.json, run_ragas.py
  app.py          Gradio interface
scripts/
  run_pilot_scrape.py   stratified sample (categories x decades x brands)
  load_db.py            loads scraped JSONL into Postgres, embeds comments
```

## Running it locally

```bash
python3.11 -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env   # AGENT_BACKEND=ollama for the free local path

docker run -d --name bikefinder-pg \
  -e POSTGRES_USER=bikefinder -e POSTGRES_PASSWORD=bikefinder -e POSTGRES_DB=bikefinder \
  -p 5432:5432 \
  -v "$(pwd)/src/bikefinder_rag/db/schema.sql:/docker-entrypoint-initdb.d/schema.sql" \
  pgvector/pgvector:pg17

# The scraped datasets ship with the repo (data/pilot, data/demo,
# data/century — 1894-2024). Load them (deduplicates + embeds, GPU-hours
# at century scale):
PYTHONPATH=src .venv/bin/python scripts/load_db.py data/pilot
PYTHONPATH=src .venv/bin/python scripts/load_db.py data/demo
PYTHONPATH=src .venv/bin/python scripts/load_db.py data/century

# Re-scrape / extend (resumable at bike, thread and forum level):
PYTHONPATH=src .venv/bin/python scripts/run_demo_scrape.py \
    --years 2000-2023 --brands all --out data/2000s

# Chat (Gradio, or scripts/chat_cli.py for the terminal):
PYTHONPATH=src .venv/bin/python src/bikefinder_rag/app.py
```

## Evaluating

```bash
# Layer 1 — retrieval alone, no LLM (writes eval_results/retrieval/retrieval_report.json):
PYTHONPATH=src .venv/bin/python scripts/eval_retrieval.py

# Layer 2 — RAGAS over the full agent. Generation model via OLLAMA_MODEL;
# judge via RAGAS_JUDGE_MODEL: an Ollama model name (local), or
# "claude-cli[:model]" to judge through `claude -p` on a Claude
# subscription (no API key). Answers are cached per question and resume
# after an interrupt; --regenerate forces fresh ones.
OLLAMA_MODEL=qwen3.6 RAGAS_JUDGE_MODEL=claude-cli:haiku \
  EMBEDDER_DEVICE=cpu AGENT_BACKEND=ollama \
  PYTHONPATH=src .venv/bin/python -m bikefinder_rag.eval.run_ragas

# Data-coverage dashboard (self-contained HTML, spot what to fill next):
PYTHONPATH=src .venv/bin/python scripts/coverage_dashboard.py
```

## Roadmap

1. Price + missing-field enrichment from **motoplanete.com** (verified
   scrapable, see the price table above): match our models against its moto
   sitemap, fetch `Tarifs France` into `msrp_eur`/`msrp_source`, and pick up
   A2-version info (35 kW bridage) along the way — feeds a future "permis A2"
   filter. 10s crawl-delay → enrichment of our own catalog only.
2. Scale scraping beyond the 2024 demo year (the demo scrape covers the
   full 2024 lineup of 16 major street brands; family-level forums mean the
   narrative layer already reaches back years)
3. RAGAS `context_precision`/`context_recall` (needs a hand-curated
   ground-truth set, deferred — faithfulness/answer_relevancy don't need one)
4. Hugging Face Spaces deployment

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
- **Agentic RAG, raw Anthropic SDK** — no LangChain/LlamaIndex. Three tools:
  `filter_specs` (typed parameters only, parameterized SQL, the LLM never
  writes SQL — plus a `count_only` mode for "how many" questions),
  `search_reviews` (pgvector cosine search with optional fuzzy/`ILIKE`
  metadata filters) and `get_bike_details` (one bike's full factory spec
  sheet, `raw_specs` included).
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
- **Evaluation**: four layers, all with published results.
  [`scripts/eval_retrieval.py`](scripts/eval_retrieval.py) proves the
  retrieval layer alone, no LLM involved (self-retrieval 30/30, theme lifts
  21-82x over corpus base rate, negative controls rejected — see
  [`eval_results/retrieval/`](eval_results/retrieval/)).
  [`scripts/eval_tool_trajectory.py`](scripts/eval_tool_trajectory.py)
  scores how a model calls the tools — deterministic predicates over the
  recorded calls, no LLM judge; its findings drove the few-shot prompt,
  the Ollama options and the visible argument repair, taking mistral-small
  from 9/12 to 15/15 golden questions
  ([`eval_results/trajectory/`](eval_results/trajectory/)).
  [`scripts/eval_constraints.py`](scripts/eval_constraints.py) then checks
  the final answers themselves: every motorcycle named in a reply is
  resolved against the database and verified against the question's hard
  constraints — **0.0% violation rate** over 41 verified mentions
  ([`eval_results/constraints/`](eval_results/constraints/)).
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

We don't scrape against an explicit prohibition or bypass anti-bot protection
(Le Repaire des Motards was probed for French owner reviews and serves an
active human-check page to automated clients — dropped, whatever its
robots.txt says).

**Current state: the motoplanete crawl is done and loaded** —
`scripts/scrape_motoplanete_prices.py` collected 11,418 fiches (93% with a
French launch price, 100% with a curated category), and
`scripts/load_motoplanete_prices.py` matched 9,390 of them (82%) onto our
motorcycles: **7,137 bikes now carry a French MSRP** in `msrp_eur` (22% of
the catalog, 25-29% of each decade since 1990) and
7,356 a clean `category_fr` (Roadster, Sportive, Trail, Supermotard...) —
used as a cross-check against bikez's loose categories, which mislabel
e.g. recent Transalps as 'Super motard'. Coverage is still partial, and
the agent is instructed to say "no price data" plainly rather than imply a
bike is unaffordable or doesn't exist.

Two more data layers ride along (loaded by their own idempotent scripts):

- **US safety recalls** (`scripts/load_nhtsa_recalls.py`): NHTSA's free
  flat files, 3,521 campaign rows matched onto 431 model families — the
  project's only *objective* reliability signal, surfaced by
  `get_bike_details` with an explicit "US market only" caveat.
- **Indicative used prices** (`scripts/load_used_prices.py`): median and
  quartiles per (family, registration year) aggregated from a 2022
  European marketplace snapshot (Kaggle, ~22k matched listings, 626
  families) — a dated cote indicative, presented as such, never as
  today's market value.

## Architecture

```
Gradio UI (visitor's own Anthropic key)
        │
        ▼
Agent loop (raw Anthropic SDK, tool-use)
        │
        ├── filter_specs ────► PostgreSQL (typed columns, parameterized SQL)
        │
        ├── search_reviews ──► PostgreSQL + pgvector (BGE-M3 embeddings,
        │                       optional ILIKE metadata pre-filter)
        │
        └── get_bike_details ► PostgreSQL (one bike's full spec sheet +
                                the family's NHTSA recalls and used-price
                                estimate)
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
  run_pilot_scrape.py            stratified sample (categories x decades x brands)
  load_db.py                     loads scraped JSONL into Postgres, embeds comments
  scrape_motoplanete_prices.py   French prices + categories (11.4k fiches)
  load_motoplanete_prices.py     matches fiches onto motorcycles (msrp_eur, category_fr)
  load_nhtsa_recalls.py          US safety recalls onto model families
  load_used_prices.py            2022 used-price aggregates onto model families
  eval_retrieval.py              layer-1 eval (retrieval alone, no LLM)
  eval_tool_trajectory.py        layer-1.5 eval (tool calls, no LLM judge)
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
# data/century — 1894-1999 + the 2024 lineup, data/2000s — 2000-2023).
# Load them (deduplicates + embeds, GPU-hours at full scale):
PYTHONPATH=src .venv/bin/python scripts/load_db.py data/pilot
PYTHONPATH=src .venv/bin/python scripts/load_db.py data/demo
PYTHONPATH=src .venv/bin/python scripts/load_db.py data/century
PYTHONPATH=src .venv/bin/python scripts/load_db.py data/2000s

# Enrichment layers (idempotent, in any order after load_db):
PYTHONPATH=src .venv/bin/python scripts/load_motoplanete_prices.py  # French MSRP + category_fr
PYTHONPATH=src .venv/bin/python scripts/load_nhtsa_recalls.py       # US safety recalls
PYTHONPATH=src .venv/bin/python scripts/load_used_prices.py         # 2022 used-price cote

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

# Layer 1.5 — tool-call trajectories, deterministic checks, no LLM judge
# (one model per run; writes eval_results/trajectory/trajectory_<model>.json):
AGENT_BACKEND=ollama OLLAMA_MODEL=mistral-small3.2 EMBEDDER_DEVICE=cpu \
  PYTHONPATH=src .venv/bin/python scripts/eval_tool_trajectory.py

# Layer 1.75 — hard-constraint violation rate of the final answers
# (writes eval_results/constraints/constraints_<model>.json):
AGENT_BACKEND=ollama OLLAMA_MODEL=mistral-small3.2 EMBEDDER_DEVICE=cpu \
  PYTHONPATH=src .venv/bin/python scripts/eval_constraints.py

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

1. ~~Price enrichment from motoplanete.com~~ **done** (7,137 bikes priced,
   plus `category_fr`); A2-version info (35 kW bridage) from the same fiches
   remains to harvest — feeds a future "permis A2" filter.
2. ~~Scale scraping beyond the 2024 demo year~~ **done** (century +
   2000-2023 crawls: 32,395 bikes, 107,952 embedded comments)
3. ~~Better entity resolution across sources~~ **done**
   (`src/bikefinder_rag/matching.py`): one token-level matcher shared by
   the enrichment loaders; the used-price cote now reaches families
   through concrete model-year rows instead of family names.
4. RAGAS `context_precision`/`context_recall` (needs a hand-curated
   ground-truth set, deferred — faithfulness/answer_relevancy don't need one)
5. ~~Cross-lingual retrieval hardening~~ **partially done**:
   `search_reviews` now reranks its dense top-50 with `bge-reranker-v2-m3`
   (+57% on-topic results in French queries' top-10, see
   [`eval_results/retrieval/`](eval_results/retrieval/)). Dense recall
   remains the bound — hybrid dense+sparse is the remaining lever.
6. ~~Hugging Face Spaces deployment~~ **shipped as a static showcase**:
   [huggingface.co/spaces/masonpaint/bikefinder-rag](https://huggingface.co/spaces/masonpaint/bikefinder-rag)
   (proof documents, eval results, a real captured session). The full
   Docker Space (Postgres + agent in one container, `deploy/`) is built
   and verified locally under linux/amd64 — hosting it live needs an HF
   PRO plan since the 2026 free-tier change, so it ships as
   run-it-yourself instead.

# Evaluation and retrieval benchmarks

Run commands from the repository root. Jev is the only authorized remote
service. Embeddings, reranking, generation and any model-based judging run
locally; source-grounded references determine relevance.

## Reserved retrieval benchmark

Compare four methods over one frozen technical catalog:

1. Keywords, with an explicit lexical ranking method.
2. Dense BGE-M3 retrieval.
3. Lexical/dense fusion.
4. The same hybrid candidates followed by local reranking.

Prepare ten development questions and fifty independently authored reserved
questions before looking at method outputs. Annotate expected source passages
and missing evidence, rather than writing answers to memorize. Separate a
provided exact identity from a global search and from the real chat route.

Report relevance, query encoding/search/reranking times, process startup,
index preparation, memory and caches separately. Preserve the first independent
pass; after changes, its replay becomes a regression run. A2 cases first test
source mentions; official A2 documents and legal compatibility are not silently
assumed to exist in the current corpus.

The [comparative harness](../../scripts/benchmark_technical_retrieval.py) ran
[issue #3](https://github.com/maax6/bikefinder-rag/issues/3) on 13 October 2026.
See the [report and recommendation](../technical-retrieval-benchmark-20261013.md)
and [reproduction commands](../../eval_results/technical/retrieval-benchmark-20261013/README.md).
Its reserved questions now form a regression set. A new independent test is
required after adaptations. The historical review evaluator measures a separate corpus.

## Regression checks

```bash
.venv/bin/python -m pytest -q
```

Most checks use local fixtures and simulated transports. Some PostgreSQL tests
are opt-in; test counts are not retrieval or chatbot quality scores. Follow the
test's integration requirements before setting `RUN_CATALOG_INTEGRATION=1`.

## Current technical tools

| Command | Purpose and requirements |
|---|---|
| `scripts/eval_technical_demo.py` | Sequential probes through an already running Gradio API; inspect answers against sources |
| `scripts/evaluate_jev_routing.py` | Controlled routing suite; real Jev calls may cost money, caches must be identified |
| `scripts/evaluate_free_chat.py` | Natural questions and dialogues, with first passes distinct from adapted replays |
| `scripts/audit_technical_normalization.py` | Bounded read-only audit of migration candidates |
| `scripts/audit_collected_technical_data.py` | Offline field/year coverage of the retained collection |

See [scripts by role](../../scripts/README.md) for complete command inventory,
and [dated results](../../eval_results/README.md) before quoting a measurement.

## Generated coverage dashboard

```bash
PYTHONPATH=src .venv/bin/python scripts/coverage_dashboard.py
```

This reads the historical database tables and writes
`eval_results/coverage/coverage_dashboard.html`, ignored by Git. It measures
coverage of that loaded corpus, not correctness or completeness of all
Motoplanète technical evidence. The previously generated HTML was relocated
without regenerating its data.

## Historical evaluation layers

The retained review/agent experiments are separate from the upcoming technical
comparison:

- `scripts/eval_retrieval.py`: review retrieval diagnostics, including
  self-retrieval and keyword proxies; no generator.
- `scripts/eval_tool_trajectory.py`: observed local model tool calls.
- `scripts/eval_constraints.py`: final-answer hard constraints.
- `bikefinder_rag.eval.run_ragas`: model-judged answer evaluation, with a local
  judge for current authorized work.

These commands can load models or query the database. Do not run them while
another person is testing the same local inference server. Old remote judge
results remain historical evidence and do not authorize a new remote service.

## Reading a result

A useful report identifies the source snapshot, question partition, code state,
model revision, actual index/configuration, measurement scope and cache state.
Self-retrieval validates plumbing; evidence relevance needs new questions and
source annotations. Source availability, retrieval quality, synthesis quality
and useful partial answers are separate outcomes.

[Documentation index](../README.md) · [Current architecture](../reference/architecture.md)

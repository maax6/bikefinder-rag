# Partial answers, new questions and refreshed demo — 2026-10-13

The chat now returns more of the facts already present in the catalog without
calling Mistral. This revision preserves source wording, model years, variants
and unknown values. It also refreshes the Gradio interface and the README demo.

## What improved

- Read reservoirs, dimensions, tyres, colours and engine rows directly.
- Convert explicitly requested, unambiguous source units: metric ch/CV to kW,
  mkg to Nm, torque to lb·ft, litres to US gallons, millimetres to inches,
  kilograms to pounds and displacement to cubic inches. Original units, regime,
  qualifications, exact factors and rounding remain visible. Filters still
  require supported units; conversions do not modify the source catalog.
- Keep available facts when one comparison fiche is missing. Display ambiguous
  generations separately, and qualify candidate variants rather than silently
  substituting them. A fiche tariff is not automatically a launch price.
- Retain model/year context in natural follow-ups, including anaphoric conversion
  requests. Model codes such as `CRF1100L` are not interpreted as litre bounds.
- Use closed, validated compound count plans over source rows for supported
  criteria. The complete matching lists are downloadable CSVs with original
  evidence, source URLs and source hashes; the chat displays twenty preview rows.
- Read explicit ABS source evidence when an older derived classification says
  unknown. Presence, standard fitment, options, absence and conflicts stay distinct.
- Supplement missing ground-clearance and cruise-control details from retained
  Bikez rows only when brand, full model/variant and year match exactly. The Z750
  2004's 165 mm ground clearance and RS660 2021's explicit “ACC (cruise control)”
  are separately cited; primary Motoplanète gaps remain visible. Market and
  standard/optional status are not inferred. No cross-source overwrite occurs.

Jev still selects bounded operations and characteristics. It does not write SQL
or supply technical values. Code validates constraints; local data produces the
answer. Mistral remains reserved for explanations and reasoning beyond reading,
comparing or calculating documented facts.

## Quality: first passes and adapted replays

Independent agents checked actual API answers against retained raw records.
Transport success and agreement with a direct router call are not quality scores.

| Set | First review | Final adapted review |
|---|---|---|
| 24 previously partial turns | 24 source-limited answers | 5 useful improvements, including 2 resolved requests; 2 complete and 22 honest source limitations |
| 50 independently authored new turns | 8 correct, 16 honest limits, 21 incomplete, 5 incorrect | 25 correct, 25 honest limits, no incomplete or incorrect answer observed |
| 20 additional unseen turns | 10 complete, 3 useful partial, 7 failures | 20 complete under that review rubric, no observed invented technical value |

The 50-turn author did not see code or previous suites; the implementing agent
saw the first five formulations during setup, so this is not a fully blind test.
The implementing agent did not see the 20-turn formulations until their first
valid API pass completed. The question-file schema was reformatted before any
successful API call. All final replays are adapted after failures, and therefore
are **not a general accuracy estimate**. The 20-turn rubric accepts a complete
treatment of the question with explicitly stated source-scoped unknowns; it does
not mean every requested value exists in the corpus.

The reviews caught wrong-brand aliases, lost follow-ups, omitted conversions,
incomplete lists and a wrong compound count. They also caught a temporary
regression where “série” or “France” was mistaken for a model name. Those cases
were corrected and retested; earlier reports remain preserved locally.

Three complete source-derived lists contain **250, 324 and 409 fiches**. An
independent review checked their **983 rows and 3,360 individual field proofs**
against raw records. The 250 count includes the Horex Regina Evo 2023's adjustable
790–810 mm seat: its entire interval satisfies the requested 820 mm ceiling.
Manual/shifter annotations do not erase an otherwise explicit six-speed gearbox.

## Observed performance and checks

| Real Gradio API run | Median | P95 | Maximum |
|---|---:|---:|---:|
| First 50 new turns | 0.378 s | 0.482 s | 0.576 s |
| First 20 unseen turns | 0.419 s | 0.769 s | 2.564 s |
| Final adapted 50-turn replay | 0.062 s | 0.217 s | 0.560 s |
| Final adapted 20-turn replay | 0.064 s | 0.161 s | 2.401 s |

The runs use sequential API turns on an isolated test server. API-first timing
excludes the subsequent router inspection. Replays reuse many classification
cache entries; their medians should not be read as uncached latency guarantees.
All 124 final API turns across the old 54 and new 50+20 agree with their direct
router inspection. **None requires Mistral in these factual suites.**

The existing controlled acceptance suite still passes **480/480**: 440 direct
factual answers, 30 clarifications and 10 cases routed to bounded synthesis.
This regression run does not execute ten Mistral generations. The local workspace
passes **922 tests**, with 8 skipped, including pre-existing collection tests.
CSV downloads return the full 250/324/409 rows through the real Gradio file route.

Observed new Jev cache receipts total **$0.13773 for 853 decisions** in this task,
including regression runs. Each new receipt is counted once relative to the
initial cache snapshot. This is an observed usage sum, not an account balance or
an EUR conversion. The user's available budget did not need to be exhausted.

## Remaining data boundaries

Missing equipment mention remains unknown rather than absent. The technical
snapshots do not establish rider comfort, owner reliability, current prices,
France homologation, model launch dates or guaranteed real-world range.

Ordinary trail/roadster/touring/sport category filters remain blocked. The old
Bikez taxonomy contains contradictory labels and is not silently treated as a
universal riding category. An explicitly requested Bikez category can use a
qualified, non-exhaustive subset with strict source identity matching. Electric
propulsion requires explicit source evidence; hybrids and electric starters do
not prove an electric-only motorcycle.

## Interface and demo

The refreshed interface provides a wider chat, more readable comparison tables,
mobile layouts, contextual examples and a new-conversation action that clears
both visible messages and the hidden routing context. CSS and theme are applied
at launch as required by Gradio 6. The endpoint remains `/chat`.

The [updated 43-second demo](brag/brag-20261013.mp4) uses real captures of the
refreshed frontend and four actual API answers. It preserves the “calculated but
unverified” range qualification. It is silent, uses shortened waits and is
explicitly labelled as an edited demonstration, not a latency measurement.
See [capture evidence and reproduction](brag/README.md).

The [aggregate result artifact](../eval_results/technical/partial_chat_improvements_20261013.json)
contains timing, review summaries, source and code hashes, and CSV validation.
Collector code and source datasets were left untouched. These changes are local
workspace work and have not been committed or pushed by this task.

The final implementation is active on the local chat at `127.0.0.1:7860`. A fresh
interface tab was opened and a live UI question verified the separate 165 mm
Bikez ground-clearance evidence. The two added source complements were independently
reviewed; the other 18 answers in that lot are unchanged. The earlier demo captures
remain labelled as captures from their recorded version, rather than a benchmark
of the final source-supplement changes.

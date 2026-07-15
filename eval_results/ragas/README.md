# Couche 2 — RAGAS sur l'agent complet

**Contexte et méthode : [De la page web au score RAGAS — le pipeline
Bikefinder](https://maax6.github.io/bikefinder-rag/pipeline-et-evaluation.html)**
(voir aussi [la méthode sans
framework](https://maax6.github.io/bikefinder-rag/methode-sans-langchain.html)).

Là où [`../retrieval/`](../retrieval/) prouve la couche recherche seule,
RAGAS note ici le système de bout en bout : l'agent (génération locale via
Ollama) répond au golden set
(`src/bikefinder_rag/eval/golden_questions.json`), puis un juge LLM score
chaque réponse en **faithfulness** (la réponse s'appuie-t-elle sur le
contexte récupéré ?) et **answer relevancy** (répond-elle à la question ?).

## Résultats

| Fichier | Génération | Juge | Questions | Faithfulness | Answer relevancy |
|---|---|---|---|---|---|
| [`ragas_results.json`](ragas_results.json) (15 juil. 2026, corpus complet + outils enrichis) | mistral-small3.2 | Claude Haiku (via `claude -p`) | 17 | **0.76** | **0.87** |
| [`ragas_results_haiku-judge.json`](ragas_results_haiku-judge.json) (12 juil.) | mistral-small | Claude Haiku (via `claude -p`) | 12 | 0.71 | 0.77 |
| [`ragas_results_qwen-judge.json`](ragas_results_qwen-judge.json) (12 juil.) | mistral-small | qwen3.6 (local) | 12 | 0.61 | 0.76 |

Le run du 15 juillet intègre tout ce qui a changé entre-temps : le passage
à mistral-small3.2 avec durcissement du tool calling (voir
[`../trajectory/`](../trajectory/)), le corpus 107 952 commentaires, le
troisième outil `get_bike_details`, les prix français, les rappels NHTSA et
la cote occasion — 5 questions golden de plus pour couvrir ces capacités.
Un timeout du juge sur 1 des 34 scorings (exclu de la moyenne).

Par question, les nouvelles capacités scorent au plafond (`details-1`
1.0/1.0, `recall-1` 1.0/0.95) ; les scores bas restent les biais RAGAS
connus plutôt que des défauts du système : pénalité sur les réponses
« pas de données » pourtant correctes (honesty-1/2), faithfulness à 0 sur
une réponse d'un seul chiffre pourtant lue dans le contexte (count-1), et
answer relevancy à 0 sur une réponse en français (narrative-3).

Sur le run du 12 juillet, les mêmes réponses avaient été notées par **deux
juges indépendants** — convergence par question, donc le signal venait des
réponses, pas du juge.

Les juges convergent par question : 0.9–1.0 pour les deux sur les questions
à filtre structuré, et les deux donnent 0.0 à la même réponse — celle où le
*générateur local* contredit ses propres résultats d'outil (il répond
« aucun avis de propriétaire » alors que de vrais commentaires sont dans son
contexte). Défaut de génération confirmé, pas de retrieval : c'est
exactement la séparation des couches que cette éval à deux étages permet.

## Reproduire

```bash
OLLAMA_MODEL=mistral-small3.2 RAGAS_JUDGE_MODEL=claude-cli:haiku \
  EMBEDDER_DEVICE=cpu AGENT_BACKEND=ollama \
  PYTHONPATH=src .venv/bin/python -m bikefinder_rag.eval.run_ragas --regenerate
```

Écrit `eval_results/ragas/ragas_results.json`. Les réponses sont mises en
cache par question et reprennent après une interruption ; `--regenerate`
force des réponses fraîches.

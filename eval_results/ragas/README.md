# Couche 2 — RAGAS sur l'agent complet

**Contexte et méthode : [De la page web au score RAGAS — le pipeline
Bikefinder](https://maax6.github.io/bikefinder-rag/pipeline-et-evaluation.html)**
(voir aussi [la méthode sans
framework](https://maax6.github.io/bikefinder-rag/methode-sans-langchain.html)).

Là où [`../retrieval/`](../retrieval/) prouve la couche recherche seule,
RAGAS note ici le système de bout en bout : l'agent (génération locale
**mistral-small** via Ollama) répond aux 12 questions du golden set
(`src/bikefinder_rag/eval/golden_questions.json`), puis un juge LLM score
chaque réponse en **faithfulness** (la réponse s'appuie-t-elle sur le
contexte récupéré ?) et **answer relevancy** (répond-elle à la question ?).

## Résultats

Les mêmes réponses générées sont notées par **deux juges indépendants** —
si les deux convergent, le signal vient des réponses, pas du juge :

| Fichier | Juge | Faithfulness | Answer relevancy |
|---|---|---|---|
| [`ragas_results_haiku-judge.json`](ragas_results_haiku-judge.json) | Claude Haiku (via `claude -p`) | **0.71** | **0.77** |
| [`ragas_results_qwen-judge.json`](ragas_results_qwen-judge.json) | qwen3.6 (local) | **0.61** | **0.76** |

[`ragas_results.json`](ragas_results.json) est le dernier run (juge Haiku) ;
[`generated_answers_mistral-small.json`](generated_answers_mistral-small.json)
contient les réponses générées qui ont été jugées.

Les juges convergent par question : 0.9–1.0 pour les deux sur les questions
à filtre structuré, et les deux donnent 0.0 à la même réponse — celle où le
*générateur local* contredit ses propres résultats d'outil (il répond
« aucun avis de propriétaire » alors que de vrais commentaires sont dans son
contexte). Défaut de génération confirmé, pas de retrieval : c'est
exactement la séparation des couches que cette éval à deux étages permet.

## Reproduire

```bash
OLLAMA_MODEL=qwen3.6 RAGAS_JUDGE_MODEL=claude-cli:haiku \
  EMBEDDER_DEVICE=cpu AGENT_BACKEND=ollama \
  PYTHONPATH=src .venv/bin/python -m bikefinder_rag.eval.run_ragas
```

Écrit `eval_results/ragas/ragas_results.json`. Les réponses sont mises en
cache par question et reprennent après une interruption ; `--regenerate`
force des réponses fraîches.

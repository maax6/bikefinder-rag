# Couche 1,5 — trajectoire des tool calls (sans juge LLM)

`scripts/eval_tool_trajectory.py` note **comment** un modèle appelle les
outils, indépendamment de la qualité de sa rédaction. RAGAS (couche 2) juge
la réponse finale ; cette éval juge la trajectoire qui l'a produite : le bon
outil est-il choisi pour chaque golden question, avec des arguments sensés,
sans appel halluciné ni dépassement de la limite de tours ?

Chaque check est un **prédicat déterministe** sur les appels enregistrés —
aucun juge LLM, donc un échec ici est sans ambiguïté. Elle complète
`eval_retrieval.py` (couche 1, retrieval seul) : un modèle qui échoue à
RAGAS mais passe ici rédige mal à partir de bonnes données ; un modèle qui
échoue ici n'a jamais donné sa chance au retrieval.

## Ce que ça a permis d'améliorer (14 juillet 2026)

Le premier run avec `mistral-small` (Ollama, local) a donné **9/12 questions,
30/33 checks**, avec trois échecs — tous des erreurs d'*arguments*, jamais de
sélection d'outil :

| Question | Échec observé |
|---|---|
| `struct-5` (années 1950, en français) | `max_year=1959` posé mais `min_year` oublié — la décennie n'était bornée que par le haut |
| `hybrid-1` (fiabilité d'une naked débutant) | argument halluciné `model_family`, `query` obligatoire omis — le thème « fiabilité » n'atteignait jamais la recherche vectorielle |
| `honesty-1` (moins chère sous 3000 €) | tri par prix sans le filtre `max_msrp_eur` — la contrainte budget n'était pas appliquée |

Corrections apportées (commit associé), toutes côté harnais/prompt, sans
toucher au modèle :

1. **Options Ollama** : `temperature: 0` (les arguments d'outils ne doivent
   pas être échantillonnés avec du bruit) et `num_ctx: 16384` (le défaut
   d'Ollama est petit et il tronque *silencieusement* — les instructions
   tombaient du contexte en milieu de boucle).
2. **Exemples few-shot dans le system prompt** : six paires question → appel
   JSON exact, ciblées sur les échecs observés (décennie = les deux bornes,
   dont un exemple en français ; budget → `max_msrp_eur` ; fiabilité →
   `query` explicite).
3. **Descriptions de paramètres enrichies** dans les schémas d'outils
   (`min_year`/`max_year` expliquent la règle des décennies, `query` est
   marqué REQUIRED avec un exemple).
4. **Réparation d'arguments visible** : les noms d'arguments quasi-synonymes
   (`model_family`, `models`, `bike`…) sont remappés au lieu d'être jetés en
   silence, et chaque réparation est annoncée dans le tool result
   (`notes: [...]`) pour que le modèle puisse se corriger au tour suivant.
5. **Un troisième outil, `get_bike_details`** : la fiche technique complète
   d'une moto (capacité du réservoir, refroidissement, transmission,
   pneus…) — ces données étaient en base (`raw_specs`) mais inatteignables
   par l'interface. Et un mode `count_only` sur `filter_specs` pour les
   questions « combien de… ».

Trois golden questions ont été ajoutées en même temps (`details-1`,
`details-2` en français, `count-1`) pour vérifier que le nouvel outil est
correctement routé et ne cannibalise pas la sélection des deux autres.

## Résultats

| Modèle | Questions | Checks | Notes |
|---|---|---|---|
| `mistral-small` (avant corrections, 12 questions) | 9/12 | 30/33 | 3 échecs d'arguments, 0 échec de sélection |
| `mistral-small` (après corrections, 15 questions) | 15/15 | 40/40 | trajectoires parfaites ; une fuite `[TOOL_CALLS]` dans le *texte* final de hybrid-1 (problème de rédaction → couche RAGAS) |
| `mistral-small3.2` (15 questions) | 15/15 | 40/40 | texte final propre ; sur hybrid-1 il trie même par `weight_kg` parce que la question demandait une moto *légère* |
| `mistral-small3.2` (17 questions, outils enrichis rappels + cote) | 16/17 | 43/44 | `recall-1` et `cote-1` routées parfaitement vers `get_bike_details` ; hybrid-1 a re-omis le `query` fiabilité ce run-ci (sa faiblesse récurrente — la réparation d'arguments visible rattrape l'appel, le check reste strict) |
| [`mistral-small3.2`](trajectory_mistral-small3.2.json) (18 questions, + filtre permis A2) | **18/18** | **46/46** | `a2-1` route directement vers `filter_specs(a2_only=true)` ; hybrid-1 repasse ce run-ci |

Sur `hybrid-1`, la trajectoire après corrections est notablement meilleure
que le minimum demandé : le modèle filtre 5 naked ≤ 600 cm³ puis interroge
les avis de **chacune** des candidates avec `query="reliability problems
breakdowns"`.

## Reproduire

```bash
AGENT_BACKEND=ollama OLLAMA_MODEL=mistral-small EMBEDDER_DEVICE=cpu \
  PYTHONPATH=src .venv/bin/python scripts/eval_tool_trajectory.py
```

Un run = un modèle ; le rapport est écrit dans
`eval_results/trajectory/trajectory_<modèle>.json` (écrasé à chaque run du
même modèle ; l'historique est porté par git).

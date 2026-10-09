# Couche 1,75 — taux de violation de contraintes (sans juge LLM)

`scripts/eval_constraints.py` mesure ce qu'un utilisateur subit vraiment :
**une moto nommée dans la réponse finale viole-t-elle les contraintes dures
de la question ?** Une recommandation bien rédigée qui dépasse le budget ou
la fourchette de cylindrée est un échec, quoi qu'en pense RAGAS de sa prose.

C'est la réponse mesurée à la critique classique des systèmes RAG (« les
contraintes dures doivent rester dures ») : ici l'architecture les impose
par SQL paramétré (`filter_specs`), et cette éval vérifie le résultat en
sortie, de bout en bout.

Méthode, entièrement déterministe :
1. poser à l'agent des questions porteuses de contraintes (cylindrée,
   poids, hauteur de selle, décennie, budget — en anglais et en français,
   dont deux formulations hors golden set) ;
2. extraire les motos mentionnées dans la réponse (spans en gras, lignes
   de liste) ;
3. les résoudre contre la table `motorcycles` (tokens normalisés, année
   respectée quand la réponse en donne une) ;
4. vérifier chaque contrainte sur les lignes résolues.

Trois issues par mention : satisfaite, **violée**, invérifiable (mention
non résolue ou données insuffisantes). Depuis octobre 2026, une contrainte
numérique sans valeur en base ne peut plus être classée satisfaite. Une
violation connue reste une violation, même si une autre donnée manque.

## Résultats (15 juillet 2026, mistral-small3.2, corpus complet)

Fichier brut : [`constraints_mistral-small3.2.json`](constraints_mistral-small3.2.json)

| Métrique | Valeur |
|---|---|
| Questions | 8 (5 EN, 3 FR) |
| Mentions résolues (checker historique) | 41 |
| **Violations de contraintes** | **0 → taux 0,0 %** |
| Invérifiables | 13 (24 %) |

Ce taux est un résultat historique du checker précédent. Celui-ci ignorait
les champs numériques absents : « 41 mentions vérifiées » signifiait alors
41 mentions résolues, sans garantir que toutes leurs contraintes étaient
vérifiables. Les anciens scores sont conservés, pas recalculés.

Les 13 « invérifiables » de ce run ne sont pas des modèles inventés : ce
sont des sous-lignes de specs (« Seat Height: 780 mm… ») que l'extracteur
de mentions prenait pour des noms — l'artefact est corrigé dans le script
depuis ce run. Aucune violation n'a été détectée sur les champs renseignés
des motos résolues ; les données manquantes limitaient cette vérification.

Un run précédent avait affiché 1 « violation » : un bug de *l'éval*
elle-même (la mention « Leoncino 800 » résolue sur le Leoncino 800 Trail,
variante plus longue) — corrigé en préférant le nom de longueur la plus
proche. Les échecs d'éval existent aussi ; ils se corrigent au même
standard que le reste.

## Reproduire

```bash
AGENT_BACKEND=ollama OLLAMA_MODEL=mistral-small3.2 EMBEDDER_DEVICE=cpu \
  PYTHONPATH=src .venv/bin/python scripts/eval_constraints.py
```

Écrit un fichier daté `eval_results/constraints/constraints_<modèle>_<date-UTC>.json`
avec provenance, sans remplacer le résultat historique.

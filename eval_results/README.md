# Résultats d'évaluation

Les résultats enregistrés des évaluations du POC local — la convention
du repo est « les résultats sont commités, les caches ne le sont pas ».

| Dossier | Couche | Ce qui est mesuré |
|---|---|---|
| [`retrieval/`](retrieval/) | 1 — retrieval seul, **aucun LLM** | La recherche sémantique pgvector + BGE-M3 fonctionne-t-elle vraiment ? |
| [`trajectory/`](trajectory/) | 1,5 — tool calls, **aucun juge LLM** | Le modèle choisit-il les bons outils avec les bons arguments ? (prédicats déterministes sur les appels enregistrés) |
| [`constraints/`](constraints/) | 1,75 — réponses finales, **aucun juge LLM** | Les motos recommandées violent-elles les contraintes dures (budget, cylindrée, poids…) ? Métrique primaire : taux de violation |
| [`ragas/`](ragas/) | 2 — agent complet | Qualité des réponses finales (faithfulness, answer relevancy) notée par deux juges indépendants |
| [`technical/`](technical/) | Catalogue technique, Jev et POC figés | Inventaires, audits, normalisation, intégration, questions et dialogues ; chaque fichier a son propre périmètre |
| [`smoke/`](smoke/) | Vérification locale ponctuelle | Fonctionnement d'un parcours sur un petit essai, sans estimation de précision générale |
| [`prices/`](prices/) | Qualité des données historiques | Audit de l'appariement des prix aux modèles et millésimes, distinct de la qualité du chat |

## Lire les résultats avant de les citer

Les JSON historiques sont conservés tels quels. Leurs scores décrivent un
run donné, avec son modèle et son corpus ; ils ne valident pas les correctifs
d'octobre 2026. Les anciens fichiers n'ont pas tous une date, une révision de
code ou une identité du corpus. Une date mentionnée dans un README est une
description historique, pas une métadonnée récupérable dans le JSON.

- Le run RAGAS entièrement local publié porte sur 12 questions : **0,61 /
  0,76**, génération mistral-small, juge qwen3.6.
- Le run **0,76 / 0,87** porte sur 17 questions avec génération locale et
  **juge Haiku distant**. La relevancy manque pour une question : sa moyenne
  porte sur 16 réponses. Les deux runs ne mesurent pas un gain contrôlé.
- Le self-retrieval vérifie le pipeline d'embedding et l'index ; il ne
  suffit pas à démontrer la pertinence sur de nouvelles questions. Les
  contrôles hors sujet comparent des distances, pas un refus de répondre.
- Le checker de contraintes historique pouvait classer une valeur
  numérique absente comme satisfaite. Le nouveau checker distingue les
  données insuffisantes ; les anciens taux ne sont pas recalculés ici.

Pour les dialogues techniques d'octobre, distinguer le **premier passage** sur
des questions nouvelles des **replays après correction**. Les replays deviennent
des vérifications de régression ; ils ne mesurent plus la généralisation à des
questions inédites. Certaines suites vérifient le routage vers une synthèse sans
exécuter cette génération. Une réponse partielle honnête n'est pas une réponse
complète, et un transport réussi n'est pas un verdict de qualité.

Les caches Jev et les vecteurs déjà présents peuvent raccourcir les replays.
Comparer séparément chargement initial, recherche avec modèles chauds et latence
du tour de chat ; ne pas additionner ou comparer des temps aux périmètres
différents. Les [notes des essais du 13 octobre](../docs/jev-partial-improvements.md)
précisent les premiers passages, les corrections et les réutilisations de cache.

Le prochain benchmark mots clés / BGE-M3 / hybride / reranking reste à exécuter.
Les anciens JSON ne constituent pas ses résultats ; son lot inédit et son
snapshot devront être identifiés avant le premier essai.

Les nouveaux scripts écrivent un **fichier daté distinct** et ajoutent des
métadonnées : date UTC, révision Git et état du checkout, versions,
configuration, identité des sources de code, du modèle et du corpus. La
génération RAGAS refuse un cache incompatible ; un changement du juge permet
de re-noter les mêmes réponses. `--regenerate` permet de générer à nouveau.

Cette révision ajoute des tests de régression sans base ni appels de modèle.
Aucun nouveau score de qualité de bout en bout n'est publié sans exécution
effective des évaluations sur la base et les modèles locaux.

Chaque dossier contient un README qui publie les chiffres et pointe vers le
document de preuve hébergé sur GitHub Pages :

- [Preuve de fonctionnement — recherche sémantique](https://maax6.github.io/bikefinder-rag/preuve-retrieval.html)
- [De la page web au score RAGAS — le pipeline](https://maax6.github.io/bikefinder-rag/pipeline-et-evaluation.html)
- [Un agent RAG sans framework — la méthode](https://maax6.github.io/bikefinder-rag/methode-sans-langchain.html)

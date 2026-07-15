# Couche 1 — preuve du retrieval (sans LLM)

**Document de preuve complet : [Preuve de fonctionnement — recherche
sémantique Bikefinder](https://maax6.github.io/bikefinder-rag/preuve-retrieval.html)**

`scripts/eval_retrieval.py` interroge pgvector directement — aucun appel LLM,
ni Anthropic ni Ollama — pour juger la qualité du retrieval sans la confondre
avec la qualité de rédaction d'un modèle. Quatre tests, du « la plomberie
marche-t-elle » au « est-ce sémantiquement utile » :

1. **Intégrité des données** — comptes, orphelins, embeddings nuls, doublons.
2. **Self-retrieval** — ré-embedder le texte d'un commentaire et le chercher
   doit le retrouver lui-même au rang 1, à distance ~0 (test de plomberie).
3. **Lift par thème** — le taux de correspondance mot-clé dans le top-30
   sémantique comparé au taux de base du corpus. Un lift ~1× = pas mieux que
   le hasard.
4. **Contrôle négatif + cross-lingue** — une requête hors-sujet doit scorer
   nettement plus loin, et une requête française doit retrouver les mêmes
   commentaires anglais que son équivalent anglais.

## Résultats (14 juillet 2026 — corpus complet : 32 395 motos, 107 952 commentaires embarqués)

Fichier brut : [`retrieval_report.json`](retrieval_report.json)

**Intégrité** : 0 embedding nul, 0 commentaire orphelin, 0 doublon exact ;
19 532 motos (60 %) reliées à au moins un avis.

**Self-retrieval** : 30/30 au rang 1, distance moyenne 0.0.

**Lift par thème** (top-30 sémantique vs taux de base corpus) :

| Thème | Hits top-30 | Lift |
|---|---|---|
| Vibrations à haute vitesse | 24/30 | **122×** |
| Confort de selle | 4/30 | **97×** |
| Consommation d'essence | 19/30 | **36×** |
| Adaptée aux débutants | 14/30 | **32×** |
| Freins | 17/30 | **22×** |
| Fiabilité | 7/30 | 2.3× * |

\* Artefact de mesure, pas un échec : le mot-clé de contrôle (« problem »,
« issue »…) est si générique que son taux de base atteint 11 % du corpus, et
les résultats remontés sont pertinents mais reformulés sans le mot-clé
littéral. Détail dans le document de preuve.

**Contrôles négatifs** : « recette de gâteau au chocolat » → distance 0.43,
« framework web Python » → 0.50, nettement pires que les requêtes moto
(0.04–0.36). **Cross-lingue** : la requête française sur la fiabilité
partage 3 de son top-10 avec la requête anglaise équivalente (~25× le
hasard) ; la paire consommation ne se recouvre pas sur ce run — le hybride
dense+sparse ou un reranker (`bge-reranker-v2-m3`) est la piste identifiée.

## Reranker cross-encoder (ajouté le 15 juillet 2026)

`search_reviews` fait maintenant du retrieval en deux étages : shortlist
dense top-50 (pgvector), puis re-tri par **bge-reranker-v2-m3** (même
famille BGE-M3 que l'embedder), qui lit la requête et le commentaire
*ensemble*. Mesure dédiée (`french_relevance` dans le rapport) : résultats
on-topic (proxy mot-clé anglais) dans le top-10 d'une requête française —

| Thème (requête FR) | Dense seul | Reranké |
|---|---|---|
| Vibrations | 6/10 | **10/10** |
| Consommation | 4/10 | **6/10** |
| Confort de selle | 1/10 | **3/10** |
| Débutant | 3/10 | 3/10 |
| Freins | 0/10 | 0/10 |
| **Total** | **14/50** | **22/50 (+57 %)** |

Deux honnêtetés : (1) le recouvrement Jaccard FR/EN des top-10 ne bouge
pas — le reranker ne peut réordonner que sa shortlist, il ne crée pas de
rappel ; (2) « freins » reste à zéro pour la même raison : le pool dense
de cette requête FR ne contient pas les bons candidats. Le rappel dense
reste la borne ; la piste suivante serait l'hybride dense+sparse.
Latence : ~0,4 s par requête à chaud sur Apple Silicon ;
`RERANKER_ENABLED=0` le coupe (c'est le réglage du Docker Space, où le
CPU le rendrait trop lent).

Le document de preuve hébergé présente le run du 12 juillet 2026 sur le
corpus « century » (82 589 commentaires) ; l'éval a été rejouée après le
chargement des années 2000 et tous les tests restent au vert à 107 952
commentaires — ce sont les chiffres du tableau ci-dessus.

## Reproduire

```bash
PYTHONPATH=src .venv/bin/python scripts/eval_retrieval.py
```

Écrit `eval_results/retrieval/retrieval_report.json` (écrasé à chaque run ;
l'historique des corpus est porté par git).

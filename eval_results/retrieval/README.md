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

## L'hybride mesuré sur le chemin livré (31 août 2026)

Le tableau ci-dessus a été mesuré le 15 juillet. L'hybride dense+sparse est
arrivé **le 16 juillet** et n'a touché ni `scripts/eval_retrieval.py` ni ce
rapport : `french_relevance_test` réimplémentait sa propre recherche au lieu
d'appeler `search_reviews`. Le « +57 % » a donc été attribué pendant six
semaines à un pipeline que rien n'avait évalué.

L'éval appelle maintenant la vraie fonction. Quatre bras, résultats
identiques sur deux runs consécutifs :

| Thème (requête FR) | Dense | Reranké | `search_reviews` FR | `search_reviews` EN |
|---|---|---|---|---|
| Consommation | 4/10 | 6/10 | 5/10 | **9/10** |
| Vibrations | 6/10 | **10/10** | 9/10 | 5/10 |
| Confort de selle | 1/10 | 3/10 | 2/10 | 1/10 |
| Débutant | 3/10 | 3/10 | 3/10 | 1/10 |
| Freins | 0/10 | 0/10 | **1/10** | **2/10** |
| **Total** | **14/50** | **22/50** | **20/50** | **18/50** |

Le bras « reranké » retombe exactement sur le 22/50 de juillet : l'instrument
est validé avant d'être cru.

**Le sparse verse effectivement du bruit dans le pool.** Mesuré sur
« les freins sont-ils bons » : `websearch_to_tsquery('english', …)` rend
**0 document**, le repli OR en rend **226** sur des tokens parasites, et la
fusion RRF laisse ce bruit **évincer 14 à 19 candidats denses légitimes** du
pool de 50. Le repli OR existe pour que des termes rares comme « SMC »
sortent quand même ; en français il part systématiquement, puisque la branche
AND ne rend jamais rien.

**Mais le corriger ne rapporte rien — mesuré, pas supposé (1er septembre).**
Deux leviers essayés :

| levier | livré FR | livré EN |
|---|---|---|
| tel quel | 20/50 | 18/50 |
| repli OR supprimé (fusion si AND a donné) | **21/50** | **17/50** |

| pool dense | 50 | 100 | 200 | 400 |
|---|---|---|---|---|
| on-topic /50 | 21 | 21 | 21 | 20 |

Le premier déplace un point dans chaque sens. Le second ne bouge pas le
total en multipliant le pool par huit — il redistribue seulement entre
thèmes (les freins montent de 0 à 2, les vibrations tombent de 10 à 7).

**Donc le plafond n'est ni la fusion ni le rappel dense.** Il reste deux
suspects, et les départager demande du travail neuf : la capacité du
cross-encoder à classer du français contre un corpus anglais, et la
validité du proxy mot-clé lui-même. Ce second point rejoint l'item RAGAS
resté ouvert — `context_precision`/`context_recall` demandent une
ground-truth annotée à la main, qui trancherait aussi cette question.
L'état honnête de cette métrique est **mesurée, pas résolue**.

### Trois biais de méthode, déclarés

1. **Les requêtes anglaises évitent volontairement les mots de la regex**
   (« how well does it stop in an emergency », pas « brakes »). Sinon le bras
   sparse retrouverait exactement les termes que le proxy compte et le score
   monterait sans rien mesurer. Le prix de ce choix : le bras EN est pénalisé
   sur les thèmes où le mot naturel *est* le mot de la regex — **18/50 est un
   plancher, pas une mesure d'égalité.**
2. **`hnsw.ef_search` vaut 40 par défaut**, donc une shortlist demandée à 50
   revenait à 43. `search_reviews` le règle désormais sur `max(fetch, 40)`.
   Sans effet en production (la limite par défaut de l'outil est 5, soit un
   `fetch` de 30), l'écart ne mordait que sur les appels à limite ≥ 7 — dont
   cette éval. Les bras dense/reranké sont explicitement remis à 40 avant
   chaque thème : `SET` persiste sur la session, et sans ce reset ils
   héritaient du réglage du thème précédent.
3. **Le corpus n'est pas exactement celui de juillet.** Reconstruit le
   31 août depuis les `data/` du dépôt : **104 418 commentaires contre les
   107 952 publiés** (−3,3 %). Le loader et le seuil des 3 commentaires n'ont
   pas changé depuis, donc l'écart vient de la lignée des données, pas du
   code : la base de juillet avait accumulé des passes de scrape dont les
   fichiers ont été remplacés depuis. **Le 107 952 n'est pas reproductible
   depuis ce dépôt ; le 104 418 l'est.** Les motos (32 395), familles
   (4 335), rappels (3 521) et prix FR (7 137) retombent tous juste.

## Reproduire

```bash
PYTHONPATH=src .venv/bin/python scripts/eval_retrieval.py
```

Écrit `eval_results/retrieval/retrieval_report.json` (écrasé à chaque run ;
l'historique des corpus est porté par git).

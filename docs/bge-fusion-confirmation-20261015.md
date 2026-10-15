# Confirmation de la fusion BGE-M3 sur 64 questions inédites

15 octobre 2026. **La fusion ajustée n'est pas intégrée au chat.** Elle améliore
la couverture moyenne, mais fait perdre des preuves sur trois nouvelles
questions et un ancien cas. La condition d'intégration « gain sans régression »
n'est donc pas satisfaite.

## Résultat

Les deux réglages interrogent les mêmes **105 687 passages** avec le même BGE-M3,
sans périmètre d'identité fourni par les annotations. La référence est la fusion
RRF actuelle, poids dense/lexical 1:1 et 40 candidats par branche. Le candidat,
choisi lors de l'[étude précédente](bge-m3-ameliorations-recherche-20261015.md),
garde la constante RRF 60, passe à 2:1 et examine 80 candidats par branche.
Les deux livrent dix passages. Aucun réglage n'a été adapté après les résultats.

| Mesure | Fusion actuelle 1:1 / 40 | Fusion ajustée 2:1 / 80 |
|---|---:|---:|
| Nouvelles questions : toutes les preuves à 10 | 49/64 (76,6 %) | 54/64 (84,4 %) |
| Nouvelles questions : première preuve pertinente | 44/64 | 47/64 |
| Nouvelles questions : rappel moyen des preuves à 10 | 88,7 % | 91,0 % |
| Nouvelles questions : latence médiane | 39,9 ms | 40,3 ms |
| Anciens cas : toutes les preuves à 10 | 17/28 | 20/28 |
| Anciens cas : première preuve pertinente | 19/28 | 20/28 |

Sur les 64 nouvelles questions, **six deviennent complètes et une cesse de
l'être** : le gain net est de cinq cas, soit 7,8 points sur ce lot. Deux autres
questions déjà incomplètes perdent une preuve supplémentaire. Les anciens cas
présentent quatre gains de complétude et une perte. Les totaux seuls masquent
donc quatre questions dégradées.

La comparaison par catégorie donne :

| Catégorie nouvelle | Nombre | Complètes avant | Complètes après |
|---|---:|---:|---:|
| Une section | 16 | 16 | 16 |
| Plusieurs sections | 32 | 25 | 28 |
| Comparaison de millésimes | 8 | 6 | 6 |
| Comparaison de modèles aux noms proches | 8 | 2 | 4 |

Il s'agit de retrouver les preuves annotées, pas de mesurer l'exactitude de
réponses rédigées. Dix questions conservent des valeurs explicitement inconnues
dans les sources : retrouver « non défini » ne permet pas de donner un coloris.

## Les quatre régressions vérifiées

| Cas | Preuve qui sort du top 10 | Rang avant → après | Effet |
|---|---|---:|---|
| F020 — Norton 1200 V4 CR 2023, freins avant/arrière | Train arrière : disque 245 mm, étrier 2 pistons | 5 → 13 | Complète → incomplète |
| F023 — Zero Motorcycles DS 2026, puissance et poids | Moteur, avec les puissances et leurs qualificatifs | 10 → 14 | Une question déjà incomplète perd encore une preuve |
| F058 — Aprilia Tuono V4 USA / standard 2023 | Moteur de la Factory Limited Edition USA | 6 → 12 | Comparaison déjà incomplète davantage amputée |
| HOLDOUT-022 — Suzuki GSX-8S 800 2024 | Équipement de série, dont contrôle de traction | 9 → 11 | Ancien cas complet → incomplet |

La [revue détaillée des régressions](../eval_results/technical/bge-fusion-confirmation-20261015/regressions-annotees.md)
conserve les textes, URL, empreintes et rangs. Des années ou variantes voisines
entrent dans les dix résultats : notamment des Zero DS 2012, 2017 et 2018 pour
la question 2026. Le candidat change à la fois le poids et la taille du pool ;
ce test ne sépare pas causalement leurs effets.

## Lot figé et règle de décision

Les [64 questions annotées](../eval_results/technical/bge-fusion-confirmation-20261015/bundle/questions-annotees.md)
portent sur **80 fiches distinctes, 24 marques et des millésimes de 2000 à 2026**.
Aucune fiche cible n'est réutilisée entre ces nouvelles questions. Les cibles
sont absentes des fichiers de questions et d'annotations antérieurs inventoriés
dans l'[audit de nouveauté](../eval_results/technical/bge-fusion-confirmation-20261015/bundle/novelty-audit.json).
Les familles et marques peuvent néanmoins avoir été vues auparavant.

La sélection des sources est déterministe, par marque, période et disponibilité
des faits, sans consulter les classements. Les questions proviennent de gabarits
écrits par l'assistant, avec leurs réponses relues dans les sources avant
l'inférence. Ce ne sont ni 64 formulations issues d'utilisateurs réels ni une
annotation humaine indépendante. Les 28 anciens cas restent un ensemble de
régression séparé ; ils ne sont pas comptés comme inédits.

La [relecture préalable](../eval_results/technical/bge-fusion-confirmation-20261015/source-review.json)
a précisé les valeurs inconnues, approximatives et les puissances nominales ou
maximales. Elle a conservé les questions et passages cibles. La première version
des annotations reste archivée dans le dossier pre-review-bundle. Aucune recherche
n'avait encore eu lieu ; la version finale est figée par empreintes.

Le [protocole](../eval_results/technical/bge-fusion-confirmation-20261015/bundle/protocol.json)
fixait les critères suivants avant le premier classement :

- gain net d'au moins cinq nouvelles questions complètes ;
- aucun groupe de preuves nécessaire perdu, même sur une question déjà incomplète,
  dans le nouveau lot comme dans les anciens cas ;
- aucune baisse du nombre de premiers résultats pertinents dans chaque lot ;
- test exact apparié unilatéral sur les gains/pertes de complétude, seuil 0,05 ;
- médiane inférieure à max(référence × 1,25 ; référence + 10 ms) ;
- intégrité des sources, des poids et de l'index, parité de la référence et
  stabilité des classements entre répétitions.

La [décision enregistrée](../eval_results/technical/bge-fusion-confirmation-20261015/run-v1/decision.json)
rejette la promotion pour deux raisons : les pertes de preuves, et une valeur
du test apparié de **0,0625** pour six gains et une perte. Cette valeur est
descriptive : les questions d'une même marque ou famille peuvent être corrélées.
La perte de preuves suffit à elle seule à refuser l'intégration demandée.

## Vérifications et limites

Les **552 recherches** correspondent à 92 questions × 2 réglages × 3 répétitions,
dans un ordre mélangé. Les classements sont identiques entre répétitions. Les
trois sondes de parité reproduisent exactement le service FrozenRetrieval
actuel. Les modèles ne reçoivent ni identités attendues, ni réponses, ni labels.

Les médianes incluent l'encodage de la question, la recherche et la fusion ;
elles excluent le chargement initial. La suite de tests du code a chevauché les
dernières secondes de la troisième répétition : ces latences sont indicatives,
sans prétention d'isolation de la machine. Sur la première répétition avant ce
chevauchement, les médianes étaient déjà 39,94 et 40,32 ms. Aucune conclusion
ne repose sur les quelques dixièmes de milliseconde d'écart.

L'[audit d'intégrité](../eval_results/technical/bge-fusion-confirmation-20261015/run-v1/integrity.json)
confirme les sources, tous les fichiers d'index, les poids BGE et les annotations
inchangés. Aucun entraînement ni appel API distant : **0 $ de coût API**.
Les scripts exécutés sont archivés avec leurs empreintes. La suite du code
donne **1 196 tests réussis et 8 désactivés**, dont des garde-fous qui empêchent
un gain moyen de masquer une perte sur un cas partiel ou ancien.

Le code du chat et sa configuration ne sont pas modifiés. L'inspection confirme
que le service commun évalué n'est pas encore le parcours de recherche utilisé
par l'interface : catalog/research.py et catalog/technical_rag.py utilisent
leurs classements BGE sur des périmètres résolus. Aucun résultat du présent
benchmark n'est présenté comme une validation de réponses finales du chat.

L'hypothèse suivante à tester séparément est la conservation du millésime et de
la variante lors de la sélection des preuves. Fournir manuellement les bonnes
identités ne suffirait pas à valider cette résolution automatique.

## Reproduire

Le lot final et les deux réglages sont conservés. Pour refaire l'exécution sans
écraser le premier résultat, utiliser un nouveau répertoire :

~~~bash
PYTHONPATH=src HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  .venv/bin/python scripts/validate_bge_fusion.py run \
  --bundle eval_results/technical/bge-fusion-confirmation-20261015/bundle \
  --out /private/tmp/bge-fusion-confirmation-reproduction
~~~

Le script requiert le corpus et le modèle figés présents localement, ainsi que
l'accès à MPS sur cette machine. Le mode prepare sert à reconstruire un lot
depuis les sources et l'inventaire historique disponible ; l'exécution du lot
archivé est la référence pour reproduire ces chiffres.

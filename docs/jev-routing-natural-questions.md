# Routage naturel du catalogue — 13 octobre 2026

Le chatbot local utilise désormais Jev pour choisir un plan fermé, puis SQL pour
répondre avec les valeurs et les liens des fiches. Jev ne produit ni SQL libre ni
nouvelles valeurs numériques. Les opérateurs et unités explicites sont vérifiés.
Les prix sont ceux de la version de base France documentée, pas des annonces.

## Résultats

Le lot contient 480 questions variées mais construites à partir de familles de
formulations : prix/puissance, marques et millésimes, équipements, détails de
fiches, critères non représentables et demandes de synthèse. Les réponses sont
contrôlées contre les plans attendus et les données SQL. Le modèle génératif
n'a pas été lancé 480 fois : les dix demandes complexes évaluent leur routage.

| Mesure | Résultat |
|---|---:|
| Réponses factuelles directes | 440 |
| Clarifications explicites | 30 |
| Synthèses nécessaires | 10 |
| Acceptation finale | 480/480 |
| Première évaluation sur familles réservées | 115/123 |
| Médiane sans cache Jev | 0,355 s |
| 95e percentile sans cache Jev | 0,483 s |
| Médiane du rejeu final en cache | 0,059 s |
| 95e percentile du rejeu final en cache | 0,104 s |
| Coût fournisseur du seul lot froid final | 0,067 USD |
| Tests du contenu publié, base locale comprise | 525 réussis |
| Tests de tout le workspace local | 542 réussis |

Les huit erreurs initiales des familles réservées ont été corrigées ; ce lot
n'est donc plus indépendant après réajustement. Ces chiffres ne mesurent pas
une précision générale sur toutes les questions de vrais utilisateurs.
L'ancien raccourci reconnaissait seulement 2/480 formulations. Seule la question
réelle de l'utilisateur avait un délai antérieur observé de 180 s, pas tout le lot.

## Vérification du chatbot actif

« Motos en dessous de 10000 eu et minimum 100 cv en 2020 » : neuf fiches avec
preuves, en 0,167 s via l'API Gradio. Deux fiches Suzuki portent le même nom mais
ont des URL sources différentes : il s'agit d'un nombre de fiches.
« Et en 2021 ? » : cinq fiches, en 0,538 s, budget et puissance conservés.
La reprise à partir de l'historique visible fonctionne aussi après perte de
l'état serveur (0,121 s). La demande ABS 2000 avec une taille de liste explicite
reste un filtre ABS de série (deux fiches, 0,425 s), jamais ABS inconnu.

## Garde-fous et limites

Une absence de mention reste inconnue. Poids sec et poids en ordre de marche ont
des projections distinctes ; le libellé source reste visible. Les autonomies
conservent leurs qualifications. Les projections sont liées au hash de la fiche
pour exclure les valeurs devenues périmées. Les critères non pris en charge,
notamment certains filtres composés, conduisent à une clarification.
Une régression intermédiaire faisait inventer un filtre ABS depuis les métadonnées
du classificateur : détectée par le lot, corrigée avant activation finale.

Les synthèses utilisent un seul appel Mistral, un budget de 30 s et des extraits
bornés. Jev contrôle ensuite les affirmations. L'essai réel mesuré à 30,132 s
a produit des conclusions causales non étayées : rejetées, avec retour des faits
sources. Ce test valide le repli, pas une synthèse causale réussie. Une synthèse
en cours ne doit pas bloquer les requêtes SQL d'autres sessions.
Jev est distant via OpenRouter : les questions et les extraits nécessaires au
contrôle de synthèse lui sont transmis. Le catalogue, SQL et Mistral sont locaux.

Les 542 tests correspondent à l’ensemble du workspace local, y compris des
travaux de collecte non inclus dans ce commit. La copie contenant exactement le contenu sélectionné pour publication passe
525 tests, intégration PostgreSQL comprise, en 10,24 s.

## Reproduire

```sh
BIKEFINDER_JEV_ROUTER=0 PYTHONPATH=.:src RUN_CATALOG_INTEGRATION=1 .venv/bin/pytest -q
PYTHONPATH=src .venv/bin/python scripts/evaluate_jev_routing.py --prepare --split all --out data/technical/routing-eval-20261013/replay.json
```

Résultats agrégés : `eval_results/technical/jev_routing_20261013.json`.
Les questions et réponses détaillées restent dans le répertoire local ignoré
`data/technical/routing-eval-20261013/`. La collecte n'a pas été relancée ni modifiée.

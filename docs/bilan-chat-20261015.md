# Le chat corrigé — bilan du 15 octobre 2026

[Ouvrir le bilan HTML avant/après](benchmark-chat-20261015.html) ·
[Bilan initial conservé](benchmark-chat-20261015-initial.html) ·
[Résultats et traces](../eval_results/technical/chat-corrections-20261015/reviewed-results.json)

**Les corrections améliorent les réponses avec BGE-M3 d’origine.** Les valeurs
approximatives et équipements perdus sont restitués ; maximums, minimums et
moyennes sont calculés sur toute la population demandée ; relances et pagination
conservent le contexte. Aucun réentraînement ni remplacement de BGE.

## Qualité observée

| Population | Avant | Après |
|---|---:|---:|
| Même lot de 36 demandes, limites pertinentes comprises | 25/36 | 36/36 |
| Dialogues dont les deux tours sont satisfaisants | 4/6 | 6/6 |
| Six tours des captures | 1/6 | 5/6 |
| Quinze tours supplémentaires, dont trois sur le prix moyen | — | 15/15 |

Sur les 42 tours appariés : **15 améliorations, 27 résultats conservés, aucune
régression de contenu observée**. Le cas XJ6 A2 2011 reste partiel : la réponse
limite correctement ce que la fiche peut certifier, mais demande modèle/année
au lieu de clarifier la variante. Les réponses exactes peuvent encore contenir
des avertissements de couverture trop génériques ou un tableau de secours.

## Prix moyen et autres calculs

- Yamaha 2020, prix France de base : **12 446,93 €**, sur **42 prix connus parmi
  43 fiches** (522 771 / 42). Le prix absent est exclu, jamais assimilé à zéro.
- Honda CB 500 F, millésimes 2020–2022 : **6 565,67 €**, sur les trois tarifs
  6 399, 6 499 et 6 799 €. Montants arrondis ici au centime ; le chat affiche
  trois décimales.
- Ces moyennes portent sur les tarifs du catalogue, sans pondération par les
  ventes. Le chat refuse de les substituer à des prix actuels d’occasion.
- Bandit 2000–2001 : **214 kg à sec** et **244 kg tous pleins**, calculés séparément.
- Maximum Yamaha 2020 : **1 298 cc**, deux FJR ex æquo sur 43 fiches. Les autres
  maxima/minima indiquent aussi leur couverture et tous les ex æquo.

## Temps, erreurs et coût

Sur les mêmes 36 tours, médiane **24,03 → 8,38 s**, P95 **33,07 → 31,01 s**.
Les caches et modèles sont déjà chauds au second passage : ce gain ne mesure
pas uniquement l’effet du code. Les 23 tours finaux avec recherche BGE ont une
médiane de **14,49 s**. Trois rédactions expirent encore près de 30 secondes et
une rédaction est rejetée ; des tableaux sourcés préservent alors les réponses.
Aucune erreur du point d’entrée Gradio sur les 63 soumissions finales.

Coût des corrections, passe intermédiaire comprise : **0,009547020 $**,
64 appels Jev/OpenRouter. Avec la campagne initiale : **0,017885532 $**, sous
0,50 $. Toutes les réservations sont soldées. BGE et Mistral restent locaux ;
énergie et amortissement non mesurés.

## Protocole et limites

Le lot initial comportait 36 tours alors inédits, six tours des captures et six
répétitions. Il constitue désormais un lot de régression. Une première passe
corrigée de 48 soumissions a révélé deux défauts résiduels : génération voisine
lors d’une réponse d’année et accord masculin de « moyen ». Elle est conservée
dans `iteration-1`. Après correction, les 48 soumissions ont été rejouées,
puis les 12 tours supplémentaires autorisés et les trois tests du prix moyen,
figés avant leur exécution. **111 soumissions pour cette correction**, dont
63 dans la mesure finale ; aucune réponse intermédiaire effacée.

Même point d’entrée Gradio `/chat`, mode rapide Jev + SQL + BGE-M3 original +
Mistral Small 3.2 24B Q4_K_M local. Révision BGE
`5617a9f61b028005a4858fdac845db406aefb181`. Le corpus conserve 11 478 fiches et
105 687 passages ; empreintes sources SQLite/PostgreSQL identiques. Aucune
modification applicative pendant la passe finale, vérifiée par empreintes.

Les corrections ont été guidées par le lot initial. Les cas supplémentaires
restent proches des familles travaillées ; rédaction et relecture sont faites
par le même agent. Le score valide les réponses et limites sur ces cas, pas une
qualité universelle ni une validation indépendante auprès des constructeurs.

Vérification logicielle : **1 232 tests réussis**, 11 tests SQL ignorés dans la
suite isolée puis **11/11 réussis sur PostgreSQL**, dans un schéma temporaire.
Les tests simulés vérifient le code ; la qualité annoncée ci-dessus vient des
réponses du vrai chat enregistrées séparément.

[Lots figés](../eval_results/technical/chat-corrections-20261015/questions-final.json) ·
[Lot prix moyen](../eval_results/technical/chat-corrections-20261015/questions-price.json) ·
[Relecture](../eval_results/technical/chat-corrections-20261015/review.json) ·
[Mesures](../eval_results/technical/chat-corrections-20261015/summary.json) ·
[Configuration](../eval_results/technical/chat-corrections-20261015/server/runtime.json) ·
[Coût](../eval_results/technical/chat-corrections-20261015/server/spending.json)

La suite utile est une relecture humaine sur un nouveau lot, puis l’amélioration
des avertissements, de la clarification XJ6 et de la latence de rédaction.
Le [plan de validation complet](phase-test-20261015.md) reste applicable.

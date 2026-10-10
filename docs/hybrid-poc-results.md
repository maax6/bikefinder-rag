# POC SQL, BGE-M3, Jev et Mistral

Rapport généré à partir des artefacts complets et des références figées. Le POC ne modifie ni la collecte ni le catalogue de production.

**Résultat : la cascade égale Mistral systématique sur l’audit (54/60, dont 34/37 dans le test), avec 32 replis Mistral sur 341 entrées distinctes. Parmi les 173 entrées contenant une mention d’équipement, 141 évitent Mistral (81,5 %). Ce lot montre une réduction des appels ; il ne démontre pas un gain de précision.**

**Index : 2 254 fiches source et 19 901 passages. Classification : 706 fiches distinctes  880 décisions fiche–équipement  341 entrées distinctes et 224 familles de textes.**

Le lot comprend 680 couples fiche–équipement et 200 contrôles sans mention d’ABS. Les doublons sont évalués une fois puis rattachés à leurs fiches ; 880 décisions ne sont donc pas 880 exemples indépendants.

## Références et méthode

Les 60 références ont été annotées par un agent indépendant à partir des extraits avant consultation des sorties de ce benchmark. Elles ne constituent pas une validation humaine ou constructeur des équipements réels. Elles sont volontairement variées, plutôt qu’un échantillon représentatif du catalogue. Les familles du premier pilote restent dans le développement.

L’expérience compare le statut d’équipement. Le marché est conservé inconnu par le code et ne constitue pas une question évaluée par Jev dans ce lot.

Les règles évaluées sont les règles simplifiées de ce POC, sans optimisation systématique sur le catalogue. Cette comparaison ne démontre pas un avantage sur le meilleur moteur de règles possible.

Macro-F1 : moyenne des F1 des classes présentes dans les références du sous-ensemble. Le développement n’a aucun exemple « explicitement absent » ; cette classe n’y est pas incluse dans la moyenne. Les erreurs, inconnus et cas ambigus restent dans le score strict.

| Sous-ensemble | Méthode | Concordance | Macro-F1 | Affirmations sur référence inconnue |
|---|---|---:|---:|---:|
| Strict — 60 références | Règles du POC | 50/60 (83.3 %) | 0.598 | 4/16 |
| Strict — 60 références | Jev | 54/60 (90.0 %) | 0.909 | 5/16 |
| Strict — 60 références | Mistral | 54/60 (90.0 %) | 0.899 | 4/16 |
| Strict — 60 références | Cascade | 54/60 (90.0 %) | 0.899 | 4/16 |
| Test — 37 références | Règles du POC | 30/37 (81.1 %) | 0.507 | 2/12 |
| Test — 37 références | Jev | 34/37 (91.9 %) | 0.917 | 3/12 |
| Test — 37 références | Mistral | 34/37 (91.9 %) | 0.888 | 2/12 |
| Test — 37 références | Cascade | 34/37 (91.9 %) | 0.888 | 2/12 |
| Développement — 23 références | Règles du POC | 20/23 (87.0 %) | 0.801 | 2/4 |
| Développement — 23 références | Jev | 20/23 (87.0 %) | 0.807 | 2/4 |
| Développement — 23 références | Mistral | 20/23 (87.0 %) | 0.801 | 2/4 |
| Développement — 23 références | Cascade | 20/23 (87.0 %) | 0.801 | 2/4 |
| Diagnostic hors 4 portées ambiguës — 56 références | Règles du POC | 50/56 (89.3 %) | 0.663 | 0/12 |
| Diagnostic hors 4 portées ambiguës — 56 références | Jev | 54/56 (96.4 %) | 0.963 | 1/12 |
| Diagnostic hors 4 portées ambiguës — 56 références | Mistral | 54/56 (96.4 %) | 0.970 | 0/12 |
| Diagnostic hors 4 portées ambiguës — 56 références | Cascade | 54/56 (96.4 %) | 0.970 | 0/12 |
| Diagnostic test hors 2 portées ambiguës — 35 références | Règles du POC | 30/35 (85.7 %) | 0.565 | 0/10 |
| Diagnostic test hors 2 portées ambiguës — 35 références | Jev | 34/35 (97.1 %) | 0.951 | 1/10 |
| Diagnostic test hors 2 portées ambiguës — 35 références | Mistral | 34/35 (97.1 %) | 0.958 | 0/10 |
| Diagnostic test hors 2 portées ambiguës — 35 références | Cascade | 34/35 (97.1 %) | 0.958 | 0/10 |

| Sous-ensemble audité | Étape choisie par la cascade | Accord strict |
|---|---|---:|
| Strict 60 | jev | 39/39 |
| Strict 60 | mistral_fallback | 5/11 |
| Strict 60 | code_no_mention | 10/10 |
| Test 37 | jev | 22/22 |
| Test 37 | mistral_fallback | 4/7 |
| Test 37 | code_no_mention | 8/8 |

L’accord sur les cas acceptés par le garde-fou est une précision conditionnelle sur cet échantillon sélectionné. Il ne démontre pas la calibration du seuil ni une garantie de sécurité sur le catalogue. Les rejets et replis demeurent dans les scores stricts.

## Portées de qualificatifs : diagnostic, sans changer le test

Les consignes des modèles imposent qu’un qualificatif final « en option » s’applique au groupe entier. Les quatre annotations ci-dessous suivent une politique plus prudente : la portée non résolue reste inconnue. C’est un conflit de politique d’interprétation ; il ne faut ni remplacer les références après les résultats, ni transformer le diagnostic à 56 cas en score principal.

| Cas | Extrait | Cible | Référence figée | Jev | Mistral | Cascade |
|---|---|---|---|---|---|---|
| f3dc7d5ab4a229bbfadd (dev) | Assistance au freinage : Dual CBS - ABS - TCS en option | ABS | unknown | optional | optional | optional |
| b01d3a7e02e0ddd5356d (dev) | Assistance au freinage : Dual CBS - ABS - TCS en option | CBS | unknown | standard | optional | optional |
| 60b6ea7e0628aaa8a7f6 (test) | Assistance au freinage : ABS + CBS en option | ABS | unknown | standard | optional | optional |
| ba1fb8f64bf0dc4e115b (test) | Assistance au freinage : Dual CBS - ABS en option | CBS | unknown | standard | optional | optional |

Jev répond « optional » conformément à la consigne de groupe sur le premier cas ABS. Ses réponses « standard » sur les trois autres ne suivent pas cette consigne ; leur exactitude factuelle demanderait néanmoins une adjudication de la source. Le diagnostic exclut les mêmes quatre cas pour toutes les méthodes.

Les autres désaccords restent inclus : source « ASB » possiblement fautive, suffixe Ride by Wire tronqué et « ABS déconnectable sur demande ». Ils interrogent respectivement la correction des fautes source, la preuve de présence et la différence entre désactivation et option d’achat.

## Confusions sur les 60 références

Chaque ligne est la référence, chaque colonne la décision. Les zéros ne sont pas omis.

### Règles du POC

| Référence \ décision | Série | Option | Absence explicite | Inconnu |
|---|---:|---:|---:|---:|
| standard | 30 | 0 | 0 | 3 |
| optional | 0 | 8 | 0 | 2 |
| explicitly_absent | 1 | 0 | 0 | 0 |
| unknown | 0 | 4 | 0 | 12 |

| Classe | Effectif | Précision | Rappel | F1 |
|---|---:|---:|---:|---:|
| standard | 33 | 96.8 % | 90.9 % | 0.937 |
| optional | 10 | 66.7 % | 80.0 % | 0.727 |
| explicitly_absent | 1 | 0.0 % | 0.0 % | 0.000 |
| unknown | 16 | 70.6 % | 75.0 % | 0.727 |

### Jev

| Référence \ décision | Série | Option | Absence explicite | Inconnu |
|---|---:|---:|---:|---:|
| standard | 32 | 0 | 0 | 1 |
| optional | 0 | 10 | 0 | 0 |
| explicitly_absent | 0 | 0 | 1 | 0 |
| unknown | 3 | 2 | 0 | 11 |

| Classe | Effectif | Précision | Rappel | F1 |
|---|---:|---:|---:|---:|
| standard | 33 | 91.4 % | 97.0 % | 0.941 |
| optional | 10 | 83.3 % | 100.0 % | 0.909 |
| explicitly_absent | 1 | 100.0 % | 100.0 % | 1.000 |
| unknown | 16 | 91.7 % | 68.8 % | 0.786 |

### Mistral

| Référence \ décision | Série | Option | Absence explicite | Inconnu |
|---|---:|---:|---:|---:|
| standard | 31 | 1 | 0 | 1 |
| optional | 0 | 10 | 0 | 0 |
| explicitly_absent | 0 | 0 | 1 | 0 |
| unknown | 0 | 4 | 0 | 12 |

| Classe | Effectif | Précision | Rappel | F1 |
|---|---:|---:|---:|---:|
| standard | 33 | 100.0 % | 93.9 % | 0.969 |
| optional | 10 | 66.7 % | 100.0 % | 0.800 |
| explicitly_absent | 1 | 100.0 % | 100.0 % | 1.000 |
| unknown | 16 | 92.3 % | 75.0 % | 0.828 |

### Cascade

| Référence \ décision | Série | Option | Absence explicite | Inconnu |
|---|---:|---:|---:|---:|
| standard | 31 | 1 | 0 | 1 |
| optional | 0 | 10 | 0 | 0 |
| explicitly_absent | 0 | 0 | 1 | 0 |
| unknown | 0 | 4 | 0 | 12 |

| Classe | Effectif | Précision | Rappel | F1 |
|---|---:|---:|---:|---:|
| standard | 33 | 100.0 % | 93.9 % | 0.969 |
| optional | 10 | 66.7 % | 100.0 % | 0.800 |
| explicitly_absent | 1 | 100.0 % | 100.0 % | 1.000 |
| unknown | 16 | 92.3 % | 75.0 % | 0.828 |

## Ensemble silver : descriptif, pas mesure de vérité

815 décisions disposent d’une référence produite par règles ; 65 restent à examiner. Les références silver sont issues des mêmes formulations et hypothèses de section : leur concordance mesure la reproduction de cette politique, pas la précision sur de nouvelles motos.

| Méthode | Concordance silver par fiche |
|---|---:|
| Règles du POC | 764/815 (93.7 %) |
| Jev | 813/815 (99.8 %) |
| Mistral | 811/815 (99.5 %) |
| Cascade | 811/815 (99.5 %) |

## Appels, délais et coût

| Étape de la cascade | Entrées distinctes | Décisions de fiches |
|---|---:|---:|
| code_no_mention | 168 | 200 |
| jev | 141 | 579 |
| mistral_fallback | 32 | 101 |

Le benchmark a réellement obtenu **341 décisions API Jev et 341 décisions Mistral locales distinctes** pour comparer les méthodes sur le même lot. La cascade réutilise ces résultats : ses seuls cas de repli représentent 32 entrées distinctes et 101 fiches. Ce n’est pas une mesure d’un nouveau traitement API de la cascade.

Taux de repli local : **32/341 (9.4 %)** sur toutes les entrées, et **32/173 (18.5 %)** sur les seules entrées avec mention d’équipement. Les 168 entrées distinctes sans mention sont traitables en code ; leur économie ne doit pas être attribuée à Jev.

Coût Jev de classification rapporté par l’API : **0.011296 USD** (0 coût(s) absent(s)). Les appels de routage et de validation de passages sont comptés séparément ci-dessous. Le calcul local n’a pas de facture API mesurée ; consommation électrique et coût matériel ne sont pas évalués.

| Classification | Médiane d’un appel | P95 | Somme des durées d’appels |
|---|---:|---:|---:|
| Jev | 0.316 s | 0.499 s | 120.1 s |
| Mistral | 1.517 s | 2.057 s | 558.5 s |

Jev a été appelé avec quatre requêtes concurrentes ; Mistral séquentiellement. La somme des durées n’est donc pas une durée murale comparable. Chargements froids, ordre des appels et reprises depuis cache sont conservés dans les sorties, sans répétitions permettant d’estimer la variabilité.

## Questions : boucle actuelle et pipeline hybride

24 questions exécutées sur les mêmes fiches figées. La boucle actuelle est son vrai agent Ollama avec un adaptateur SQLite isolé conservant ses arguments d’outils ; ce n’est pas une mesure sur le PostgreSQL de production. Les fiches détaillées de l’adaptateur transmettent les labels source et les sections, et peuvent être plus volumineuses que les fiches de production. Pour les listes, la projection limitée aux mesures de l’outil original est appliquée. Les filtres numériques/catégories non normalisés dans ce snapshot sont exclus du test. Le pipeline hybride répond en preuves structurées pour les cas simples et utilise Mistral pour les synthèses.

| Méthode | Médiane backend | P95 backend | Appels génératifs locaux | Appels Jev |
|---|---:|---:|---:|---:|
| Boucle actuelle | 31.324 s | 39.438 s | 44 | 0 |
| Hybride | 0.448 s | 53.884 s | 3 | 30 |

Routage conforme : **24/24**. Coût API de routage et validation de passages : **0.000740 USD**, avec 0 coût(s) absent(s). Les références de routes ne sont pas fournies aux modèles.

Les deux parcours reçoivent les mêmes questions avec millésime explicite. La boucle actuelle utilise son contexte habituel de 16 384 tokens ; les synthèses hybrides utilisent 4 096 tokens et un plafond de 400 tokens de sortie. Ces paramètres et les réponses structurées plus courtes contribuent aux différences de durée.

Les durées backend hybrides utilisent des vecteurs de questions préparés. Elles excluent leur encodage. Pour les seules branches BGE, l’encodage local chaud mesuré séparément doit être ajouté ; les branches SQL n’en ont pas besoin.

Une première série avec années isolées a déclenché le refus prévu par l’extracteur prudent de la boucle actuelle. Elle est conservée dans `queries-bare-year-v1.json` et `legacy-bare-year-regression.json`, hors de cette comparaison. La série finale précise le millésime pour les deux parcours ; cette correction ne change pas les références de classification. Les deux parcours partagent désormais l’extracteur prudent d’années de production ; la résolution hybride des noms reste un appariement exact, pas une capacité démontrée de Jev.

Branches BGE : 6 questions ; médiane backend + encodage chaud mesuré séparément **0.841 s**. Il s’agit d’une addition diagnostique, pas d’une nouvelle mesure de bout en bout.

| Question | Route attendue | Route hybride | Preuve cible retrouvée dans l’hybride |
|---|---|---|---|
| passage-0-0 | passage | passage | section cible présente |
| passage-0-1 | passage | passage | section cible présente |
| passage-1-0 | passage | passage | section cible présente |
| passage-1-1 | passage | passage | section cible présente |
| passage-2-0 | passage | passage | section cible présente |
| passage-2-1 | passage | passage | section cible présente |
| passage-3-0 | passage | passage | section cible présente |
| passage-3-1 | passage | passage | section cible présente |
| passage-4-0 | passage | passage | section cible présente |
| passage-4-1 | passage | passage | section cible présente |
| passage-5-0 | passage | passage | section cible présente |
| passage-5-1 | passage | passage | section cible présente |
| abs-2000 | sql_list | sql_list | non évaluée indépendamment |
| abs-2004 | sql_list | sql_list | non évaluée indépendamment |
| abs-2008 | sql_list | sql_list | non évaluée indépendamment |
| abs-2010 | sql_list | sql_list | non évaluée indépendamment |
| brand-Honda-2000 | sql_list | sql_list | non évaluée indépendamment |
| brand-BMW-2008 | sql_list | sql_list | non évaluée indépendamment |
| complex-2000 | complex | complex | non évaluée indépendamment |
| complex-2008 | complex | complex | non évaluée indépendamment |
| semantic-0 | passage | passage | aucun passage retenu ; synthèse de repli à auditer |
| semantic-1 | passage | passage | section cible présente |
| semantic-2 | passage | passage | section cible présente |
| semantic-3 | passage | passage | section cible présente |

La présence de la section cible ne valide pas chaque valeur ou phrase d’une réponse. Une synthèse après rejet de tous les candidats doit être auditée séparément : le repli ne démontre pas la réussite de la recherche. Les listes d’ABS sont construites avec les décisions de la cascade : leur exhaustivité SQL ne doit pas être présentée comme une exactitude indépendante de leurs équipements. Les noms complets et années explicites facilitent la résolution d’identité ; les erreurs de saisie, noms courts, marchés et variantes ambiguës restent hors de ce test.

## Audit des réponses : erreurs et utilité de Mistral

Un agent a comparé les 48 réponses aux textes et URLs du snapshot, sans appel à un modèle de notation. Cette revue établit la conformité aux extraits recueillis, pas la vérité constructeur. L’audit détaillé est conservé dans `query-answer-audit.json`.

- **16 questions factuelles :** valeurs et sources conformes dans les deux parcours. L’hybride répond directement dans 15 cas et récupère le dernier avec Mistral après abstention de Jev.
- **Listes par marque :** la boucle actuelle affiche 10 Honda sur 26 et 10 BMW sur 15 sans annoncer que les listes sont partielles. La liste Honda omet les URLs demandées. SQL rend les 26 et 15 identités avec leurs sources.
- **Listes ABS :** la boucle actuelle explique que le filtre est indisponible, sans inventer de réponse. L’hybride rend 2, 9, 19 et 39 fiches pour 2000, 2004, 2008 et 2010 ; leurs mentions d’ABS et URLs sont présentes. Cela ne valide pas un équipement de série pour toutes les variantes.
- **Deux comparaisons :** la boucle actuelle produit seulement un début d’en-tête avec des espaces, sans valeurs ni sources. L’hybride recopie des valeurs documentées mais ses deux réponses sont coupées : Ollama indique `done_reason=length`, 400 tokens. La seconde suppose aussi une meilleure stabilité à partir du débattement seul ; cette conséquence n’est pas étayée par les fiches.

Les statuts ABS restent un point de données à résoudre. Le repli Mistral interprète « ABS déconnectable sur demande » comme une option alors que la référence figée le classe en série. Les listes 2008 et 2010 perdent ainsi une fiche chacune par rapport à la politique silver. Cette divergence ne prouve pas l’équipement réel. Pour la Mana 850 NA et la Shiver 750 GT 2010, l’équipement annonce ABS tandis que les tarifs distinguent une version avec ABS : la portée de variante reste ambiguë malgré la concordance silver.

**Une collaboration BGE–Jev observée :** pour la suspension avant de la R6, BGE classe le train arrière en premier et le train avant en deuxième. Jev rejette l’arrière (score 0,20), conserve l’avant (0,86) et fournit la preuve correcte sans Mistral.

**Un repli Mistral utile :** pour la transmission de la FZ1, BGE ne propose pas le bon passage dans ses trois candidats. Jev les rejette tous ; Mistral lit la fiche complète sélectionnée par SQL et répond « boîte à 6 rapports, secondaire par chaîne » avec la bonne URL, en 17,8 s. Ce repli réussit, contrairement aux deux synthèses longues encore incomplètes.

Le seuil Jev ne garantit pas que le repli soit meilleur : sur le classement d’équipements, la cascade corrige l’inférence non étayée du texte « ASB » mais dégrade le cas « ABS déconnectable sur demande ». Elle conserve 54/60 accords, comme Mistral et Jev seuls. Les quatre désaccords sur les options groupées restent des conflits de politique de portée, inclus dans le score strict.

## Recherche BGE-M3

19 901 passages indexés  3 952 textes distincts  dimension 1024  calcul CPU local ; préparation mesurée 227.4 s et 0 texte tronqué.

| Recherche — 60 questions de sections source | Rappel @1 | Rappel @3 |
|---|---:|---:|
| scoped | 66.7 % | 88.3 % |
| unscoped | 1.7 % | 1.7 % |

Le filtre exact modèle–millésime est fourni avant la recherche filtrée : son identité correcte est imposée par SQL, pas démontrée par BGE. La recherche sans filtre n’indexe pas les noms dans les textes des sections ; elle sert à illustrer le besoin de portée et ne mesure pas un moteur complet de résolution d’identité.

## Conclusions autorisées et limites

Ce lot permet d’observer les accords, erreurs et besoins de repli sur des fiches réelles ; il ne prouve pas une précision générale de Jev sur toutes les motos. Le score test repose sur 37 références sélectionnées et seulement une absence explicite. Les 880 décisions sont corrélées et les références silver ne remplacent pas des annotations indépendantes.

Les requêtes SQL apportent une sélection exhaustive dans le catalogue figé, sous réserve de la qualité des champs. BGE apporte les passages techniques dans la bonne portée. Jev apporte la classification et le routage ; Mistral fournit les synthèses et les replis. Un gain de vitesse sur une réponse structurée ne garantit pas une meilleure réponse conversationnelle.

Avant généralisation : fixer la politique des listes d’équipements, conserver l’abstention sur les sources ambiguës, ajouter des annotations humaines indépendantes et tester des questions non templatisées. Les probabilités Jev et seuils de la cascade n’ont pas été calibrés sur une population représentative.

## Artefacts reproductibles

- `data/technical/hybrid-poc/benchmark-protocol.json` : modèles, consignes, paramètres et empreintes.
- `dataset.json`, `cases.json`, `gold_annotations.json`, `annotation_protocol.json` : lot et références figés.
- `jev-classifications.json`, `mistral-classifications.json`, `cascade-decisions.json` : sorties et coûts par entrée.
- `queries.json`, `legacy-query-results.json`, `hybrid-query-results.json` : questions et résultats des deux parcours.
- `index.retrieval-evaluation.json`, `index.embeddings.json`, `query-encoding-profile.json` : preuves de recherche et encodage.

Rapport généré le 2026-10-10T21:45:58.010253+00:00 ; aucune référence n’a été réétiquetée.

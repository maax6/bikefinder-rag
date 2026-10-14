# Outils SQL et RAG et comparaison des modèles

Le nouveau bot doit permettre de consulter le catalogue de motos en langage naturel : trouver des modèles, filtrer, compter, comparer et explorer les fiches et leurs millésimes. Le choix local ou cloud sera fait sur les mêmes données et les mêmes outils. Le contrat ci-dessous définit le nouveau parcours ; il n'est pas encore raccordé au chat.

## Base de la comparaison

Le lot utilise le snapshot enrichi Motoplanète du 12 octobre, ouvert en lecture seule. Ses empreintes et celles de l'index préparé sont enregistrées dans le [protocole](../eval_results/technical/sql-rag-comparison-20261014/protocol.json). Les sources constructeurs acquises pour les expériences précédentes ne font pas partie de cette première comparaison : chaque candidat dispose du même corpus.

SQL sert les chiffres, filtres, comptes et identités. La recherche de passages sert les explications techniques. Les textes originaux, variantes, millésimes et URL restent liés aux résultats. L'enrichissement se fait avant les requêtes du chat, avec des valeurs numériques reliées aux lignes sources.

## Six outils communs

Les schémas exploitables sont dans [tools.json](../eval_results/technical/sql-rag-comparison-20261014/tools.json). Ils sont indépendants du fournisseur de modèle.

| Outil | Entrée principale | Résultat |
|---|---|---|
| `describe_catalog` | Aucun argument | Champs et unités, couverture, sections, noms canoniques des équipements, contraintes prises en charge |
| `resolve_models` | Texte du modèle ou de la famille, périmètre facultatif, pagination | Identifiants réels des fiches, variantes, années, sources, nombre total de candidats et ambiguïtés |
| `query_catalog` | Périmètre, plusieurs critères numériques et d'équipement, compte ou liste, tri et pagination | Compte exact ou fiches correspondantes ; chiffres avec preuves ; valeurs inconnues exclues des comparaisons ; critères et témoin du calcul |
| `get_fiches` | Un à cinq identifiants, champs, sections et équipements souhaités | Valeurs, lignes originales, statuts des équipements, passages et références de chaque fiche |
| `compare_fiches` | Deux à cinq identifiants et caractéristiques | Tableau comparable, écarts calculés, preuves et inconnus par fiche |
| `search_passages` | Question, périmètre facultatif, mode hybride ou littéral, sections et ordre | Passages originaux avec identité, sources et couverture de recherche |

Le modèle reçoit les descriptions et schémas d'entrée. Les propriétés `semantics` et le reste du contrat servent à construire le service et ses contrôles ; l'adaptateur ne les transmet pas comme paramètres d'une fonction fournisseur.

### Identité et périmètre

L'année reste facultative pour chercher une famille ou ses millésimes. Une lecture précise et une comparaison utilisent ensuite les identifiants obtenus dans la base. Une recherche de Z 650 peut trouver plusieurs variantes ; le service les présente séparément. Il ne transforme pas une édition inconnue en modèle standard.

Un périmètre combine marque, mots discriminants du modèle, bornes d'année et éventuellement identifiants de fiches. Tous les critères fournis s'appliquent ensemble. Sans périmètre, une recherche concerne tout le catalogue. Le service retourne explicitement toute portion non examinée.

### Chiffres et équipements

Les champs initiaux sont la cylindrée, la puissance en ch, le couple en Nm, la hauteur de selle, le poids à sec, le poids en ordre de marche, l'autonomie et le prix de catalogue daté en euros. Une plage ou des valeurs contradictoires restent lisibles dans le texte source mais ne deviennent pas arbitrairement un chiffre comparable.

Les critères numériques et d'équipement sont combinés avec AND. Les statuts sont `standard`, `optional`, `explicitly_absent` et `unknown`. Une ligne absente ne prouve pas une absence d'équipement. Les noms canoniques proviennent de `describe_catalog`; un synonyme ambigu demande une résolution explicite.

Un compte porte sur toutes les fiches correspondantes, variantes comprises. Une liste fournit son total, sa page et un curseur lié aux critères, au tri et à l'empreinte du corpus. La taille par défaut est vingt fiches, au maximum cinquante par page. Ce maximum limite l'affichage, pas les connaissances du bot.

Les catégories de conduite, marchés techniques, prix d'occasion actuels et homologation d'un exemplaire ne sont pas des filtres établis dans cette version. Une contrainte indisponible est signalée et ne disparaît pas silencieusement de la demande.

### Recherche des passages

Le mode hybride associe le classement lexical BM25 et BGE-M3 local, avec la même configuration pour tous les candidats. Le périmètre est appliqué avant le classement. La première configuration propose quarante candidats par méthode, une fusion RRF avec k de 60 et huit passages retournés par défaut, vingt au maximum. Le reranking sera une expérience ultérieure distincte.

Le mode littéral parcourt exhaustivement le périmètre pour des mots ou expressions explicitement fournis. Il permet de paginer les résultats et de les ordonner par millésime. Le cas historique du lot demande la première mention DCT dans les transmissions des Gold Wing du snapshot. Cela établit un premier millésime documenté pour ces termes et ce périmètre, pas une date officielle de lancement.

Les passages classés par similarité ne suffisent pas à établir une première occurrence. Une recherche infructueuse ou une absence de mention reste une limite des données ou de la recherche, jamais une preuve d'absence.

### Réponses des outils

Chaque réponse fournit un statut, l'identifiant du snapshot, les résultats, les preuves, la couverture, les informations manquantes, la pagination et le temps d'exécution. Les preuves d'un compte conservent les critères SQL et l'accès aux fiches contributrices ; une URL isolée ne suffit pas à prouver un total.

Le service valide les types, bornes, champs, années, valeurs finies et noms d'équipements avant toute opération. Le modèle ne reçoit pas de SQL libre, d'écriture en base ou d'accès au Web. Les textes des fiches sont des données et ne peuvent pas modifier les règles d'exécution.

## Lot commun de quarante cas

Le [lot de questions](../eval_results/technical/sql-rag-comparison-20261014/questions.json) couvre :

| Tâche | Cas |
|---|---:|
| Comptes avec critères simples ou combinés | 8 |
| Consultation précise d'une fiche | 8 |
| Comparaisons numériques | 6 |
| Explications par passages, dont recherche chronologique | 6 |
| Découverte des variantes et millésimes | 4 |
| Données manquantes et ambiguïtés | 4 |
| Conversations et pagination à plusieurs tours | 4 |

Les quarante cas représentent quarante-quatre tours utilisateur. Vingt-quatre cas servent au développement et seize sont réservés à l'évaluation après gel de l'implémentation. Ce découpage est interne : l'auteur a préparé les deux ensembles. Il ne constitue pas un panel indépendant de généralisation.

Les [références locales](../eval_results/technical/sql-rag-comparison-20261014/references.private.json) contiennent les comptes, identités, valeurs, sources et critères de relecture. Elles n'entrent jamais dans le contexte des modèles. Le suffixe `private` indique leur rôle, pas un contrôle d'accès au fichier. Seuls le prompt, les schémas d'outils et [model-inputs.json](../eval_results/technical/sql-rag-comparison-20261014/model-inputs.json) sont autorisés comme entrées.

Les comptes sont préparés par une sélection SQL séparée sur le snapshot. Les valeurs numériques réutilisent le parseur existant `project()` ; leur référence n'est donc pas indépendante de ce parseur. Les lignes sources originales sont conservées pour la vérification humaine, notamment les plages, conflits et qualifications. Les explications nécessitent une relecture du sens des affirmations, en plus de la vérification des sources.

## Candidats local et cloud

| Parcours | Candidats initiaux | Conditions |
|---|---|---|
| Local | Qwen3.5 9B et Ministral 3 8B via Ollama | Modèles sous Apache 2.0 ; mesurer mémoire, quantification et latence sur le Mac |
| Cloud | GPT-6 Luna et Gemini 3.8 Flash | Vérifier accès du compte, fonctionnalités, quotas et tarifs avant exécution ; mesurer coût réel |
| Référence facultative | Claude Sonnet 5.5 | Expérience supplémentaire si les résultats justifient un modèle plus puissant |

Sources des candidats : [Qwen](https://huggingface.co/Qwen/Qwen3.5-9B), [Mistral](https://mistral.ai/news/mistral-3/), [OpenAI](https://developers.openai.com/api/docs/guides/latest-model), [Google](https://ai.google.dev/gemini-api/docs/models), [Anthropic](https://platform.claude.com/docs/en/models/overview).

Ce tableau décrit les candidats envisagés lors de la préparation. Les essais locaux ont depuis vérifié Qwen3.5 **4B**, réellement installé, et Ministral 3 8B ; ils ne constituent pas encore la comparaison locale complète. Le panel cloud a été élargi à huit modèles via OpenRouter. Les résultats observés sont présentés dans le [benchmark HTML](../eval_results/technical/sql-rag-cheap-models-20261014/benchmark.html), avec leurs identifiants exacts et leurs réglages.

Une variante de taille, un autre runtime comme MLX ou un autre niveau de quantification constitue un candidat distinct. Les identifiants exacts, empreintes des modèles locaux, réglages de raisonnement et versions seront gelés avant les essais. La base reste locale ; le parcours cloud transmet au fournisseur les questions et les résultats d'outils utiles à la réponse.

## Protocole de décision

La comparaison principale mesure le parcours complet : compréhension, choix des outils, consultation et rédaction. Les outils sont identiques, mais les appels choisis par les modèles peuvent différer. Une comparaison secondaire peut imposer le même dossier de preuves à tous les rédacteurs ; elle mesure seulement la rédaction et sera présentée séparément.

Le protocole initial, conservé comme référence historique de la première passe, limite chaque tour utilisateur à quatre étapes de modèle, huit appels d'outil, trente secondes et 1 200 tokens de sortie par appel. Le budget cumulé des résultats d'outils est de 32 000 caractères, avec réduction déterministe, annoncée et enregistrée. La seconde passe du paquet v5 porte les étapes à six et la sortie à 2 400 tokens ; ses autres limites et ses résultats sont détaillés ci-dessous. L'objectif produit reste cinq secondes pour les demandes simples et dix pour les recherches complexes ; trente secondes est un plafond d'expérience, pas la cible de rapidité.

Trois répétitions par cas et par candidat sont planifiées, soit 480 sessions et 528 tours utilisateur. L'ordre des cas est commun et celui des candidats est alterné avec une graine enregistrée. Chaque cas ouvre une conversation neuve ; ses tours partagent leur contexte. Les démarrages à froid et préchargements sont mesurés séparément. Aucun résultat de question ou réponse ne sera réutilisé en cache. Les vecteurs de documents préparés sont partagés.

La comparaison complète planifiée prévoit une relecture avec les étiquettes des candidats masquées. Les deux panels cloud exécutés ci-dessous ont été relus par des assistants avec les identifiants des modèles visibles ; ils ne constituent pas une évaluation aveugle. Les contrôles exacts couvrent comptes, identités, chiffres et références ; la relecture couvre le soutien réel de chaque affirmation et la réponse à toutes les parties de la demande. Une clarification justifiée peut réussir un cas ambigu ; elle ne remplace pas une réponse disponible à une question résoluble.

Le rapport présentera par type de tâche : taux de réponses correctes et complètes, taux de réponses utiles dans le délai cible, temps total médian et p95, erreurs et délais dépassés, nombre d'appels, coût par réponse réussie et mémoire locale. Le premier texte affiché ne sera pas présenté comme une réponse utile sans vérification. Une mesure indisponible reste `null`, jamais zéro.

Les seuils d'acceptation de qualité et le budget cloud seront fixés avant les appels payants. Les premières exécutions, échecs et corrections resteront distincts. Trois répétitions mesurent une variabilité limitée et ne constituent pas une démonstration de fiabilité générale ou de charge multiutilisateur.

## Préparation et prochaine exécution

Le paquet est gelé avec ses empreintes dans [manifest.json](../eval_results/technical/sql-rag-comparison-20261014/manifest.json). La préparation conserve les sources et produit un répertoire neuf ; elle refuse d'écraser un paquet existant.

```bash
PYTHONPATH=src .venv/bin/python scripts/prepare_sql_rag_comparison.py --out /private/tmp/bikefinder-comparison-new
PYTHONPATH=src .venv/bin/python scripts/check_sql_rag_comparison.py --pack /private/tmp/bikefinder-comparison-new
```

Le service autonome des six outils, les adaptateurs fournisseurs et l'enregistrement des réponses sont implémentés. La [vérification sur la base réelle](../eval_results/technical/sql-rag-service-20261014/service-verification-v2-final.json) couvre les quarante cas et valide les 105 687 passages de l'index contre le snapshot. Le chat actif reste un parcours distinct.

## Deux passes cloud exécutées

Les deux passes testent les mêmes huit modèles via OpenRouter sur les mêmes huit cas de développement : Q01, Q10, Q17, Q24, Q27, Q31, Q34 et Q37. Chaque passe contient une seule exécution par couple modèle/cas, soit 64 sessions et 72 tours utilisateur attendus, y compris les tours non exécutés après un échec. Les questions, le snapshot et les références d'évaluation restent identiques. Elles ne remplacent pas la comparaison locale complète ni le lot de quarante cas avec répétitions et cas réservés.

| Limite ou traitement | Passe 1 : paquet v4 | Passe 2 : paquet v5 |
|---|---|---|
| Étapes de modèle par tour utilisateur | 4 | 6, dernière étape réservée à la réponse |
| Appels aux six outils du catalogue par tour | 8 au maximum | 8 au maximum |
| Délai par tour | 30 secondes | 30 secondes |
| Sortie maximale par appel | 1 200 tokens | 2 400 tokens |
| Résultats d'outils cumulés dans le contexte | 32 000 caractères | 32 000 caractères ; plafond de 24 000 par résultat |
| Présentation des preuves | Résultats avec réduction déterministe annoncée | Vue compacte : identités et sources partagées, textes dupliqués référencés, preuves et qualifications conservées ; compression des échanges anciens annoncée |
| Réparation de format finale | Aucun nouvel essai correctif | Une au maximum, dans les mêmes plafonds d'étapes et de temps ; une référence inventée reste rejetée |

La seconde passe normalise aussi la casse, les accents et les espaces des sections et équipements enregistrés, avec des alias explicites de Quickshifter vers `shifter`. Les erreurs d'arguments proposent des corrections. La mention « standard » ne résout un modèle que lorsque sa désignation complète correspond exactement à la fiche de base ; une variante inconnue n'est pas remplacée. Ces améliorations sont générales, sans traitement particulier des identifiants des questions. Elles sont implémentées dans le service autonome et **ne sont pas encore raccordées au chat**.

Les [réponses de la passe 1](../eval_results/technical/sql-rag-cheap-models-20261014/pilot-v2.json) proviennent du [paquet v4](../eval_results/technical/sql-rag-comparison-20261014-v4/manifest.json), celles de la [passe 2](../eval_results/technical/sql-rag-cheap-models-20261014/pilot-v3.json) du [paquet v5](../eval_results/technical/sql-rag-comparison-20261014-v5/manifest.json). Le [benchmark HTML commun](../eval_results/technical/sql-rag-cheap-models-20261014/benchmark.html) compare les deux passes, leurs réponses, preuves, latences et coûts ; le [HTML de la première passe](../eval_results/technical/sql-rag-cheap-models-20261014/benchmark-pass1.html) est conservé.

La [même grille](../eval_results/technical/sql-rag-cheap-models-20261014/rubric.json) distingue réponses correctes, partielles, incorrectes et échecs. Les [relectures de la passe 1](../eval_results/technical/sql-rag-cheap-models-20261014/semantic-review.json) et de la [passe 2](../eval_results/technical/sql-rag-cheap-models-20261014/semantic-review-v3.json) couvrent chacune les 72 tours attendus. Elles ont été faites par des assistants, sans masquer les modèles. Un cas à deux tours ne réussit entièrement que si ses deux réponses sont correctes ; un tour manquant reste un échec. Les erreurs d'outils, de fournisseur et de format restent distinctes des affirmations factuellement fausses. Un chiffre attendu et une référence valide ne suffisent pas à prouver le soutien réel de l'affirmation.

| Résultat observé | Passe 1 | Passe 2 |
|---|---:|---:|
| Cas entièrement corrects | 26 / 64 (40,63 %) | 34 / 64 (53,13 %) |
| Score de qualité sur les 72 tours attendus, correct = 2 et partiel = 1 | 37,50 % | 52,78 % |

Le gain observé est de huit cas entièrement corrects, soit 12,5 points. Il comprend aussi des régressions et des erreurs sémantiques malgré des réponses finalisées. Une seule exécution par cas ne permet pas d'attribuer chaque différence au changement de service plutôt qu'au choix des appels, à la variabilité du modèle ou à la disponibilité du fournisseur. La [vérification de comparaison](../eval_results/technical/sql-rag-cheap-models-20261014/verification-v3.json) lie les rapports et relectures à leurs empreintes et contrôle les questions, les modèles, le corpus et les budgets ; la [vérification du service sur la base réelle](../eval_results/technical/sql-rag-cheap-models-20261014/service-verification-v3.json) conserve les contrôles des quarante cas et de l'index.

La première passe dispose d'un plafond de **2 $ pour les entrées**, partagé avec ses appels de préparation déjà effectués. La seconde utilise un **nouveau plafond indépendant de 2 $ pour les entrées** : son débit conservateur est de **0,76056756 $**, réservations incertaines comprises. Son coût connu retourné par l'API est de **0,153296733 $**, entrées et sorties comprises ; dix requêtes n'ont pas de coût total retourné, donc ce montant connu ne constitue pas une facture définitive. Les [consommations et réservations détaillées](../eval_results/technical/sql-rag-cheap-models-20261014/pilot-v3.json) restent enregistrées avant et après chaque requête. Les sorties sont suivies séparément et un appel interrompu sans consommation retournée conserve sa réservation d'entrée.

Le raisonnement reste désactivé lorsqu'il est facultatif ; Gemini 3.8 Flash utilise `low` et Gemini 3.5 Flash-Lite `minimal`, niveaux minimaux imposés par ces modèles. Les paramètres sont enregistrés dans chaque protocole. La [tentative initiale incompatible avec ces contraintes](../eval_results/technical/sql-rag-cheap-models-20261014/pilot-v1.json) est conservée hors classement.

## Corrections vérifiées après la deuxième passe

L'[analyse des échecs restants](sql-rag-remaining-failures-20261014.md) distingue les erreurs des outils et du contexte des erreurs de réponse et de fournisseur. Les périmètres contenant un identifiant inconnu sont désormais rejetés avant tout comptage ; la recherche de famille conserve les frontières de mots. Les identités restent lisibles près des identifiants, les passages d'équipement réellement livrés deviennent explicitement citables, et les preuves d'identité restent limitées à l'identité. Une confusion entre identifiant de fiche connu et identifiant de preuve peut recevoir une seule correction de format, dans les mêmes budgets, sans conversion automatique ni acceptation de référence inventée.

Les listes trop larges réduisent d'abord des colonnes numériques secondaires, uniformément et avec les noms des colonnes omises, avant de retirer des fiches. Les critères, champs de tri et mesures déjà citées sont protégés ; le périmètre de la page reste réutilisable. La version de présentation est `catalogue-compact-v2`, toujours sous les plafonds de 24 000 caractères par résultat et 32 000 cumulés.

La [vérification des six outils](../eval_results/technical/sql-rag-cheap-models-20261014/post-pass2-service-verification.json) couvre les quarante cas et les 105 687 passages de l'index. Le [rejeu des régressions](../eval_results/technical/sql-rag-cheap-models-20261014/post-pass2-regression-checks.json) vérifie notamment le périmètre erroné de Luna, les preuves sources et la liste complète de huit motos de Qwen. Aucun nouvel appel cloud n'a été effectué : les scores des deux passes historiques restent inchangés. Ces corrections concernent le service autonome ; leur comportement avec de nouvelles réponses des modèles reste à mesurer.

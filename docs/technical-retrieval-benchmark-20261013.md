# Benchmark de recherche technique — 13 octobre 2026

**BGE-M3 est une base crédible pour le prochain raccordement : il retrouve toutes les preuves requises dans cinq passages sur 40/44 cas lorsque les fiches sont données, en environ 17 ms. Le contrôle de l'identité est la priorité de confiance.** La recherche globale améliore l'exploration, mais peut confondre années et variantes. Le reranking améliore le premier résultat ; son gain de complétude dépend du nombre de passages conservés.

Travail de l'[issue #3](https://github.com/maax6/bikefinder-rag/issues/3), exécuté sur une copie correspondant au catalogue actif : **11 478 fiches, 411 954 lignes techniques, 105 687 passages**. Aucune API d'inférence du projet appelée, y compris Jev ; Jev reste le seul service distant autorisé. Le chat actif et sa base n'ont pas été modifiés par ce benchmark.

## Comparaison sur les questions réservées

50 nouvelles questions, dont **34 répondables, 10 partielles et 6 hors couverture**. Les chiffres de pertinence portent sur les **44 cas avec preuves annotées**. « Partiel » peut signifier une précision absente ou un verdict sur l'exemplaire impossible ; certains de ces cas restent entièrement répondables sur le contenu de la fiche.

« Preuve en tête » signifie qu'au moins un passage attendu est premier. « Toutes preuves @k » exige un passage suffisant pour **chaque fait demandé** dans les k premiers ; cette mesure est plus utile pour une réponse comprenant plusieurs faits. Un passage alternatif suffit pour son groupe. Le rappel mesure, lui, tous les passages annotés, y compris des preuves redondantes.

### Fiches déjà identifiées — portée fournie au benchmark

| Méthode | Preuve en tête | Toutes preuves @3 | @5 | @10 | Médiane | P95 |
|---|---:|---:|---:|---:|---:|---:|
| Mots-clés · BM25 | 20/44 | 13/44 | 19/44 | 37/44 | 0.4 ms | 0.7 ms |
| BGE-M3 | 40/44 | 33/44 | 40/44 | 44/44 | 16.7 ms | 18.9 ms |
| Hybride · RRF | 39/44 | 26/44 | 34/44 | 40/44 | 16.8 ms | 23.2 ms |
| Hybride + reranking | 44/44 | 34/44 | 41/44 | 43/44 | 130.2 ms | 253.6 ms |

La portée est correcte parce qu'elle est fournie par les annotations : **ce tableau ne mesure pas la résolution d'identité de Jev**. 33 des 44 cas ont une fiche de dix sections au maximum ; la couverture @10 est alors mécaniquement facile. Les rangs 1/3/5 sont plus discriminants.

BGE-M3 offre ici le meilleur compromis simple. Le reranking place une preuve pertinente en tête sur 44/44 et passe de 40 à 41 cas complets @5, pour environ huit fois la durée. L'hybride RRF fixé pour ce test dégrade plusieurs classements par rapport au dense : il n'est pas à activer systématiquement dans cette portée.

### Catalogue complet — aucun ID attendu injecté

| Méthode | Preuve en tête | Toutes preuves @3 | @5 | @10 | Médiane | P95 |
|---|---:|---:|---:|---:|---:|---:|
| Mots-clés · BM25 | 14/44 | 7/44 | 8/44 | 15/44 | 2.6 ms | 4.0 ms |
| BGE-M3 | 27/44 | 19/44 | 23/44 | 30/44 | 29.3 ms | 35.2 ms |
| Hybride · RRF | 32/44 | 17/44 | 21/44 | 30/44 | 32.1 ms | 38.3 ms |
| Hybride + reranking | 37/44 | 18/44 | 22/44 | 35/44 | 388.4 ms | 540.3 ms |

Le reranking augmente nettement la qualité du premier résultat et la couverture @10, pour environ douze fois la durée hybride. À cinq passages, l'écart 23/44 BGE contre 22/44 reranking est trop petit pour déclarer un modèle intrinsèquement supérieur. Les références globales ne sont pas exhaustives : ces scores décrivent les preuves connues, pas toute la pertinence possible dans le catalogue.

Les médianes et P95 comprennent **l'encodage réel de la question**, les recherches requises, la fusion et le reranking. Chaque méthode exécute son propre pipeline. 50 questions × 3 répétitions = 150 durées par méthode et portée ; pertinence sur le premier passage uniquement. Aucun cache de question ou résultat. Chargement et échauffement séparés ; cache système froid non revendiqué. Les six négatifs ont une portée vide dans l'expérience fournie : cette absence de candidats est donnée au banc, elle ne démontre aucune abstention du bot.

## Ce qui doit produire la confiance

- **Bonne identité avant utilisation.** Le premier résultat global reranké est hors du périmètre attendu dans 7/44 cas : quatre années différentes et trois variantes différentes. Ces intrusions ne signifient pas toutes un fait faux, mais deux cas changent les caractéristiques demandées. HOLDOUT-010 demande la R 1250 GS 2023 en excluant l'Adventure ; l'Adventure est première, avec une selle de 890–910 mm contre 850–870 mm. HOLDOUT-041 compare les Tracer GT/GT+ 2024 ; un passage 2025 avec boîte automatique est premier, alors que les fiches 2024 indiquent une transmission manuelle.
- **Toutes les preuves requises.** Les neuf échecs de complétude @10 du reranking global se divisent en trois pertes dans le pool de 30 candidats (036, 038, 039) et six preuves présentes dans ce pool mais reléguées hors du top 10 (005, 007, 008, 034, 037, 041). Un bon premier passage ne résout pas une comparaison comportant plusieurs faits.
- **Autorité adaptée à la demande.** Les quatre méthodes rendent dix candidats sur chacun des six négatifs globaux. Le certificat officiel A2 demandé en 045 reste absent malgré une mention Motoplanète classée première avec un score reranker voisin de 0,64. Aucun seuil d'abstention n'a été calibré ; aucun refus ni aucune hallucination de réponse n'est mesuré ici.
- **Qualificatifs et inconnus conservés.** Les 11 232 positions retournées du lot réservé correspondent exactement aux textes, identités, années, sections et URLs de l'index. Les mentions « en option », les bases de poids et les inconnus restent dans les passages. Leur compréhension et leur restitution par le générateur restent à valider.

Les listes sont identiques sur les trois répétitions pour toutes les méthodes. Cette répétabilité est vérifiée ; la confiance exige aussi les contrôles ci-dessus. Le taux de passages hors portée de référence dans le top 10 atteint environ 79 % pour le reranking global : **ce n'est pas un taux de réponses fausses**, notamment pour les alternatives ambiguës et les passages non jugés.

### Premier cas métier : A2

Six demandes A2 disposent de preuves dans les fiches. Toutes les preuves @5 sont retrouvées sur **6/6 avec BGE, hybride et reranking dans la portée fournie**, contre 0/6 en lexical. En global : BGE 2/6, hybride 2/6, reranking 1/6, lexical 0/6. Le reranking conserve pourtant un bon premier passage sur 6/6 : la complétude apporte une information que ce bon rang ne donne pas.

Le corpus ne contient pas de documents officiels A2 ni les certificats d'un exemplaire. Certaines fiches combinent une puissance native élevée et une mention générique « A2 ou bridable » : restituer cette tension, sans certifier un bridage ou une homologation. La recherche retrouve des assertions de la source ; elle ne vérifie pas leur vérité auprès du constructeur.

## Direction recommandée

1. **Jev interprète la demande ; le code résout et valide l'identité et les contraintes.** Modèle, millésime et exclusions de variante doivent borner les preuves. En cas d'ambiguïté, demander une précision ou présenter des candidats séparés.
2. **SQL conserve les filtres, comptes, valeurs et comparaisons structurées. BGE récupère les passages dans la portée autorisée.** Garder le reranking comme option à mesurer pour l'exploration globale ou les cas où le meilleur premier passage justifie son coût.
3. **La réponse dépend de la couverture et du type de source.** Compléter une recherche comportant plusieurs faits, ou signaler ce qui manque. Une mention commerciale ne satisfait pas une demande de certificat officiel.
4. **Brancher un adaptateur RAG au parcours Jev, puis mesurer les réponses finales sur un nouveau lot réservé.** Les 50 questions utilisées ici deviennent un lot de régression. A2 peut commencer par les mentions des fiches et les limites explicites, puis une extension documentaire distincte.

Cela permet d'exploiter des formulations nouvelles sans rédiger une réponse cible pour chacune. Le benchmark soutient cette voie d'accès aux connaissances ; il ne prouve pas encore la fiabilité du bot complet.

## Protocole et coûts

- Copie SQLite en lecture seule et index isolé. Identité/année + titre de section + texte source intégral pour les quatre méthodes ; aucun changement de découpage. IDs stables `object_id:section:indice_original`.
- BM25 local : k1=1,2 ; b=0,75 ; accents et casse normalisés ; codes de modèles, nombres, unités et négations conservés. Ce moteur n'est pas PostgreSQL FTS.
- BGE-M3 dense 1 024 dimensions, cosine exacte, vecteurs normalisés stockés float32. Fusion RRF=60 ; pool=30 ; reranking sur exactement les mêmes 30 candidats hybrides ; retour de dix passages. Longueur maximale 512 tokens. Aucun passage ni paire de question/passage tronqué (maximum documentaire 272 tokens).
- Inférence MPS float16, batch 32, choisis sur un profil de textes du corpus avant lecture des questions réservées. Accord cosine minimal float32/float16 de ce profil : 0,99977. Cela diffère du calcul float32 et du texte brut de l'encodeur actif.
- Modèles installés et chargés hors ligne : [BGE-M3, MIT](https://huggingface.co/BAAI/bge-m3), révision `5617a9f61b028005a4858fdac845db406aefb181` ; [bge-reranker-v2-m3, Apache-2.0](https://huggingface.co/BAAI/bge-reranker-v2-m3), révision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`. Configurations et poids empreintés et revérifiés avant chaque évaluation. Les seules lectures web du module concernent ces métadonnées de licence, sans données du corpus.
- Apple M5, 32 Go, macOS 27.0.1 ; Python 3.11.15, torch 2.13.0, sentence-transformers 5.6.0, transformers 5.13.0, NumPy 2.4.6. Révisions et fichiers réellement employés enregistrés, workspace initial modifié sur `f2118d5`.
- **Préparation : 942,98 s**, dont 913,11 s d'encodage et 2,86 s de BM25 ; artefacts principaux 528,46 Mo, dont 432,89 Mo de vecteurs. Aucun index ni poids de modèle versionné.
- Initialisation des processus réservés : 7,03 et 7,89 s, comprenant vérifications, lecture d'index et import/chargement ; chargement des deux modèles 2,67 et 2,85 s ; échauffement exclu 0,41 et 0,74 s. Processus neuf ; caches disque système non contrôlés.
- Pic RSS observé environ 1,84 Go ; mémoire MPS pilote échantillonnée environ 5,34 Go. Ne pas les additionner comme un maximum certifié de mémoire unifiée. Le swap était déjà présent, passant de 3 681 à 5 533 Mo affichés ; la machine et ses applications restent en fonctionnement. Pas de mesure de concurrence multi-utilisateur.
- Diagnostic distinct sur trois fiches de développement : encodage des sections brutes float32 avec longueur par défaut 8192, puis question et cosine en mémoire. Cache source supposé vide pour chaque fiche : 269–446 ms ; vecteurs source réutilisés, question réencodée : 21–23 ms. SQL, résolution d'identité et chat exclus ; aucune réutilisation de cache entre fiches. Ce diagnostic n'est pas une latence conversationnelle.
- Cache actif technique confirmé inchangé : seulement neuf textes déjà encodés, sur 22 139 textes distincts. Comptes et empreintes des fiches actives inchangés après exécution. La connexion RAG au chat reste un prochain module.

## Références, limites et vérifications

Auteur **IA indépendant et isolé**, depuis le corpus seul, sans lire le code ni les anciens lots ; pas de panel humain. Dix questions de développement et cinquante réservées, sans famille de modèle, fiche ou passage partagé entre lots. Les formulations réservées restent hors de la préparation du code et des paramètres ; empreintes figées avant le premier passage. Aucun ajustement aux scores, références ou paramètres après leur ouverture.

25 cas demandent plusieurs groupes de preuve ; 11 portent sur plusieurs fiches. Le lot réservé représente 41 fiches et 82 passages distincts : certaines questions partagent des preuves. Ce petit jeu contrôlé et ses jugements globaux incomplets ne fournissent ni garantie générale ni P95 robuste de tous les futurs usages. Un seuil d'abstention exigerait davantage de négatifs de développement et un nouveau test indépendant.

Deux revues indépendantes du code et du protocole ont conduit à corriger les contrôles de métriques et de provenance avant ouverture du réservé. **947 tests réussis, 8 tests d'intégration désactivés**. Les vérifications en lecture seule confirment les identités/empreintes sources et les comptes du catalogue actif après exécution. Aucun modèle de génération ni parcours conversationnel n'a été évalué.

### Rappel gradué et classement

| Portée | Méthode | Recall@1 | @3 | @5 | @10 | MRR@10 | nDCG@10 |
|---|---|---:|---:|---:|---:|---:|---:|
| Identité fournie | Mots-clés · BM25 | 0.309 | 0.449 | 0.604 | 0.922 | 0.603 | 0.637 |
| Identité fournie | BGE-M3 | 0.587 | 0.856 | 0.941 | 0.996 | 0.945 | 0.935 |
| Identité fournie | Hybride · RRF | 0.553 | 0.750 | 0.864 | 0.970 | 0.925 | 0.876 |
| Identité fournie | Hybride + reranking | 0.655 | 0.892 | 0.951 | 0.989 | 1.000 | 0.973 |
| Globale | Mots-clés · BM25 | 0.195 | 0.312 | 0.352 | 0.489 | 0.440 | 0.378 |
| Globale | BGE-M3 | 0.388 | 0.583 | 0.706 | 0.837 | 0.730 | 0.681 |
| Globale | Hybride · RRF | 0.422 | 0.587 | 0.676 | 0.811 | 0.804 | 0.695 |
| Globale | Hybride + reranking | 0.553 | 0.638 | 0.708 | 0.890 | 0.903 | 0.801 |

Les scores sont des moyennes par question avec preuves, et non par répétition. MRR est limité aux dix premiers. Aucune comparaison directe des scores bruts BM25/cosine/reranker.

### Reproduire et consulter

[Résultats et traces versionnables](../eval_results/technical/retrieval-benchmark-20261013/README.md) · [Harness](../scripts/benchmark_technical_retrieval.py) · [Tests](../tests/test_benchmark_technical_retrieval.py).

Les commandes et empreintes exactes sont dans ces artefacts. Utiliser un nouveau répertoire pour une nouvelle expérience ; `--resume` reprend uniquement une exécution interrompue avec les mêmes empreintes. Les résultats du premier passage ne sont pas écrasables. Les caches lourds restent dans `data/technical/retrieval-benchmark-20261013/`.

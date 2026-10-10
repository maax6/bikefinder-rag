# Recentrer le POC local sur un catalogue technique de motos par millésime

Document de cadrage du 10 octobre 2026, destiné à l'issue de refonte.

## Problème

Après la reprise du projet, l'essai de la démo a clarifié la priorité : choisir et comparer des motos à partir de leurs **caractéristiques techniques et performances**. Les avis des propriétaires ont pris trop de place dans la logique du POC. Ils pourront enrichir le produit plus tard, une fois le socle technique fiable.

Les questions centrales portent sur la puissance, le couple, la cylindrée, le poids, les équipements, les couleurs disponibles et l'histoire des modèles, sur une période de plus d'un siècle. Il faut pouvoir comparer un même millésime ou une plage d'années explicite, sans mélanger générations, variantes et marchés.

La démo doit rester un **proof of concept entièrement local**, utilisable sur un **Mac M5 avec 32 Go de mémoire unifiée**. L'essai « quelles motos avaient l'ABS en 2000 ? », puis une relance, ont rencontré des délais d'attente. Ces échecs ne démontrent pas que tous les commentaires sont envoyés au modèle : la recherche en sélectionne cinq par défaut. En revanche, les tours d'outils et l'historique peuvent accumuler du contexte, et les outils actuels ne savent pas rechercher proprement cet équipement dans tout le catalogue.

### État mesuré du catalogue local

Audit PostgreSQL en lecture seule le 10 octobre 2026 ; ces chiffres décrivent les données chargées, pas une couverture exhaustive du marché.

| Donnée | Fiches renseignées / présentes |
|---|---:|
| Fiches techniques | 32 395 |
| Millésimes distincts | 131, de 1894 à 2024 |
| Cylindrée normalisée | 31 885 |
| Poids normalisé | 28 781 |
| Puissance normalisée | 22 140 |
| Couple normalisé | 14 222 |
| Hauteur de selle normalisée | 20 732 |
| Couleurs brutes | 19 560, soit 60,4 % |
| Vitesse maximale brute | 10 846, soit 33,5 % |
| Freinage avant / arrière brut | 30 502 / 30 353 |

Les comptes de champs bruts excluent les valeurs vides et `Loading...`. Les 131 millésimes présents n'impliquent ni continuité de couverture, ni exhaustivité de chaque année. La collecte actuelle est bornée à 2025 dans le code ; le catalogue chargé s'arrête à 2024. L'extension jusqu'aux millésimes récents doit être explicite et contrôlée.

Les données présentent déjà des ambiguïtés importantes :

- L'année est celle du catalogue annuel. Aucun champ de lancement ou de période de production n'a été trouvé : le premier millésime observé ne prouve pas une date de sortie.
- Poids sec et poids tous pleins alimentent aujourd'hui le même champ normalisé. Les comparer directement ou en dériver un classement puissance/poids peut être trompeur.
- Les couleurs sont des chaînes libres : une liste de coloris et une livrée multicolore ne se découpent pas de la même façon.
- Certaines fiches regroupent plusieurs variantes. Une mention d'ABS peut décrire une option ou une autre variante ; un champ silencieux ne signifie pas « sans ABS ».
- La séparation marque/modèle au premier espace fragilise les marques composées. Le rattachement à une famille ne doit pas transférer les caractéristiques d'un millésime à un autre.
- Les catégories issues de plusieurs sources peuvent se contredire ; une comparaison doit rendre ces conflits visibles.

Dans l'architecture actuelle, les embeddings portent sur les avis. Les fiches techniques sont accessibles par les outils SQL et leurs champs bruts, mais n'ont pas d'index de passages techniques. Un commentaire entier correspond encore à une unité vectorisée ; limiter son extrait après recherche ne constitue pas un découpage avant embedding.

## Solution

Construire d'abord un catalogue technique traçable, avec une identité **marque → modèle → millésime → variante**, puis une interface de recherche et de comparaison qui répond à partir de ce catalogue. Les avis deviennent une extension désactivée dans le parcours technique par défaut.

Les filtres précis et les calculs comparatifs passent par des données structurées. Les passages techniques servent à rechercher et expliquer les informations textuelles non couvertes par ces filtres. Le modèle local choisit les outils et rédige la réponse à partir d'une sélection bornée de preuves ; il ne doit pas remplacer les données manquantes par ses connaissances générales.

Le changement de modèle sera évalué sur cette tâche réelle. Il ne remplace ni la correction du catalogue, ni les bons outils, ni la maîtrise du contexte.

## Parcours attendus

1. En tant qu'utilisateur, je veux rechercher les motos d'un millésime précis afin de comparer une même période.
2. En tant qu'utilisateur, je veux fixer une plage d'années afin d'explorer plus d'un siècle sans mélanger implicitement les époques.
3. En tant qu'utilisateur, je veux filtrer par cylindrée, puissance, couple et poids afin de sélectionner des motos selon des critères mesurables.
4. En tant qu'utilisateur, je veux comparer plusieurs modèles du même millésime afin de voir leurs différences techniques dans un tableau.
5. En tant qu'utilisateur, je veux connaître les unités et le type de poids afin de comparer des valeurs compatibles.
6. En tant qu'utilisateur, je veux consulter la vitesse maximale lorsqu'elle est documentée afin de disposer d'un critère supplémentaire sans inventer les valeurs absentes.
7. En tant qu'utilisateur, je veux distinguer performances annoncées et mesurées lorsque la source le permet afin de comprendre la portée des chiffres.
8. En tant qu'utilisateur, je veux savoir si l'ABS est de série, en option, explicitement absent ou inconnu afin de comprendre l'équipement réel d'une variante.
9. En tant qu'utilisateur, je veux rechercher un équipement sur toute une année afin d'obtenir les cas documentés et les limites de couverture.
10. En tant qu'utilisateur, je veux connaître les couleurs d'un modèle et d'un millésime afin de ne pas recevoir les coloris d'une autre génération.
11. En tant qu'utilisateur, je veux distinguer une livrée multicolore d'un choix entre plusieurs couleurs afin de comprendre les options disponibles.
12. En tant qu'utilisateur, je veux connaître la date de lancement lorsqu'une source la documente afin de la distinguer du premier millésime présent dans la base.
13. En tant qu'utilisateur, je veux distinguer variantes et marchés lorsqu'ils sont renseignés afin d'éviter une comparaison incohérente.
14. En tant qu'utilisateur, je veux accéder à la source de chaque caractéristique utilisée afin de vérifier la réponse.
15. En tant qu'utilisateur, je veux que les données inconnues et les conflits soient signalés afin de ne pas prendre une absence de donnée pour une absence d'équipement.
16. En tant qu'utilisateur, je veux pouvoir poser une question en français afin de consulter aussi les fiches issues de sources anglophones.
17. En tant qu'utilisateur, je veux recevoir une réponse technique sans avis de propriétaires afin de rester concentré sur les spécifications.
18. En tant qu'utilisateur, je veux des réponses locales avec un budget d'attente explicite afin de savoir quand réduire ou relancer une question.
19. En tant qu'utilisateur, je veux relancer une question échouée sans réinjecter ses traces d'outils incomplètes afin d'éviter une nouvelle accumulation de contexte.
20. En tant que mainteneur, je veux reprendre une collecte interrompue et identifier les fiches déjà traitées afin de compléter le catalogue sans doublons.
21. En tant que mainteneur, je veux mesurer la couverture par champ, millésime et source afin de cibler les collectes utiles.
22. En tant que mainteneur, je veux comparer les modèles sur les mêmes questions et preuves afin de choisir selon les résultats du POC.
23. En tant qu'auteur du futur article, je veux des résultats datés et reproductibles afin de distinguer ce qui fonctionne, ce qui a été mesuré et ce qui reste à améliorer.

## Décisions d'implémentation

### Catalogue et collecte

- Conserver les fiches brutes et introduire une normalisation versionnée. Une migration doit être vérifiable sur un échantillon avant tout réimport général ; conserver le corpus précédent jusqu'à validation.
- Définir des identifiants stables pour marque, modèle, millésime et variante. Traiter les marques composées et les identifiants numériques de modèles sans rapprochements approximatifs dangereux.
- Associer chaque valeur normalisée à sa valeur d'origine, son unité, sa nature, sa source et sa date de collecte. Ne pas inventer marché, variante ou date de lancement lorsqu'ils ne sont pas documentés.
- Séparer poids sec et poids tous pleins. Définir les conventions de puissance et de conversion avant tout calcul. Un rapport puissance/poids ne peut utiliser que des mesures compatibles et doit afficher sa formule.
- Modéliser les équipements avec les états « série », « option », « absence explicite » et « inconnu », ainsi que le passage justificatif et la variante concernée. Les repérages lexicaux seuls ne suffisent pas à classer une fiche.
- Conserver les libellés originaux des couleurs et distinguer choix et livrées. Leur rattachement est au millésime et, si connu, au marché et à la variante.
- Distinguer millésime, première apparition dans le corpus, lancement documenté et période de production documentée.
- Prioriser les fiches techniques manquantes et les champs utiles aux comparaisons. La collecte doit être reprenable, dédupliquée, avec concurrence bornée, cache et temporisation ; compléter les années récentes après vérification des pages disponibles et des conditions de chaque source. Aucun nouveau crawl massif n'est requis pour établir ce cadrage.

### Recherche et génération

- Garder PostgreSQL et les outils de lecture structurée comme socle pour les dates, limites numériques, tris et agrégations. Valider les arguments des outils et signaler les filtres non pris en charge au lieu de les ignorer silencieusement.
- Ajouter un contrat de recherche d'équipements et de couleurs, puis un contrat de comparaison. Les résultats doivent conserver identité, millésime, variante, unités, source et inconnues ; borner les listes et expliciter leur pagination et leur éventuelle non-exhaustivité.
- Construire un index distinct de passages **techniques**, découpés par sections cohérentes avant embedding. Conserver les métadonnées d'identité, millésime, source et version ; ne pas séparer une valeur de son unité, d'une note de variante ou de son qualificatif.
- Appliquer les contraintes de millésime et d'identité avant la sélection sémantique. Utiliser la recherche lexicale/vectorielle et le reranking lorsque le texte le justifie ; ne pas imposer de recherche vectorielle aux requêtes qu'un filtre structuré résout directement.
- Conserver BGE-M3 comme référence initiale. Remplacer seulement le modèle génératif ne nécessite pas de refaire les embeddings existants. Un nouveau corpus technique ou un nouveau découpage nécessite en revanche son propre index versionné.
- Exclure les avis du parcours technique par défaut, sans supprimer le corpus déjà collecté. Leur réintroduction sera une décision ultérieure avec une évaluation séparée.
- Borner les preuves envoyées au modèle et le contexte cumulé. Conserver les traces complètes pour le diagnostic, séparément de l'historique utile au dialogue. Ne jamais enregistrer un timeout comme une réponse réussie.
- Garder une configuration locale explicite et un fonctionnement hors ligne après installation des modèles. Les sources de scraping nécessitent le réseau pendant la collecte ; la consultation du corpus chargé doit pouvoir fonctionner sans API distante ni clé cloud.

### Modèles à comparer sur M5 / 32 Go

Sources officielles consultées le 10 octobre 2026. Le serveur Ollama local répond en version **0.32.15**. Les tailles suivantes sont celles des artefacts distribués ; elles ne représentent pas la mémoire totale en exécution.

| Candidat | Artefact annoncé | Place dans l'expérience |
|---|---:|---|
| Mistral Small 3.2 actuel | 24B, quantification locale Q4_K_M | Référence du POC, à conserver pour comparaison |
| [Gemma 4 12B MLX](https://ollama.com/library/gemma4:12b-mlx) | environ 7,7 Go | Premier candidat compact utilisant le moteur MLX d'Ollama sur Apple Silicon ; appels d'outils annoncés |
| [Ministral 3 14B](https://ollama.com/library/ministral-3:14b) | environ 9,1 Go, Q4_K_M | Second candidat compact ; français, appels d'outils et JSON annoncés |
| [Qwen 3.5 9B](https://ollama.com/library/qwen3.5:9b) | environ 6,6 à 7,6 Go selon moteur/artefact | Alternative compacte ; contrôler et enregistrer le mode de raisonnement |
| [Qwen 3.8 27B](https://ollama.com/library/qwen3.8:27b) | environ 18 Go | Comparaison secondaire seulement si la marge mémoire mesurée le permet |

Les [optimisations MLX et MTP publiées par Ollama](https://registry.ollama.com/blog/faster-gemma-4-mlx-mtp) justifient un essai, mais leurs gains de benchmark de programmation sur M5 Max ne prouvent aucun gain pour notre RAG sur M5.

[Mistral Large 4](https://docs.mistral.ai/models/mistral-large), annoncé le 6 octobre, possède 1 050 milliards de paramètres au total. Ses appels d'outils sont compatibles avec le principe de l'architecture, mais sa taille l'écarte d'un déploiement ordinaire sur ce Mac : à 4 bits, les seuls poids représenteraient de l'ordre de 525 Go avant surcoûts. Il s'agit d'une estimation de taille, pas d'une mesure d'exécution. L'[annonce officielle](https://mistral.ai/news/mistral-large-4/) présente actuellement une préversion API et prévoit les poids en fin de mois ; une API distante ne satisfait pas l'objectif local.

Ne sélectionner aucun gagnant avant mesure. Charger un seul modèle génératif à la fois ; compter aussi le contexte/KV cache, les embeddings, le reranker, PostgreSQL et macOS dans le budget mémoire. Vérifier au vrai contrat Ollama les appels d'outils, les arguments, les sorties finales et le traitement du raisonnement ; une étiquette « tools » n'est pas une validation du POC.

## Décisions de test

La validation principale se fait au niveau du comportement observable : **question → outils/données → réponse avec preuves**, en réutilisant les entrées existantes de l'agent et du chat. Les fixtures de scraping complètent cette validation pour la normalisation ; éviter des tests qui reproduisent seulement les détails internes du code.

### Jeu de référence technique

Constituer au moins vingt questions avec réponses ou preuves attendues, vérifiées manuellement sur les fiches conservées. Inclure :

- ABS en 2000 : citer uniquement les cas documentés, distinguer option et série, signaler les variantes regroupées et la couverture limitée. Sur les 323 fiches locales de 2000, une seule mentionne l'ABS dans les champs bruts ; cela ne signifie pas qu'une seule moto du marché en disposait.
- Couleurs d'un modèle et d'un millésime précis : conserver la livrée et ne pas emprunter les couleurs d'une autre année.
- Comparaison de puissance, couple et poids sur un même millésime : unités cohérentes, poids sec/tous pleins distingués, aucune valeur manquante complétée par le modèle.
- Classement puissance/poids : refuser ou limiter le classement lorsque les mesures ne sont pas comparables ; citer les opérandes de tout calcul.
- Date de sortie : répondre « non documentée » lorsque seule une première apparition dans le catalogue est disponible.
- Contraintes contradictoires, modèle ambigu, marque composée, variantes proches et aucune fiche correspondante.
- Question française sur données anglophones, sources contradictoires, équipement inconnu et résultat paginé.
- Timeout avant/après outil, relance, tours multiples et épuisement de budget : aucun historique incomplet réinjecté, aucun nouvel appel après détection de l'épuisement.

Les cas critiques doivent respecter toutes leurs contraintes et rattacher chaque caractéristique affirmative à une preuve. Une abstention justifiée est correcte ; une réponse fluide mais non sourcée ne l'est pas. Vérifier les résultats SQL séparément de la formulation du modèle pour localiser les erreurs.

### Mesures locales et reproductibilité

- Même corpus, mêmes questions, mêmes outils et même budget de contexte pour chaque modèle ; démarrer à 16 384 tokens, comme la configuration actuelle, plutôt qu'utiliser les fenêtres maximales annoncées.
- Mesurer démarrage à froid et réponses à chaud, au moins trois passages du jeu de référence, sans essai interactif ou modèle juge concurrent.
- Enregistrer durée totale, latence par opération, nombre d'appels, arguments invalides, preuves retenues, taille du contexte, timeouts, réussite des contraintes, valeurs non justifiées et abstentions correctes.
- Enregistrer pic mémoire, pression mémoire et variation de swap, en plus de la taille des poids. Fixer ensuite le seuil de latence acceptable à partir de mesures du M5 ; le budget d'attente configurable ne constitue pas une promesse de réponse dans ce délai.
- Rapports datés avec commit, version de schéma/normalisation, empreinte du corpus, modèle/digest, moteur, version d'Ollama, paramètres et mode de raisonnement. Ne pas réutiliser un cache d'une autre configuration.
- Rejouer les régressions de parsing, rapprochement de modèles, outils, état du chat et provenance. L'auto-retrieval vectoriel contrôle le câblage de l'index, pas la qualité de réponse technique.

## Étapes de refonte et critères d'acceptation

Chaque étape doit produire un petit commit vérifiable et une validation avant la suivante.

1. **Fixer la référence.** Sauvegarder l'état actuel, l'audit de couverture et les essais datés ; conserver les corpus existants. Critère : baseline reproductible et limites explicites.
2. **Livrer un premier parcours technique.** Retirer les avis des outils proposés par défaut et du discours de la démo ; répondre à une question de fiche et à une comparaison simple avec les données existantes et leurs inconnues. Critère : aucun avis utilisé pour affirmer une spécification.
3. **Fiabiliser identité et mesures.** Corriger marques composées, millésimes/variantes et poids ; définir les conversions et preuves par champ. Critère : fixtures représentatives et audit de migration sans mélange de modèles ni perte des valeurs brutes.
4. **Ajouter équipements et couleurs.** Normaliser un pilote et livrer recherche/explication correspondantes. Critère : ABS 2000 et couleurs par millésime passent, avec états inconnus et couverture visible.
5. **Compléter la collecte technique.** Reprendre les fiches incomplètes et années manquantes avec métriques par champ/source/année. Critère : reprises idempotentes, aucune couverture exhaustive prétendue sans preuve.
6. **Indexer les passages techniques utiles.** Créer un index versionné, filtrable par identité et millésime ; comparer filtrage structuré seul et recherche de passages. Critère : les preuves attendues sont retrouvées et aucune note de variante ou unité n'est perdue au découpage.
7. **Comparer les modèles locaux.** Tester d'abord la référence, Gemma 4 12B MLX et Ministral 3 14B ; étendre à Qwen si utile. Critère : choix motivé par qualité, appels d'outils, temps total et mémoire sur ce M5 ; aucun basculement fondé seulement sur un classement général.
8. **Consolider le POC et son explication.** Documenter installation locale, limites, modèle retenu et résultats. Critère : démonstration technique reproductible après chargement des nouvelles versions et matière vérifiable pour l'article.

## Hors périmètre

- Analyse des états d'âme, réputation ou sentiment des propriétaires ; nouveaux enrichissements d'avis.
- Suppression des avis et des anciens datasets pour gagner de la place.
- Production, hébergement public, API cloud obligatoire et modèle dépassant le budget de la machine.
- Fine-tuning et remplacement simultané de tous les composants de recherche.
- Affirmation d'un catalogue mondial exhaustif, ou de performances mesurées lorsque la source donne seulement une annonce.
- Rédaction de l'article avant validation du nouveau parcours technique.

## Notes complémentaires

Les correctifs préparatoires de cette reprise portent sur le démarrage local, le rapprochement prudent des modèles, la provenance des évaluations, les messages de timeout, le budget coopératif de tour et le volume de preuves transmis. Ils sécurisent l'expérimentation ; ils ne constituent pas encore la refonte technique décrite ici.

L'essai local de six questions a validé quatre contrôles objectifs après correction d'un faux négatif de provenance ; deux cas ont terminé en timeout. Ce petit smoke test, effectué en partie pendant un essai interactif concurrent, ne constitue pas un score global de qualité ni un benchmark de latence isolé. Les nouveaux correctifs doivent encore être chargés et rejoués dans la démo, dont le redémarrage a été différé à la demande de l'utilisateur.

Le cap retenu est donc : **des fiches techniques fiables, des comparaisons prouvées, puis éventuellement des avis**, avec un fonctionnement local mesuré et un statut de POC assumé.

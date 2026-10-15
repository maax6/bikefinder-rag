# Mistral seul, Jev et embeddings techniques : essais du 14 octobre 2026

Deux expériences distinctes : choisir un modèle pour piloter les outils et choisir
un modèle pour retrouver les passages. Les résultats restent locaux ; le chat et
les deux anciennes passes du benchmark public ne sont pas modifiés.

## Mistral seul et parcours Jev

Mistral Small 3.2 24B Q4_K_M, via Ollama, a accès aux six outils communs en
lecture seule : SQL pour les identités, filtres, comptes et mesures ; BM25/BGE-M3
pour les passages. Il choisit ses appels, consulte les preuves et soumet sa réponse.
Il n'a pas Bash, d'accès libre aux fichiers ou de droit d'écriture sur la base.

Le candidat distant est Mistral Small 4 (`mistralai/mistral-small-2603`) via
OpenRouter. Le témoin Jev (`typesafe/jev-1.13`) utilise son API de décisions et
le routeur/rendu SQL existant, sans rédaction Mistral ni nouvelle synthèse.
Ce témoin n'est pas le front Gradio complet et ne possède pas l'interface
conversationnelle des deux Mistral : on compare des parcours, pas seulement des
poids de modèle. Les neuf appels Jev utilisent un cache isolé neuf. PostgreSQL
et le snapshot SQLite ont les mêmes 11 478 identités et empreintes sources ;
PostgreSQL conserve 105 687 passages.

Huit cas connus du pilote précédent, soit neuf tours attendus, avec un plafond de
30 secondes par tour et des plafonds de contexte/outils identiques pour les deux
Mistral. Une session neuve par cas ; le dialogue Q37 conserve son contexte. Un
échec du premier tour empêche le suivant. L'initialisation de l'index et le
chargement/échauffement du modèle sont séparés des durées de réponse.

| Parcours | Résultat du premier passage | Temps observé |
|---|---|---|
| Mistral Small 3.2 local | 6 cas en timeout, une non-réponse soumise comme finale, un manque d'identité signalé mais réponse incomplète | Presque 30 s par cas ; manque d'identité à 28,4 s |
| Jev + routeur/rendu SQL existant | 4 cas entièrement corrects sur 8 ; les 9 tours retournent pourtant du texte | Médiane 0,274 s par tour ; première réponse 2,66 s |
| Mistral Small 4 distant | Une réponse correcte ; 7 cas interrompus par HTTP 429 | Réponse correcte à 3,90 s, autres cas non comparables en qualité |

« Completed » est un succès de format/exécution, pas un jugement de qualité.
Mistral local soumet « La recherche est en cours » pour le compte Q01, sans
outil ni résultat : c'est un échec. Sur Q34, il trouve que l'édition fictive est
inconnue, sans substituer la fiche standard ; il ne répond pas explicitement à
la disponibilité du régulateur. Les six autres cas n'ont pas de réponse finale
dans le délai. Le smoke initial avait trouvé la bonne hauteur de selle de
785 mm, mais avait également expiré avant la réponse.

Jev répond correctement au compte Yamaha, à la cylindrée, à l'écart de selles
et aux variantes Z650. Il affirme à tort que les fiches Gold Wing/BMW demandées
n'existent pas ; demande l'année quand celle-ci est à découvrir ; remplace
l'édition fictive par la fiche standard. Q37 commence avec la bonne liste de huit,
puis perd les critères au suivi et retourne **8 697**, au lieu de **3**. Ce dernier
cas n'est pas entièrement correct. Ces erreurs du parcours ne sont pas des
échecs démontrés du modèle d'embeddings.

Un deuxième passage distant sur Q01/Q17/Q24/Q27, avec au moins deux secondes
entre les départs d'appels, reçoit encore quatre HTTP 429. Il ne remplace pas
le premier passage. La réponse correcte disponible donne 689 cm³ pour la
MT-07 2020, avec les preuves attendues. Cela ne suffit pas à choisir un modèle
plus intelligent : l'évaluation distante est limitée par la disponibilité.

## Prix : dépenses connues et réservations

L'utilisateur a autorisé les questions, métadonnées nécessaires et extraits
techniques vers ces deux services via OpenRouter, sous un **plafond total de
0,50 $**, entrées et sorties comprises. Le transport réserve avant chaque appel
une enveloppe conservatrice incluant le contexte, les outils et la sortie maximale.
Un coût manquant conserve sa réserve. Le deuxième passage reprend le registre
entier du premier, au lieu de remettre le budget à zéro.

- Mistral local et les embeddings : **0 $ de coût API** ; électricité et
  amortissement ne sont pas mesurés.
- Jev : **0,00142674 $ confirmés**, pour neuf décisions.
- Mistral Small 4 : **0,00252753 $ confirmés** ; onze appels rejetés n'ont pas
  de coût total retourné, sur les deux passages.
- Total confirmé : **0,00395427 $**. Total conservateur, réservations comprises :
  **0,16218027 $**, sous le plafond de 0,50 $. Cette réserve n'est pas une facture.

Les tarifs publics vérifiés étaient 0,042 $ par million de tokens d'entrée pour
[Jev](https://openrouter.ai/typesafe/jev-1.13/api), sortie à 0 $ ; et 0,15 $/0,60 $
par million de tokens entrée/sortie pour
[Mistral Small 4](https://openrouter.ai/mistralai/mistral-small-2603/pricing).
Le coût d'une réponse comprend tous les tours de modèle et les preuves relues,
pas seulement le texte de la question. Les coûts retournés priment sur ces tarifs.

[Traces locales](../eval_results/technical/mistral-alone-20261014/local-v1/results.json),
[premier passage distant/Jev](../eval_results/technical/mistral-alone-20261014/remote-v1/results.json),
[rejeu espacé et registre complet](../eval_results/technical/mistral-alone-20261014/remote-paced-v2/results.json),
[relecture](../eval_results/technical/mistral-alone-20261014/review-v1.json),
[équivalence du corpus](../eval_results/technical/mistral-alone-20261014/corpus-equivalence.json),
[bilan](../eval_results/technical/mistral-alone-20261014/summary.json).

## Comparaison locale des embeddings

Le pilote conserve les textes et identités d'origine, sans nouveau découpage.
**4 096 passages** : toutes les sections des fiches des périmètres fournis,
l'union des candidats/classements historiques des quatre méthodes, puis des
passages tirés avec une graine fixe. Cinquante questions déjà connues, dont
44 avec preuves annotées ; six négatifs restent hors des dénominateurs de pertinence.
Le protocole et les empreintes du sous-ensemble sont figés avant les exécutions.

Trois modèles :

- [BGE-M3](https://huggingface.co/BAAI/bge-m3), MIT, référence dense actuelle ;
- [Qwen3-Embedding 0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), Apache-2.0 ;
- [multilingual-E5-large-instruct](https://huggingface.co/intfloat/multilingual-e5-large-instruct), MIT.

Tous restent multilingues. Qwen et E5 reçoivent une instruction de recherche
commune en anglais, conformément à leur usage ; BGE n'en exige pas. Révisions
et empreintes des fichiers sont enregistrées. Calcul MPS float16, vecteurs
normalisés, 512 tokens maximum ; aucun texte ni requête n'est tronqué.
Les vecteurs documentaires BGE déjà préparés sont repris dans le même ordre ;
Qwen et E5 réencodent les mêmes passages. Chaque modèle est aussi testé avec
le même BM25, et la même fusion RRF (40 candidats par méthode, constante 60).
Aucun modèle génératif, reranker, appel cloud ou juge distant n'intervient.

Résultats **dense seul** :

| Modèle | Première preuve pertinente parmi les 4 096 passages | Première preuve pertinente avec identités fournies | Toutes les preuves requises dans le top 10, identités fournies | Médiane recherche dans le sous-ensemble |
|---|---:|---:|---:|---:|
| BGE-M3 | 27/44 | 40/44 | 44/44 | 15,8 ms |
| Qwen3-Embedding 0.6B | 34/44 | 39/44 | 43/44 | 35,8 ms |
| E5-large-instruct | 22/44 | 43/44 | 43/44 | 24,3 ms |

Le rappel des preuves connues à 10 dans le sous-ensemble est respectivement
83,7 %, 85,2 % et 80,7 %. Toutes les preuves requises y sont présentes à 10
sur 30/44, 32/44 et 28/44 cas. Les latences incluent encodage de la requête et
classement du sous-ensemble, sans chargement du modèle ni encodage des documents.
L'encodage des 4 096 documents prend environ 87,3 s pour Qwen et 21,0 s pour E5 ;
BGE reprend son index existant, donc aucun coût d'encodage comparable n'est annoncé.
Un passage par requête ne suffit pas à établir un P95 robuste.

La fusion actuelle n'améliore pas systématiquement l'embedding : le premier
rang dans le sous-ensemble passe de 34/44 à 26/44 pour Qwen, de 27/44 à 30/44
pour BGE, de 22/44 à 29/44 pour E5. Sa couverture complète à 10 est respectivement
24/44, 27/44 et 31/44. Les valeurs de fusion n'ont pas été adaptées sur ces questions.

Ce pilote suggère Qwen pour la recherche ouverte et E5 pour le classement dans
une identité connue. BGE conserve toutefois la meilleure couverture complète
à 10 dans les périmètres fournis. Aucun remplacement général n'est établi.
La sélection des distracteurs utilise les anciens systèmes et les preuves :
elle peut biaiser le résultat. Les jugements globaux sont incomplets ; les
passages non jugés ne sont pas automatiquement faux. Les identités fournies
sont une expérience oracle, pas une résolution d'identité par le bot.

[Bilan structuré](../eval_results/technical/embedding-model-comparison-20261014/summary.json)
et résultats détaillés [BGE](../eval_results/technical/embedding-model-comparison-20261014/bge-pilot-v1.json),
[Qwen](../eval_results/technical/embedding-model-comparison-20261014/qwen-pilot-v1.json),
[E5](../eval_results/technical/embedding-model-comparison-20261014/e5-pilot-v1.json).

## Décision à prendre ensuite

Les comptes et les contraintes exactes restent en SQL ; les codes et termes
littéraux disposent de BM25/recherche littérale ; les embeddings retrouvent les
explications et paraphrases. BGE-M3 offre lui-même des modes sparse et multi-vecteurs,
mais ce pilote ne teste que sa représentation dense. Le multilinguisme seul
n'explique donc pas les échecs du parcours actuel.

Avant migration : comparer les candidats sur les 105 687 passages avec un nouveau
lot indépendant, garder les erreurs d'identité distinctes de la récupération,
mesurer la complétude et décider les paramètres de fusion sur un lot de développement.
Qwen3-Embedding 4B reste un candidat plus lourd **non exécuté**, pas un gagnant annoncé.
Un changement d'embedder impose un nouvel encodage des documents ; des vecteurs
à 1 024 dimensions de modèles différents ne partagent pas le même espace.

Les millisecondes de récupération ne résolvent pas à elles seules les dizaines
de secondes de génération locale, les refus de découverte du routeur ou les
HTTP 429 du fournisseur. Ces trois problèmes doivent être mesurés séparément.

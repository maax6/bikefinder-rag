# Pilote contrastif BGE-M3 avec LoRA — 15 octobre 2026

[Ouvrir l’annexe HTML interactive](benchmark-finetuning.html) : comparaison
avant/après, 156 questions inspectables, exemples d’apprentissage et export des
données. Le fichier est autonome et lié depuis le benchmark principal.

**Pilote entraîné et évalué ; adaptateur non retenu pour le chat.** Avec la
recherche hybride, la couverture complète passe de 60/64 à 61/64 sur les nouvelles
questions et de 66/92 à 78/92 sur les anciens cas. Cependant, neuf questions
perdent une preuve requise, dont sept deviennent incomplètes. Le critère
« aucune preuve perdue » échoue. BGE-M3 d'origine reste utilisé par le chat.

## Ce qui a été entraîné

Le pilote adapte la représentation dense utilisée par notre recherche, à partir
de BGE-M3 à sa révision figée. Il conserve le pooling CLS, la normalisation et
les 1 024 dimensions. BM25 n'est pas modifié ; les fonctions sparse/ColBERT
natives de BGE-M3 ne sont pas entraînées ici.

LoRA ajoute des paramètres aux projections query/value des 24 couches :
rang 8, alpha 16, dropout 0,05. **786 432 paramètres sont entraînés**, environ
0,14 % du modèle avec adaptateur. Les poids de base restent gelés. Cette
méthode est prise en charge par [Sentence Transformers et PEFT](https://sbert.net/examples/sentence_transformer/training/peft/README.html).

L'entraînement local sur le Mac M5 a effectué **512 pas**, soit deux passages
sur les 512 questions, avec deux questions par lot. Il a duré **656 secondes**
(environ 11 minutes), hors préparation, essai technique et réindexation.
Le taux d'apprentissage est de 0,00003. La longueur maximale est fixée à
384 tokens ; le plus long texte d'entraînement/validation observé en compte 161.
Aucun texte n'est tronqué.

## Données et séparation des lots

| Lot | Questions | Fiches cibles distinctes | Rôle |
|---|---:|---:|---|
| Apprentissage | 512 | 267 | Mise à jour des paramètres LoRA |
| Validation | 64 | 46 | Choix entre les deux sauvegardes |
| Nouveau test | 64 | 40 | Mesure finale après choix du modèle |
| Anciens cas | 92 | 112 | Régressions des études précédentes |

Les marques sont distinctes entre les quatre lots. Cela réserve ensemble
les années et variantes d'une marque, et empêche qu'une fiche de test devienne
un négatif d'entraînement. Certaines fiches sont réutilisées à l'intérieur
d'un même lot : le nombre de questions n'est pas un nombre d'observations
statistiquement indépendantes.

L'apprentissage utilise Brixton, Brough Superior, Daelim, Derbi, Hyosung,
Laverda, MZ / MuZ, Macbor, Orcal, QJ Motor, Rieju et Voxan. La validation porte
sur FB Mondial, Kove, Ural et Zontes. Le nouveau test utilise BSA, Fantic,
GASGAS, Gilera, Kymco et Morbidelli. Les marques des anciens cas, notamment
Honda, Yamaha, Suzuki et BMW, ne participent pas à l'apprentissage. Ce choix
protège les évaluations antérieures, mais donne un corpus d'entraînement
orienté vers de plus petits constructeurs.

Les [512 exemples annotés](../eval_results/technical/bge-lora-pilot-20261015/exemples-entrainement.md)
sont construits depuis les fiches, à partir de douze gabarits. Les formulations
de validation et de test sont différentes des formulations d'apprentissage,
mais restent écrites par le même assistant. Il ne s'agit pas de questions
collectées auprès d'utilisateurs, ni d'un panel indépendant.

## Positifs multiples et négatifs vérifiés

Les questions d'apprentissage associent **764 passages pertinents** et
**2 048 passages négatifs**. Parmi elles, 252 nécessitent deux sections.
Les quatre négatifs par question sont sélectionnés avec BGE-M3 d'origine,
uniquement dans les marques du même lot :

- 1 537 occurrences concernent une autre identité explicitement demandée
  (modèle, variante ou année différente) ;
- 511 occurrences proviennent de la bonne fiche, mais d'une rubrique qui ne
  contient aucun des faits demandés selon les règles d'annotation.

Un passage d'une autre année n'est pas une preuve de la fiche demandée, même
si certaines valeurs se répètent. Une section complémentaire pertinente est
toujours positive. Chaque positif est comparé aux seuls négatifs explicites :
les positifs ne se font pas concurrence, et les autres questions du lot ne
deviennent pas automatiquement des négatifs. La température de la perte
contrastive est fixée à 0,05.

L'[audit d'annotation](../eval_results/technical/bge-lora-pilot-20261015/annotation-audit.json)
vérifie 3 165 occurrences de passages contre les textes canoniques pour
l'apprentissage et la validation. Les citations et identités sont contrôlées
automatiquement ; 24 exemples répartis sur les douze marques ont aussi été
relus par l'assistant pour les identités et rubriques. Ce contrôle n'est pas
une annotation humaine indépendante exhaustive.

## Apprentissage et choix de sauvegarde

| État | Erreur contrastive de validation, plus faible = mieux |
|---|---:|
| BGE-M3 avant adaptation | 1,14834 |
| Après une passe | 0,48246 |
| Après deux passes — retenu | 0,43397 |

Cette diminution mesure le classement parmi les positifs/négatifs annotés.
Elle n'est ni un pourcentage de bonnes réponses ni un résultat de recherche
sur tout le catalogue. Le nouveau test et les 92 anciens cas ne choisissent
pas la sauvegarde.

Un essai technique séparé de vingt pas a précédé les deux passes, puis le
pilote complet est reparti de BGE-M3 d'origine. Le rechargement de cet
adaptateur reproduit exactement son erreur de validation. La fusion des
48 couches LoRA en mémoire a aussi été vérifiée, avec une différence maximale
d'environ 0,000000205 sur les vecteurs sondés. Les sauvegardes complètes et
leurs empreintes sont conservées ; le modèle du chat n'est pas remplacé.

## Réindexation et protocole de recherche

Les **105 687 passages** sont réencodés dans un dossier séparé avec le modèle
retenu, en **517 secondes** (environ 8 minutes 37). Il est nécessaire d'utiliser le nouvel encodeur pour les documents
comme pour les questions. Les textes, identités et rubriques sont identiques
à ceux de l'index d'origine.

Les deux modèles sont comparés en dense seul puis avec la fusion actuelle :
40 candidats par branche, poids BGE/BM25 1:1, constante RRF 60, dix passages
livrés. Les documents sont encodés en float16, les requêtes en float32,
comme pour la référence. Un contrôle sur 32 passages mesure la fidélité du
pipeline d'encodage de base aux anciens vecteurs. La référence doit également
reproduire les classements précédents sur les 92 anciens cas.

Ces contrôles passent : cosinus minimal de 0,99999988 sur les 32 passages,
et les **92 classements top 10 de référence sont identiques** aux résultats
de l'étude précédente. Les textes du catalogue atteignent au plus 272 tokens,
sans troncature. L'[empreinte de l'index candidat](../eval_results/technical/bge-lora-pilot-20261015/index-manifest.json)
lie les vecteurs à l'adaptateur retenu et au corpus figé.

La règle de promotion est figée : gain de complétude sur le nouveau test,
aucune preuve requise perdue sur les tests nouveau et ancien, et aucun recul
du nombre de premiers résultats pertinents. Le pilote n'active rien
automatiquement dans le chat.

## Résultats de recherche

La couverture complète signifie que toutes les rubriques requises sont présentes
dans les dix passages retournés. Un premier passage pertinent ne suffit pas à
garantir cette complétude, ni une réponse finale correcte.

| Recherche et lot | Couverture complète avant → après | Premier passage pertinent avant → après |
|---|---:|---:|
| Hybride, 64 nouvelles questions | 60 → 61 / 64 | 30 → 52 / 64 |
| Hybride, 92 anciens cas | 66 → 78 / 92 | 63 → 74 / 92 |
| Dense seul, 64 nouvelles questions | 56 → 52 / 64 | 57 → 62 / 64 |
| Dense seul, 92 anciens cas | 63 → 81 / 92 | 71 → 83 / 92 |

Les [mesures brutes](../eval_results/technical/bge-lora-pilot-20261015/evaluation-v1/summary.json)
montrent une amélioration du premier résultat, mais des évolutions différentes
selon le lot et la méthode. **Le dense seul recule sur la complétude du nouveau
test.** La baisse de l'erreur d'apprentissage ne garantit donc pas un gain de
recherche uniforme.

En hybride, le gain net sur le nouveau test cache quatre questions devenues
complètes et trois devenues incomplètes. Sur les anciens cas, seize deviennent
complètes et quatre deviennent incomplètes ; deux autres, déjà incomplètes,
perdent aussi une preuve. Le [détail des neuf régressions](../eval_results/technical/bge-lora-pilot-20261015/regressions.md)
conserve les questions, passages sources et rangs constatés. Exemples :

- BSA 650 Scrambler 2026 : la rubrique moteur contenant les 652 cc passe
  du rang 4 à une absence du top 10.
- Fantic Caballero 700 Scrambler 2024 : la transmission par chaîne passe
  du rang 2 à une absence du top 10 ; le refroidissement seul ne suffit pas.
- BMW R 1200 GS 2018 / 2017 : le châssis de la 2018, nécessaire pour comparer
  selle et réservoir, sort du top 10 alors qu'il était troisième.

**Décision : conserver les poids et résultats comme expérience locale,
sans remplacer le modèle ni l'index du chat.** Le pilote démontre que nous
pouvons adapter BGE-M3 localement ; il ne démontre pas une amélioration sans
régression. Les gains ne doivent pas être présentés comme un taux de bonnes
réponses du chatbot.

Pour une seconde expérience, la priorité est d'ajouter des questions exigeant
plusieurs fiches et des preuves complémentaires aux marques d'entraînement,
puis de vérifier les négatifs avec davantage de variantes et d'années proches.
Le lot actuel n'enseigne que des demandes portant sur une seule fiche. C'est une
piste cohérente avec les erreurs observées, pas une cause établie. Un réglage
plus conservateur devra être choisi sur la validation ; une nouvelle évaluation
finale indépendante sera nécessaire puisque les erreurs de ce test sont
désormais connues. Aucun deuxième entraînement n'a été lancé.

## Exécution et reproduction

La suite du projet passe : **1 201 tests réussis, 8 ignorés**, dont cinq tests
ajoutés pour les positifs complémentaires, les gradients contrastifs et la
séparation des marques. La configuration pytest cible désormais `tests/` :
la première collecte générale avait inclus les tests internes d'Accelerate,
présents dans le dossier local de dépendances. La collecte par défaut a ensuite
été vérifiée. Les journaux sont conservés avec le
[bilan du pilote](../eval_results/technical/bge-lora-pilot-20261015/summary.json).

L'[audit final](../eval_results/technical/bge-lora-pilot-20261015/final-integrity-audit.json)
vérifie les empreintes du corpus et de l'index d'origine, les adaptateurs
sauvegardés, ainsi que les dimensions, valeurs finies et normes de l'index
candidat. Les fichiers du code applicatif sous `src/` n'ont pas été modifiés.

Aucun appel d'inférence distant ni dépense API n'est nécessaire au pilote.
Les seuls téléchargements de préparation sont PEFT et Accelerate, installés
dans un dossier isolé. L'environnement Python du chat n'est pas modifié.
Les versions enregistrées sont PEFT 0.21.2 et Accelerate 1.15.0, avec le
PyTorch, Transformers et Sentence Transformers déjà présents.

Le [protocole figé](../eval_results/technical/bge-lora-pilot-20261015/bundle/protocol.json),
les annotations, les étapes et les
[résultats d'apprentissage](../eval_results/technical/bge-lora-pilot-20261015/train-v1/result.json)
permettent d'inspecter l'expérience. Les poids et vecteurs volumineux restent
dans le dossier local ignoré par Git, data/technical/bge-lora-pilot-20261015.

Le script est [train_bge_contrastive.py](../scripts/train_bge_contrastive.py).
Il propose les étapes prepare, mine, smoke, train, index et evaluate. Chaque
sortie doit utiliser un chemin neuf afin de conserver les premières mesures.
Le lot archivé est la référence ; reconstruire un lot avec prepare dépend
de l'inventaire historique présent au moment de l'exécution.

L’annexe HTML se régénère avec
`python scripts/render_bge_finetuning.py`, sans entraînement ni appel réseau.
Le générateur vérifie les empreintes des entrées et recalcule les agrégats depuis
les classements avant de produire `docs/benchmark-finetuning.html`. Son gabarit
est `scripts/templates/bge_finetuning.html`. Les 156 cas et leurs passages sont
embarqués ; les exports JSON et CSV fonctionnent dans le navigateur. Pour publier
l’annexe, conserver ce fichier à côté de `docs/benchmark.html`, qui la référence.

~~~bash
# Dépendances optionnelles isolées : aucune mise à jour de l'environnement du chat.
.venv/bin/python -m pip install --no-deps \
  --target data/technical/bge-training-runtime-20261015 \
  -r scripts/requirements-bge-training.txt

# Réutiliser les lots figés, avec un nouveau répertoire de sortie.
PYTHONPATH=data/technical/bge-training-runtime-20261015:src \
  .venv/bin/python scripts/train_bge_contrastive.py train \
  --bundle eval_results/technical/bge-lora-pilot-20261015/bundle \
  --mined eval_results/technical/bge-lora-pilot-20261015/mined \
  --out /private/tmp/bge-lora-reproduction/train
~~~

Le script requiert les modèles et le corpus conservés localement, ainsi
qu'un accès MPS. Les limites restent celles d'un premier pilote : français
uniquement, questions construites depuis les sources, négatifs contrôlés
par règles et évaluation des passages plutôt que des réponses finales du chat.

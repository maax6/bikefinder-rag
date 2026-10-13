# Questions libres dans le chatbot — 13 octobre 2026

Les corrections sont actives dans le chatbot local. Les demandes factuelles,
les relances et les calculs simples utilisent les fiches et SQL directement.
Jev choisit parmi des décisions définies ; il ne fournit ni SQL libre ni
nouvelles valeurs techniques. Mistral reste réservé aux synthèses qui demandent
une interprétation supplémentaire des preuves.

## Méthode et résultat

Deux agents ont écrit **40 questions sans voir le code ni les formulations du
lot précédent**. Le premier a fourni 30 questions ; le second, dix nouvelles
questions après la première série de corrections. Quatorze essais exploratoires
supplémentaires donnent un total de **54 questions**, dont sept dialogues
avec 19 tours, et 35 questions isolées.

Les réponses ont été obtenues par l'API `/chat` du serveur Gradio actif, puis
leur routage a été inspecté séparément. Les agents auteurs ont vérifié leurs
40 réponses contre les fiches brutes. Il s'agit d'une revue par agents,
pas d'une annotation humaine indépendante. Les défauts découverts ont été
corrigés avant le rejeu final : ce rejeu ne mesure donc pas une précision
générale sur des questions encore inconnues.

| Revue des réponses | Complètes | Limite justifiée / clarification | Incorrectes | Incomplètes |
|---|---:|---:|---:|---:|
| Première série de 30, avant corrections | 1 | 5 | 24 | 0 |
| Dix nouvelles questions après les premières corrections | 1 | 0 | 2 | 7 |
| Rejeu final des 40 questions indépendamment rédigées | 16 | 24 | 0 | 0 |

Les **24 réponses avec limite** ne sont pas 24 réponses complètes : elles
exposent ce que les fiches permettent de dire, ou demandent la variante qui
manque. Aucune erreur matérielle ni omission injustifiée ne subsiste dans cette
revue finale. Les quatorze essais exploratoires ne sont pas inclus dans ce
score de qualité.

## Temps et usage des modèles

| Mesure du chatbot actif | Résultat |
|---|---:|
| Questions du rejeu final | 54 |
| Réponses concordantes avec le routage inspecté séparément | 54/54 |
| Appels Mistral nécessaires sur ce lot | 0 |
| Médiane API du rejeu, majoritairement en cache | 0,057 s |
| 95e percentile API, rang supérieur | 0,113 s |
| Maximum API du rejeu | 0,542 s |
| Une question supplémentaire nouvelle, sans cache Jev | 0,541 s |
| Suite précédente : contrôle des plans et données | 480/480 |
| Tests de tout le workspace local, PostgreSQL compris | 622 réussis en 7,27 s |
| Tests de la copie exacte sélectionnée pour publication | 605 réussis en 9,52 s |

Les temps API excluent l'inspection séparée du routage. La concordance API
valide le comportement du serveur, pas la justesse sémantique de chaque réponse.
Les 54 temps du rejeu sont majoritairement en cache. La question supplémentaire
sur le couple et les deux types de poids de la BMW F 900 R 2020 a créé une
nouvelle entrée de classification Jev pendant son appel API ; son temps est
une mesure individuelle, pas une médiane générale sans cache.

La suite précédente conserve ses 480 contrôles réussis. Ses dix cas complexes
contrôlent le choix de la synthèse ; il n'y a pas eu 480 générations Mistral.
Les 622 tests couvrent aussi des travaux de collecte et de suivi déjà présents
dans le workspace. Une copie du dernier commit publié, complétée seulement par
les fichiers du chatbot sélectionnés, passe **605 tests**, intégration PostgreSQL
comprise. Les modifications de collecte et de suivi restent hors de cette
publication.

Le coût de recherche des noms a été réduit : sur trois mêmes questions répétées
trois fois, la médiane de cette seule opération passe de **440 à 23 ms**, avec
les mêmes références trouvées. Ce microbenchmark n'est pas le temps complet
d'une réponse.

## Corrections et exemples

- Les noms courts ou familiers (`F900R`, `MT07`), l'ordre marque/modèle,
  « balles » pour les euros et « bourrins » pour les chevaux sont reconnus.
  Les chiffres d'un modèle ne deviennent pas une cylindrée ou une année.
- Les négations et exclusions sont conservées. « Les bécanes de 2010 dont on
  sait qu'elles n'ont pas d'ABS, pas celles où t'as aucune info » donne **zéro
  fiche avec absence explicite**, sans prendre les inconnus pour des absences.
- Les filtres de plusieurs équipements s'appliquent ensemble, avec leur statut
  propre. Une relance qui ajoute un prix minimum garde le maximum déjà donné.
- Les relances corrigent le modèle ou le millésime concerné seulement. Une
  demande bloquée conserve son contexte sans exécuter un plan partiel trompeur.
- Les différences et classements calculables ne passent plus inutilement par
  Mistral. Pour Monster 2022 / SV 650 2022, le poids tous pleins faits est
  comparé sur **188 / 197 kg** ; le poids sec n'est pas mélangé à cette mesure.
- Pour Himalayan 450 2024 / NX 500 2024, les poids pleins faits sont identiques
  (**196 kg**). La selle **825–845 mm / 830 mm** impose de préciser le réglage,
  au lieu de désigner arbitrairement la moto la plus basse.
- Le couple en mkg reste cité dans son unité source. Une selle réglable ne
  prouve pas une selle basse incluse ; une mention de boîte DCT ne prouve pas
  son inclusion ou son supplément. Les autonomies calculées gardent leur
  qualification « non vérifiée ».
- Les tarifs de fiche restent des tarifs France de base documentés. Une
  question sur le prix au lancement reçoit la valeur disponible et une réserve
  explicite lorsque sa date d'application n'est pas établie.

## Ce qui reste limité

Les catégories globales, la disponibilité sur un marché et les critères légaux
A2 ne sont pas complètement normalisés. Certains modèles ou millésimes manquent,
et plusieurs variantes ou générations partagent un nom : une précision reste
alors nécessaire. Une absence de mention d'équipement reste inconnue.

Les fiches ne garantissent pas l'autonomie à une vitesse, avec un passager ou
une charge donnés. Elles ne donnent pas automatiquement un prix actuel ou
d'occasion, ni une preuve de fiabilité ou de confort pour une personne.
Mistral peut encore servir à une synthèse complexe lorsque les preuves suffisent ;
ajouter de la génération ne comble pas une donnée absente.

BGE-M3 reste disponible pour chercher les passages techniques dans un périmètre
défini. Ce lot ne valide pas un index vectoriel complet de toutes les fiches.
Jev fonctionne à distance via OpenRouter ; les questions lui sont transmises.
SQL, le catalogue et Mistral restent locaux.

La collecte et les données sources n'ont pas été modifiées par ce travail.
Au moment des mesures, les corrections étaient actives localement et pas encore
publiées. Le code, les questions figées et les bilans sont ensuite sélectionnés
pour publication ; les données sources et les caches restent locaux.

## Preuves et reproduction

- [Questions figées](../eval_results/technical/free_chat_all_questions_20261013.json)
- [Résultats et empreintes du code](../eval_results/technical/free_chat_results_20261013.json)
- [Verdicts initiaux et finaux](../eval_results/technical/free_chat_reviews_20261013.json)

Les réponses et mesures détaillées sont conservées localement dans
`data/technical/free-questions-20261013/`, ignoré par Git. Le script mesure
d'abord l'API puis inspecte le routage ; il ne déduit pas un verdict de qualité
d'une simple réponse HTTP réussie.

```sh
PYTHONPATH=src .venv/bin/python scripts/evaluate_free_chat.py --api-first --questions eval_results/technical/free_chat_all_questions_20261013.json --out data/technical/free-questions-20261013/replay.json
BIKEFINDER_JEV_ROUTER=0 PYTHONPATH=.:src RUN_CATALOG_INTEGRATION=1 .venv/bin/pytest -q
```

Un rejeu peut utiliser les classifications Jev déjà en cache. Les requêtes
nouvelles nécessitent la clé OpenRouter configurée dans le `.env` du serveur.

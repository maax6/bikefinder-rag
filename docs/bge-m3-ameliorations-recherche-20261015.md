# Améliorer la recherche BGE-M3 avant entraînement

Suite de cette étude : la [confirmation sur 64 nouvelles questions](bge-fusion-confirmation-20261015.md)
mesure un gain moyen mais détecte des pertes de preuves. La fusion candidate
n'est pas intégrée au chat. Les résultats des deux premiers essais sont
conservés ci-dessous.

15 octobre 2026. BGE-M3 est conservé. Deux expériences locales ont mesuré des
changements de recherche sur les **105 687 passages**, sans réencoder les
documents, entraîner le modèle ou activer un réglage dans le chat.

Le candidat retenu sur le développement est une fusion qui donne deux fois plus
de poids au classement BGE et examine 80 candidats par branche. Sur huit
questions nouvelles figées avant leur première recherche, il retrouve toutes
les preuves nécessaires dans **6/8 cas**, contre **5/8 actuellement**, pour une
médiane de **41,4 ms contre 40,3 ms**. Cela représente une question complète
supplémentaire sur ce petit lot, pas un gain d'exactitude générale de 12,5 points.

## Lot d'erreurs annotées

Le [lot lisible de 24 cas](../eval_results/technical/bge-retrieval-improvements-20261015/lot-annote.md)
comprend onze questions de réglage, neuf de vérification sur d'autres marques,
et quatre audits de documents ou d'autorités absents. Chaque cas conserve :

- la question et le type de défaut : autre modèle, année/variante voisine,
  comparaison incomplète, qualificatif ou preuve manquante, limite documentaire ;
- les identités, URL, empreintes sources et textes exacts des preuves attendues ;
- les groupes de preuves nécessaires, les faits attendus et les limites à garder ;
- deux passages proches issus des traces historiques et leur rôle dans la confusion.

Les passages non jugés globalement ne sont pas automatiquement étiquetés comme
de mauvais exemples d'apprentissage. Les cas témoins vérifient notamment le
shifter en option, les coloris et la variante A2 à 94 ch distincte de la R à
120 ch. Ce lot est annoté pour l'analyse de recherche ; aucun corpus
d'apprentissage n'a été exporté et aucune étape d'entraînement n'a eu lieu.

Les 24 questions étaient déjà connues : elles constituent une étude de
régression choisie pour ses erreurs et témoins. La séparation par marques
réduit les partages entre les deux sous-lots ; elle ne les transforme pas en
test indépendant. La relecture est faite par l'assistant à partir des textes et
annotations sources, sans panel humain indépendant.

## Premier essai : le premier passage ne suffit pas

Six configurations ont été figées : dense seul ; fusion actuelle ; fusion
dense/lexical 2:1 avec 40 ou 80 candidats ; fusion actuelle puis reranking de
40 ou 80 candidats. Le choix utilise seulement le développement et privilégie
d'abord toutes les preuves dans le top 10, puis le premier passage et le nDCG.

Sur le développement, le reranking de 40 candidats est choisi. Sur les neuf
cas de vérification connus :

| Recherche | Première preuve pertinente | Toutes les preuves dans le top 10 | Médiane |
|---|---:|---:|---:|
| Fusion actuelle | 6/9 | 7/9 | 42,2 ms |
| Reranking de 40 candidats, choisi avant vérification | 9/9 | 6/9 | 422,2 ms |
| Reranking de 80 candidats | 9/9 | 6/9 | 758,5 ms |

Ce choix n'est pas promu : il améliore le premier résultat, mais certaines
preuves complémentaires sortent des dix passages livrés. Élargir le reranking
à 80 candidats n'a pas corrigé cette perte et augmente le temps.
La fusion 2:1 sur 80 candidats obtenait 8/9 cas complets sur ce même lot, mais
elle n'était pas le choix initial sur développement. Cette observation a
motivé une seconde expérience, sans réécrire les résultats de la première.

## Second essai : conserver les preuves et vérifier sur de nouvelles questions

Le second protocole fige quatre candidats : fusion actuelle ; fusion 2:1 sur
80 candidats ; chacune suivie éventuellement d'un reclassement limité à ses
dix passages déjà retenus. Ce reclassement change uniquement l'ordre. Les
**114 classements** correspondants ont conservé exactement le même ensemble
de dix preuves que leur recherche parente.

Huit [questions nouvelles annotées](../eval_results/technical/bge-retrieval-improvements-20261015/questions-nouvelles-annotees.md)
ont été écrites depuis les sources et figées avant leur première recherche :
Benelli, Husqvarna, Indian et MV-Agusta, marques absentes du développement.
Elles portent sur huit fiches distinctes, parfois partagées entre questions :
cylindrée réelle/réservoir, USB/coloris, deux variantes de Norden, équipements
chauffants, couple/régime et poids inconnu, R contre RR, courroie et dimensions
Scout contre Bobber. Questions et annotations ont le même auteur ; ce n'est
pas une évaluation indépendante ni huit motos statistiquement indépendantes.

Le développement choisit cette fois **la fusion 2:1 sur 80 candidats, sans
reranking**. Le choix est enregistré avant l'utilisation des annotations de
vérification pour calculer les scores. Les empreintes des fichiers sont
contrôlées avant l'exécution, sans utiliser les labels pour classer les passages.

| Recherche sur les huit questions nouvelles | Première preuve pertinente | Toutes les preuves dans le top 10 | Médiane |
|---|---:|---:|---:|
| Fusion actuelle | 5/8 | 5/8 | 40,3 ms |
| Fusion BGE/lexical 2:1, 80 candidats — choix sur développement | 5/8 | 6/8 | 41,4 ms |
| Fusion actuelle puis reclassement de ses dix preuves | 6/8 | 5/8 | 155,8 ms |
| Fusion 2:1/80 puis reclassement de ses dix preuves | 6/8 | 6/8 | 169,7 ms |

Le gain du candidat choisi est localisé sur la TRK 702 : les passages du
moteur et du châssis sont maintenant tous deux présents pour répondre
**698 cc et réservoir de 20 litres**. Aucun des huit cas ne perd sa couverture
complète par rapport à la fusion actuelle. Le rappel des preuves connues à 10
passe de 75 % à 81,25 %. Le premier rang ne s'améliore pas avec ce réglage seul.

Le reclassement limité aux dix passages garde bien la couverture, mais le
développement ne le sélectionne pas : il y réduit le nombre de premiers
passages pertinents de 8/11 à 7/11, malgré un gain de premier rang sur les
questions nouvelles. Ce comportement empêche d'en faire une règle universelle.

## Les erreurs restantes orientent la suite

Les deux questions Indian restent incomplètes dans la recherche globale.
Un [diagnostic séparé](../eval_results/technical/bge-retrieval-improvements-20261015/scope-diagnostic.json)
fournit manuellement les identités correctes : la recherche actuelle retrouve
alors les deux groupes requis pour chacune, sur dix ou vingt passages.
Cela montre que les preuves sont disponibles. **Ce diagnostic est une expérience
avec identité donnée**, exclue de la sélection et des tableaux ; il ne démontre
pas que le bot résout automatiquement ces identités.

Les quatre demandes de certificat, câblage, homologation US et calendrier
d'entretien continuent à recevoir des passages de fiches commerciales de la
part des moteurs de classement. Ces candidats ne sont pas les documents
demandés. Aucune règle d'abstention ni seuil de confiance n'est évalué ici ;
le contrôle du type et de l'autorité de preuve reste nécessaire.

La suite utile est donc de valider la fusion candidate sur davantage de
questions et de fiabiliser l'utilisation des périmètres SQL résolus. Une
adaptation des poids de BGE n'est pas encore justifiée par ces seules erreurs.

## Protocole, contrôles et reproduction

Les modèles reçoivent seulement la question et les textes indexés : pas
d'identité oracle, réponse cible ou annotation dans les expériences principales.
Les documents, leur découpage et les vecteurs restent identiques. La fusion
utilise RRF avec constante 60 et exclut les scores BM25 nuls. BGE-M3 garde sa
révision figée et son encodeur de requêtes float32 actuel ; les vecteurs
documentaires restent ceux de l'index existant. Le reranker local
`bge-reranker-v2-m3` est chargé à sa révision figée, en float16 sur MPS.
Les paires sont contrôlées avant l'inférence : aucune troncature au-delà de
512 tokens n'est acceptée.

Trois répétitions mesurent la latence, dans un ordre de configurations mélangé.
Les classements sont identiques entre répétitions. Les médianes incluent
l'encodage de la question, les recherches, la fusion et le reranking éventuel ;
chargements et échauffements sont séparés. Les répétitions ne sont pas de
nouvelles questions indépendantes et ne fournissent pas un P95 robuste.
La machine n'est pas présentée comme un environnement à caches système froids.

La référence expérimentale reproduit le top 10 de la recherche actuelle sur
trois sondes génériques ; un test vérifie aussi cette fidélité et l'exclusion
des scores lexicaux nuls. Les garde-fous couvrent la troncature, le partage de
marques, la priorité à la complétude et la conservation de l'ensemble des preuves.
**1 189 tests du code réussissent, 8 tests d'intégration sont désactivés.**

L'[audit d'intégrité](../eval_results/technical/bge-retrieval-improvements-20261015/integrity-audit.json)
confirme les poids figés, tous les fichiers de l'index, les sources inchangées
et l'absence d'entraînement et d'appel API distant du benchmark. Coût API : **0 $**.
Ces contrôles ne mesurent pas la qualité d'une réponse finale rédigée par le chat.

Les [résultats structurés](../eval_results/technical/bge-retrieval-improvements-20261015/summary.json)
renvoient aux protocoles, sélections, classements complets et audits. Chaque
exécution conserve une copie du script correspondant à son empreinte.
Pour reproduire, choisir de nouveaux chemins afin de préserver les premiers essais :

```bash
PYTHONPATH=src .venv/bin/python scripts/improve_bge_retrieval.py prepare \
  --bundle /private/tmp/bge-errors/bundle
PYTHONPATH=src HF_HUB_OFFLINE=1 .venv/bin/python scripts/improve_bge_retrieval.py run \
  --bundle /private/tmp/bge-errors/bundle --out /private/tmp/bge-errors/run-v1
PYTHONPATH=src .venv/bin/python scripts/improve_bge_retrieval.py prepare-preserving \
  --previous-bundle /private/tmp/bge-errors/bundle --bundle /private/tmp/bge-errors/bundle-v2
PYTHONPATH=src HF_HUB_OFFLINE=1 .venv/bin/python scripts/improve_bge_retrieval.py run \
  --bundle /private/tmp/bge-errors/bundle-v2 --out /private/tmp/bge-errors/run-v2
```

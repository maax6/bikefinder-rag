# Décision : garder Jev pour éviter les générations inutiles

Décision du 11 octobre 2026, après le POC réalisé le 10 octobre.
Suivi : [issue #2](https://github.com/maax6/bikefinder-rag/issues/2).

Le POC est concluant pour ce rôle : on garde Jev dans le workflow cible pour
trier les demandes, classer les équipements à partir de leurs preuves et
sélectionner les passages utiles. Une réponse factuelle déjà disponible dans
la base n'a pas besoin d'être reformulée par un générateur.

## Répartition du travail

1. **SQL** résout la moto, le millésime et la variante, puis applique les filtres,
   calcule les comptes et produit les listes dans cette portée.
2. **BGE-M3** retrouve les passages techniques quand une recherche textuelle est
   nécessaire, en conservant les contraintes d'identité établies par SQL.
3. **Jev** choisit parmi des décisions définies : routage de la demande,
   pertinence d'un passage, équipement de série, en option, explicitement absent
   ou inconnu. On fournit la question, les critères et les preuves disponibles.
4. **Le code** restitue les données ou extraits retenus avec leurs URL. Il
   contrôle les décisions et conserve l'inconnu si les preuves manquent.
5. **Mistral** intervient pour une synthèse ou lorsque la sélection de passages
   ne suffit pas. Pour la classification, il reste le repli sur les décisions
   Jev rejetées par les contrôles ; son résultat n'est pas une preuve constructeur.

Jev ne remplace donc pas l'embedder. Il vérifie et trie ce que la recherche lui
propose. Les probabilités et seuils du POC restent à calibrer sur un échantillon
représentatif ; une décision très probable ne résout pas une source ambiguë.

## Ce qui justifie la décision

Le snapshot contient 2 254 fiches, 19 901 passages et 35 libellés de marques.
Les 880 décisions fiche–équipement concernent 706 fiches et 341 entrées
distinctes, dont 173 avec une mention d'équipement. Les doublons ne sont pas
comptés comme autant d'exemples indépendants.

| Mesure | Fonctionnement actuel comparé | POC hybride |
|---|---:|---:|
| Accord avec les 60 annotations indépendantes | Mistral : 54/60 | Cascade : 54/60 |
| Accord dans le test réservé | Mistral : 34/37 | Cascade : 34/37 |
| Appels Mistral pour 24 questions | 44 | 3 |
| Temps médian backend pour ces questions | 31,3 s | 0,45 s |
| Classification des 173 entrées mentionnant un équipement | Mistral systématique | 141 sans Mistral, 32 replis |

Le parcours actuel utilise sa boucle Ollama réelle avec un adaptateur SQLite
sur le même corpus figé. Ce n'est pas une mesure du chat en production sur
l'ancienne base PostgreSQL. La latence hybride exclut l'encodage précalculé des
questions ; une mesure BGE séparée ajoute environ 79 ms aux six branches qui en
ont besoin. Les 60 références ont été annotées par un agent indépendant avant
consultation des sorties, sans adjudication humaine ou constructeur.

Les 16 questions factuelles obtiennent des faits conformes aux extraits avec
leurs bonnes URL dans les deux parcours. Le POC répond à 15 sans Mistral ;
le dernier nécessite Mistral après l'échec de sélection des passages sur la
transmission. Sur une question de fourche avant, Jev écarte le premier résultat
BGE portant sur le train arrière et retient le passage suivant.

On garde les erreurs dans le bilan : quatre demandes de listes ABS sont
refusées par les outils actuels ; les nouvelles listes restent tributaires
des ambiguïtés de variante et de qualificatifs. Les deux comparaisons complexes
hybrides sont coupées à 400 tokens et l'une contient une interprétation de
suspension non étayée. Le POC ne démontre pas une meilleure précision globale.
Le [rapport complet](hybrid-poc-results.md) détaille les désaccords, coûts,
latences et limites de méthode.

## Mise en œuvre retenue

Le fournisseur testé est **OpenRouter**, modèle demandé `typesafe/jev-1.13`
(réponse observée `typesafe/jev-1.13-20260917`). Ces décisions passent par une
API distante. SQL, BGE-M3 et `mistral-small3.2:latest` restent locaux. Le chat
actuel conserve son fonctionnement local : le POC et la décision ne constituent
pas encore une intégration dans son interface.

On laisse finir la collecte déjà en cours avec sa temporisation, sa reprise et
sa protection `caffeinate -i`. Ensuite : mesurer sa couverture, examiner les
ambiguïtés d'équipement, ajouter des annotations humaines et des questions
moins templatisées, puis intégrer le routage et les réponses directes. Pour les
synthèses, ajuster le budget de sortie et vérifier la complétude des citations.
La fin de cette file ne signifiera pas que toutes les motos du monde sont couvertes.

Les scripts, tests et résultats agrégés sont versionnés. Les snapshots source,
références, sorties par entrée et vecteurs restent sous `data/technical/hybrid-poc/`,
ignoré par Git. La reproduction exacte nécessite ces artefacts locaux et leurs
empreintes ; un nouveau clone peut préparer un autre lot, mais ne doit pas le
présenter comme une répétition de ce benchmark.

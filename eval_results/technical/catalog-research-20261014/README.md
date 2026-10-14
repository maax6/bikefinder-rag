# Validation du parcours de recherche — 14 octobre 2026

Référence actuelle : [verified-panel.json](verified-panel.json). Six cas ciblés passent les contrôles. Les quatre recherches produisent une rédaction locale validée, mais restent en publication `mixed` avec extraits et manques visibles. La liste des [questions](questions.json) est figée ; elle n’est pas un jeu indépendant de benchmark.

Les réponses proviennent de sessions neuves du véritable endpoint Gradio. Leurs reçus correspondent à l’exécution observée ; aucun second appel au moteur n’est utilisé pour reconstruire une preuve. Les identités, empreintes et extraits sont comparés au SQL actuel en lecture seule.

Le contrôle Honda exige une phrase Mistral validée par Jev qui cite la fiche DCT 2018. Retrouver cette fiche sans l’utiliser dans la rédaction ne suffit pas. Le contrôle BMW exige un manque propre à l’automatisation, pas seulement la réserve générique sur les dates de lancement.

## Observations conservées

| Fichier | Lecture |
| --- | --- |
| `firstpass-original.json` | Échec : termes génériques, trop d’extraits et rédaction expirée |
| `secondpass-original.json` | Échec : gestion du retour de couverture et références invalides |
| `thirdpass-original.json` | Faux succès avec les anciens contrôles : pas de preuve DCT 2018 dans la rédaction |
| `final-panel.json` | Panneau intermédiaire malgré son nom : plusieurs réponses ne passent pas les contrôles renforcés |
| `semantic-complement-original.json` | Échec : preuve 2018 récupérée mais omise au profit d’une mention 2023 |
| `chronological-prose-original.json` | Premier passage du cas original avec la preuve 2018 dans une phrase validée ; publication partielle |
| `verified-panel.json` | Six cas passent les contrôles actuels ; recherches toujours `mixed` |
| `browser-original-receipt.json` | Nouvelle exécution de la question originale saisie et envoyée dans le navigateur : 137,33 s, deux phrases Mistral acceptées par Jev |
| `browser-validation.json` | Contrôles SQL de cette exécution et référence à la capture `frontend-original.png` |

Les durées du panneau actuel sont 39,95 à 134,10 secondes pour les quatre recherches, 74,88 secondes pour l’édition inconnue et 0,17 seconde pour le comptage SQL. Elles incluent toute la chaîne et ne constituent pas des percentiles ni une mesure de performance répétée.

Voir le [parcours et ses limites](../../../docs/catalog-research-20261014.md). Les requêtes Jev utilisent le seul service distant autorisé ; encodage et génération restent locaux. Les réponses n’établissent pas de date officielle de lancement.

# Revue indépendante du benchmark

Périmètre : nouveau harness et ses tests, base `f2118d5181813d60eea83bed5de915a87a058806`, issue #3. Deux agents distincts ont examiné le code et la spécification avant ouverture des questions réservées. Aucune inférence ni question réservée pendant la revue du code.

## Standards

Trois défauts concrets corrigés :

- Fraction hors périmètre @10 : numérateur désormais limité aux dix premiers même si `k > 10`.
- Modèles : configurations et poids réempreintés avant ouverture des questions et hors chronométrage des requêtes.
- Diagnostic à la demande : empreinte du snapshot revérifiée avant lecture ; fiches distinctes et cache neuf par fiche explicités.

25 tests ciblés passent, dont mutations de modèles et sources, refus d'utiliser le réservé dans le diagnostic, métriques graduées, portée exacte, comptage des répétitions et reprise sans écrasement. Aucun défaut bloquant restant.

## Spec

Un défaut de métrique @10 identifié indépendamment, corrigé. Les points de livrable à compléter ont été traités : diagnostic brut sur trois fiches, analyse des six demandes hors couverture, erreurs d'années/variantes, pertes de preuves avant/après reranking, mémoire et charge effectivement observées.

Quatre pipelines réellement exécutés avec mêmes textes, questions et contraintes. Le global ne reçoit aucun ID de référence. Les questions sont encodées dans chaque pipeline, les modèles restent locaux, aucun score brut n'est présenté comme une confiance. Les négatifs ne produisent pas de faux taux d'accuracy.

La traçabilité du réservé a été auditée séparément après gel : 11 232 positions retournées conformes aux passages sources. La synthèse finale et la résolution d'identité du chat restent explicitement hors mesure.

Standards : trois constats corrigés. Spec : un défaut corrigé, compléments de rapport réalisés. Aucun défaut ouvert sur la comparaison réalisée ; les contrôles du bot complet constituent le prochain module.

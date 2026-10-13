# Connexion Jev → SQL → BGE-M3 → citations

Rapport : [RAG raccordé au parcours Jev](../../../docs/jev-rag-connection-20261013.md).

- `questions.frozen.json` : 20 formulations gelées avant leur première exécution.
- `fresh-v5.frozen.json` : 6 formulations supplémentaires gelées avant leur premier essai.
- `firstpass.json` : premier résultat des 20 questions, conservé avec ses échecs.
- `development-replay-v3.json`, `identity-development.json` : essais de développement sur des cas déjà observés.
- `regression-v4.json`, `regression-v5.json`, `regression-v6.json` : rejeux successifs des 20 questions.
- `fresh-v5-firstpass.json`, `fresh-regression-v6.json` : premier essai des 6 supplémentaires et leur rejeu corrigé.
- `non-a2-live.json` : vraie question hors A2, rendu et qualifications conservés.
- `jev-receipts.json` : réponses Jev archivées pour les requêtes mesurées, sans clé API.
- `baseline.json`, `validation-manifest.json` : origine du travail, versions, configuration et empreintes.
- `full-tests.log` : résultat de la suite complète.

Chaque série mesure l'API du chat avant d'inspecter séparément le routage.
Les rubriques `routing.evidence` exposent les identités, passages, états de
couverture, manques et temps d'inspection. Ceux-ci ne décomposent pas le temps du
serveur. Un premier modèle d'inspection peut être froid malgré un serveur chaud.

Un contrôle réussi accepte une citation exacte **ou** une limite explicite quand
la preuve manque. Il n'est ni un score humain de pertinence, ni une déclaration
d'éligibilité A2. Les questions sont écrites par l'agent de réalisation ; les
rejeux ne sont pas une évaluation aveugle. Les caches et vecteurs locaux restent
ignorés dans `data/technical/`.

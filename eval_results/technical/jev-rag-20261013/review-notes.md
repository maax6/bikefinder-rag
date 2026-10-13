# Revue finale du raccordement RAG

Base de travail : `b5932ff`. Deux revues parallèles en lecture seule, sans
requête distante, exécution de modèle ou modification par les relecteurs.

## Standards

Aucun blocage restant sur v6. Le cache ZIP corrompu est recalculé ; les demandes
explicites de rubriques et d'équipements ne peuvent plus être supprimées par un
choix Jev. Le lanceur mesure l'API avant l'inspection et compare les passages
aux originaux. Le recomptage confirme les résultats et les temps du rapport.

Limites documentées : interprétation Jev des suffixes nus après l'année ; total
des reçus mesurés excluant le tour d'amorçage ; cache document déjà chaud ;
rubriques supplémentaires encore sélectionnées. Le dénominateur des états de
couverture est précisé comme celui des champs annotés du jeu de validation.

## Spec

Aucun blocage restant. Le nom complet et l'année passent par une fiche SQL
unique ; BGE local classe ses passages ; citations disponibles et couverture
sémantique sont distinguées. `unverified` n'autorise jamais `covered=true`.
Les traces confirment 21 réponses partielles, 5 clarifications, et aucune
certification A2. Les qualifications hors A2 sont conservées.

Le rapport ne présente pas 26 contrôles réussis comme 26 réponses complètes.
Les questions sont écrites par l'agent de réalisation. Premiers essais et
rejeux sont séparés, avec les échecs initiaux conservés.

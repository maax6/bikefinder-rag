# Documentation Bikefinder

Le [README du dépôt](../README.md) présente le projet et son prochain jalon.
Les guides décrivent les opérations ; les rapports conservent les mesures et
les décisions dans leur contexte daté.

Nouvelle conception : [outils SQL et RAG et comparaison local/cloud](sql-rag-tools-and-comparison.md). Le contrat et le lot commun de quarante cas sont préparés ; le nouveau service et les essais de modèles restent à raccorder et exécuter.

Dernier résultat : [benchmark local de recherche — 13 octobre 2026](technical-retrieval-benchmark-20261013.md), lié à l'[issue #3](https://github.com/maax6/bikefinder-rag/issues/3). Prochaine étape : raccordement RAG au parcours Jev avec contrôles d'identité et de preuves.

## Pour travailler sur le projet

| Document | Contenu |
|---|---|
| [Installation et lancement local](guides/local-setup.md) | Préparer l'environnement, les données et le chat |
| [Évaluation et reproduction](guides/evaluation.md) | Choisir les vérifications et lire leurs limites |
| [Architecture actuelle](reference/architecture.md) | Données, voie Jev réellement connectée, recherche disponible et responsabilités |
| [Collecte technique](technical-data-collection.md) | Sources, conservation, reprise et suivi de collecte |
| [Index des scripts](../scripts/README.md) | Outils regroupés par rôle et statut |
| [Guide des résultats](../eval_results/README.md) | Corpus, essais datés et précautions d'interprétation |

## État du chat et décisions récentes

- [Réponses partielles, nouvelles questions et démo du 13 octobre](jev-partial-improvements.md)
- [Questions libres : premiers passages, corrections et limites](jev-free-questions.md)
- [Routage naturel du catalogue](jev-routing-natural-questions.md)
- [Catalogue enrichi connecté au chatbot](enriched-catalog-chat.md)
- [Première passe d'enrichissement des équipements](first-equipment-enrichment-pass.md)
- [Décision hybride : rôle de Jev et générations évitées](hybrid-workflow-decision.md)
- [POC SQL, BGE-M3, Jev et Mistral : mesures et limites](hybrid-poc-results.md)

Une expérience concluante n'implique pas que toutes ses briques sont connectées
au chat. L'architecture actuelle précise notamment que la voie Jev sélectionne
des lignes de fiches sans appeler encore la recherche BGE technique.

## Conception et historique

- [Refonte vers le catalogue technique](technical-catalog-refactor.md)
- [Premier parcours technique](technical-catalog-first-slice.md)
- [Pilote de normalisation des identités et mesures](technical-catalog-normalization-pilot.md)
- [Notes regroupées depuis le README du 13 octobre](history/project-notes-2026-10-13.md)
- [Démo et captures](brag/README.md)
- [Ancien déploiement Hugging Face](../deploy/README.md)

Les documents HTML historiques restent accessibles depuis [l'index public](index.html) :
[preuve de recherche](preuve-retrieval.html),
[pipeline et évaluation](pipeline-et-evaluation.html),
[méthode sans framework](methode-sans-langchain.html).
Ces pages, leurs noms et les fichiers de `assets/` restent à leur place pour
conserver les liens GitHub Pages. Elles décrivent les expériences de leur époque.

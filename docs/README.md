# Documentation Bikefinder

Le [README du dépôt](../README.md) présente le projet et son prochain jalon.
Les guides décrivent les opérations ; les rapports conservent les mesures et
les décisions dans leur contexte daté.

Le [service SQL + RAG et sa comparaison local/cloud](sql-rag-tools-and-comparison.md) dispose de six outils et de deux passes enregistrées ; son raccordement au chat reste à réaliser.

Dernier bilan : [corrections du vrai chat — 15 octobre](bilan-chat-20261015.md), avec [annexe HTML avant/après](benchmark-chat-20261015.html). BGE-M3 d’origine conservé ; 25/36 → 36/36 réponses satisfaisantes sur le lot comparable, puis 15/15 tours supplémentaires, dont le prix moyen. Le cas XJ6 A2 reste partiel ; les limites de relecture et de latence sont explicites.

Essai précédent : [pilote contrastif BGE-M3 avec LoRA — 15 octobre](bge-lora-pilote-20261015.md). Entraînement local sur 512 questions, puis réindexation complète. Couverture hybride de 60/64 à 61/64 sur le nouveau test et de 66/92 à 78/92 sur les anciens cas, mais neuf pertes de preuves : adaptateur non activé.

L’[annexe HTML interactive du fine-tuning](benchmark-finetuning.html) reprend ces résultats avec les 156 questions, les passages avant/après, douze exemples d’apprentissage et les exports JSON/CSV. Elle fonctionne hors ligne et dispose d’un lien depuis le benchmark principal.

Essai précédent : [confirmation de la fusion BGE sur 64 questions inédites — 15 octobre](bge-fusion-confirmation-20261015.md). Couverture complète de 49/64 à 54/64, mais quatre pertes de preuves sur les lots nouveau et ancien : fusion non intégrée au chat.

Étude précédente : [améliorations de recherche avec BGE-M3 conservé](bge-m3-ameliorations-recherche-20261015.md). Lot d'erreurs annotées, comparaison sur tous les passages et huit questions nouvelles, sans entraînement.

Derniers essais locaux : [Mistral seul, Jev et comparaison des embeddings — 14 octobre](mistral-jev-et-embeddings-20261014.md). Ils distinguent les délais de génération, les erreurs du routeur, les HTTP 429 et le classement des passages. Le [benchmark local de recherche précédent](technical-retrieval-benchmark-20261013.md) reste une étude distincte ; l'[issue #4](https://github.com/maax6/bikefinder-rag/issues/4) conserve le bilan de cette phase.

**Prochain jalon : [validation indépendante du parcours complet](phase-test-20261015.md)** — prolonger la campagne exploratoire exécutée par un lot relu indépendamment et valider le raccordement du service commun au chat.

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
au chat. Avec l'option RAG activée, certaines lectures de fiches exactes consultent
BGE-M3 puis Mistral local ; le service commun testé séparément n'est pas encore
raccordé à cette interface.

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

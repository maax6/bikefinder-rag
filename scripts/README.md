# Outils du projet

Lancer les outils depuis la racine du dépôt. Les chemins restent stables pour
les imports, les tests et les commandes de reproduction. Les prérequis figurent
dans les [guides locaux](../docs/guides/local-setup.md) et le
[guide d'évaluation](../docs/guides/evaluation.md).

**Actuel** désigne le catalogue technique et son chat Jev. **POC** désigne une
expérience ou un snapshot isolé. **Historique** désigne l'ancien parcours Bikez,
les avis et leurs évaluations ; ces outils restent utiles à sa reproduction.
Ce statut ne signifie pas qu'un outil s'exécute automatiquement.

Le chat existant utilise Jev comme service d'inférence distant. Les comparaisons
de modèles distants sont des expériences séparées, avec leurs propres données
autorisées et plafonds ; leur présence ne change pas le backend du chat. Les
collecteurs et chargeurs téléchargent des données pendant une préparation
séparée du chat.

## Catalogue technique : collecte, audit et import

| Outil | Statut et fonction |
|---|---|
| [`collect_technical_data.py`](collect_technical_data.py) | Actuel : collecte individuelle Motoplanète, reprise et conservation des détails |
| [`monitor_technical_collection.py`](monitor_technical_collection.py) | Actuel : vue locale de la collecte ; lit sans modifier son corpus |
| [`collection_terminal.py`](collection_terminal.py) | Actuel : tableaux de suivi dans Zellij |
| [`start_collection_panel.py`](start_collection_panel.py) | Actuel : démarrer ou réutiliser la collecte et son suivi, avec protection contre la veille |
| [`audit_collected_technical_data.py`](audit_collected_technical_data.py) | Actuel : audit d'un snapshot cohérent de collecte |
| [`load_enriched_catalog.py`](load_enriched_catalog.py) | Actuel : import du snapshot enrichi dans PostgreSQL et projection numérique |
| [`validate_technical_catalog.py`](validate_technical_catalog.py) | Actuel : vérifications du corpus local complet, sans modèle |
| [`audit_technical_data.py`](audit_technical_data.py) | Préparation : inventaire hors réseau des fiches conservées |
| [`export_local_technical_data.py`](export_local_technical_data.py) | Préparation : export versionné de candidats techniques Bikez, sans avis |
| [`audit_technical_normalization.py`](audit_technical_normalization.py) | POC : contrôle en lecture seule des identités et unités du pilote |
| [`collect_wikidata_motorcycles.py`](collect_wikidata_motorcycles.py) | POC : inventaire borné d'identités CC0, avec caches ; pas un catalogue technique complet |
| [`collect_technical_data_fast.py`](collect_technical_data_fast.py) | POC comparateur : plusieurs fiches par requête ; limites de conservation documentées |
| [`bench_compare_vs_fiche.py`](bench_compare_vs_fiche.py) | POC comparateur : comparaison contrôlée de collecte sur le même échantillon |

Voir les [règles et limites de collecte](../docs/technical-data-collection.md).

## Chat et validation du catalogue

| Outil | Statut et fonction |
|---|---|
| [`chat_cli.py`](chat_cli.py) | Actuel : entrée terminal du même agent que Gradio ; utilise la configuration du dépôt |
| [`eval_technical_demo.py`](eval_technical_demo.py) | Actuel : essais séquentiels via la vraie API Gradio |
| [`evaluate_jev_routing.py`](evaluate_jev_routing.py) | Actuel : routage, contraintes, preuves SQL et temps ; marque la synthèse sans la lancer en lot |
| [`evaluate_free_chat.py`](evaluate_free_chat.py) | Actuel : dialogues libres via Gradio, puis inspection distincte du routage |
| [`render_chat_public_fixes.py`](render_chat_public_fixes.py) | Bilan HTML du rejeu après corrections des questions libres ; conserve la première passe |
| [`evaluate_enriched_chat.py`](evaluate_enriched_chat.py) | Validation de l'intégration : conservation des fiches, SQL, chat et recherche BGE séparée |
| [`render_brag_video.py`](render_brag_video.py) | Présentation : montage local à partir de captures réelles ; les attentes raccourcies ne mesurent pas la vitesse |

## POC figé SQL, recherche et classification

Ces outils travaillent dans `data/technical/hybrid-poc/` et sur les snapshots
associés. Ils ne constituent pas le prochain benchmark de questions inédites.
Les annotations silver, les références indépendantes et les sorties adaptées
doivent rester distinguées.

| Outil | Fonction |
|---|---|
| [`prepare_hybrid_poc.py`](prepare_hybrid_poc.py) | Figer les fiches, passages et références silver ; fournit aussi des fonctions partagées |
| [`hybrid_poc_retrieval.py`](hybrid_poc_retrieval.py) | SQL et index BGE local isolés |
| [`evaluate_hybrid_poc.py`](evaluate_hybrid_poc.py) | Comparer les classifications Jev, Mistral local et la cascade |
| [`evaluate_hybrid_queries.py`](evaluate_hybrid_queries.py) | Comparer boucle avec outils et routage hybride sur un corpus figé |
| [`report_hybrid_poc.py`](report_hybrid_poc.py) | Produire un rapport à partir de sorties complètes et contrôlées, sans appel de modèle |
| [`enrich_equipment.py`](enrich_equipment.py) | Passes d'enrichissement isolées puis finalisation des décisions avec preuves |
| [`equipment_enrichment_policy.py`](equipment_enrichment_policy.py) | Module de contrôles partagé ; ce fichier n'est pas une CLI |
| [`evaluate_equipment_poc.py`](evaluate_equipment_poc.py) | Petit POC de classification de preuves ; anciens modes de fournisseurs à relire avant usage |

Voir le [rapport du POC](../docs/hybrid-poc-results.md) et la
[décision retenue](../docs/hybrid-workflow-decision.md).

## Ancien corpus Bikez, avis et enrichissements

| Outil | Fonction historique |
|---|---|
| [`run_demo_scrape.py`](run_demo_scrape.py) | Collecte Bikez avec reprise des fiches et discussions |
| [`run_pilot_scrape.py`](run_pilot_scrape.py) | Petit échantillon stratifié Bikez |
| [`load_db.py`](load_db.py) | Charger les JSONL, familles, fiches et avis BGE dans PostgreSQL |
| [`scrape_motoplanete_prices.py`](scrape_motoplanete_prices.py) | Collecter prix France et catégories pour l'ancien catalogue |
| [`load_motoplanete_prices.py`](load_motoplanete_prices.py) | Apparier ces prix aux anciennes lignes du catalogue |
| [`scrape_motoplanete_reviews.py`](scrape_motoplanete_reviews.py) | Collecter les avis français conservés |
| [`load_motoplanete_reviews.py`](load_motoplanete_reviews.py) | Apparier et encoder les avis au niveau famille |
| [`load_nhtsa_recalls.py`](load_nhtsa_recalls.py) | Télécharger et apparier les rappels américains |
| [`load_used_prices.py`](load_used_prices.py) | Télécharger et agréger le snapshot de prix d'occasion de 2022 |
| [`audit_prices.py`](audit_prices.py) | Échantillon d'audit humain des appariements de prix, puis score |
| [`coverage_dashboard.py`](coverage_dashboard.py) | Tableau HTML local de couverture de cet ancien catalogue |

Ces scripts ne prouvent pas l'homologation A2, la disponibilité française, la
fiabilité ni un prix actuel. La conservation de leurs chemins permet de
reproduire les artefacts historiques sans mélanger les périmètres.

## Benchmark technique actuel

[`benchmark_technical_retrieval.py`](benchmark_technical_retrieval.py) prépare
un index isolé, compare BM25/BGE/hybride/reranking et profile l'encodage à la
demande sur le développement. [Rapport du 13 octobre](../docs/technical-retrieval-benchmark-20261013.md)
et [commandes de reproduction](../eval_results/technical/retrieval-benchmark-20261013/README.md).

## Expériences des 14–15 octobre 2026

Ces scripts conservent leurs résultats dans des dossiers datés. Ils ne modifient
pas automatiquement le modèle ni la recherche du chat.

| Outil | Fonction |
|---|---|
| [`compare_mistral_jev.py`](compare_mistral_jev.py) | Comparer les parcours Mistral/Jev ; les modes distants utilisent un budget explicite |
| [`compare_technical_embeddings.py`](compare_technical_embeddings.py) | Comparer BGE-M3, Qwen et E5 sur un sous-ensemble figé |
| [`improve_bge_retrieval.py`](improve_bge_retrieval.py) | Étudier fusion et reranking sur les erreurs annotées |
| [`validate_bge_fusion.py`](validate_bge_fusion.py) | Confirmer la fusion sur un nouveau lot, avec contrôle des pertes de preuves |
| [`train_bge_contrastive.py`](train_bge_contrastive.py) | Préparer, entraîner et évaluer le pilote LoRA local, avec index isolé |
| [`render_bge_finetuning.py`](render_bge_finetuning.py) | Générer l’annexe HTML depuis les résultats vérifiés, sans inférence |
| [`render_sql_rag_benchmark.py`](render_sql_rag_benchmark.py) | Générer le benchmark HTML des modèles et son lien d’annexe |

Rapports et décisions : [index de documentation](../docs/README.md).
Les poids, vecteurs et dépendances optionnelles restent dans les dossiers locaux
ignorés par Git. Les annotations, protocoles et résultats sont versionnés.

## Évaluations de la boucle historique


| Outil | Couche mesurée |
|---|---|
| [`eval_retrieval.py`](eval_retrieval.py) | Recherche d'avis seule, sans générateur |
| [`eval_tool_trajectory.py`](eval_tool_trajectory.py) | Choix et arguments des outils, contrôles déterministes |
| [`eval_constraints.py`](eval_constraints.py) | Contraintes dures des réponses finales et insuffisances de données |

RAGAS se lance depuis `src/bikefinder_rag/eval/run_ragas.py`. Les options
locales et les limites des résultats figurent dans le
[guide d'évaluation](../docs/guides/evaluation.md) et
[`eval_results/README.md`](../eval_results/README.md).

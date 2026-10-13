# Benchmark technique local — 2026-10-13

[Rapport et recommandation](../../../docs/technical-retrieval-benchmark-20261013.md) · [issue #3](https://github.com/maax6/bikefinder-rag/issues/3).

Premier passage indépendant : 10 questions de développement, 50 réservées, quatre méthodes et deux portées. Les trois répétitions servent aux durées, pas à augmenter le nombre de questions. Aucun appel à une API d'inférence du projet, aucune modification du catalogue actif.

## Lire les fichiers

- `holdout-*-firstpass-summary.json` : métriques complètes, durées par étape, P50/P95/max/variabilité, mémoire et limites.
- `holdout-*-firstpass-traces.json` : premier classement de chaque question/méthode, texte source intégral et **toutes les trois mesures de temps**. Les classements identiques des répétitions ne sont pas recopiés ; leur égalité est explicitement indiquée. Les empreintes des JSONL originaux restent enregistrées.
- `dev-*` : contrôles de développement et démarrage, distincts des résultats réservés.
- `questions-dev.json`, `questions-holdout.json`, `author-manifest.json` : formulations, jugements gradués, groupes de preuves, limites, sources et partitionnement. Auteur IA isolé, aucun panel humain. Après cette exécution, ce lot réservé devient un lot de régression.
- `protocol.json`, `evaluation-protocol.json`, `pre-evaluation-freeze.json` : configurations et code figés avant ouverture du réservé.
- `source-manifest.json`, `live-equivalence.json`, `index-manifest.json`, `environment-manifest.json` : provenance du corpus, modèles, fichiers et environnement réellement utilisés ; workspace initial modifié.
- `confidence-analysis.json` : A2, négatifs, couverture et pertes de preuves avant/après reclassement.
- `device-profile-*` : profil de textes du corpus servant au choix MPS/float16/batch32 ; aucune question réservée dans ce choix.
- `lazy-dev-profile.json`, `live-raw-cache-coverage.json` : diagnostic distinct du calcul à la demande sur texte brut et état du cache actif.
- `post-run-live-check.json` : comptes, empreintes sources et neuf vecteurs techniques déjà en cache inchangés après le benchmark.
- `model-license-metadata.json` : licences publiées par BAAI ; lectures de métadonnées web uniquement, aucun texte du corpus envoyé.
- `artifact-manifest.json` : tailles et SHA256 des artefacts de ce dossier, avec empreintes des traces originales.

Les poids, la copie SQLite, les passages d'indexation et les vecteurs sont des caches locaux dans `data/technical/retrieval-benchmark-20261013/`, exclus de Git.

## Reproduire

Dans la racine du projet, avec les deux snapshots de modèles déjà installés :

```sh
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false
BENCH_DIR=data/technical/retrieval-benchmark-20261013
DENSE_SNAPSHOT=/Users/m4ks/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181
RERANK_SNAPSHOT=/Users/m4ks/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e

.venv/bin/python scripts/benchmark_technical_retrieval.py prepare \
  --snapshot "$BENCH_DIR/catalogue.frozen.sqlite3" \
  --out "$BENCH_DIR/index-replay" \
  --dense-model "$DENSE_SNAPSHOT" --reranker-model "$RERANK_SNAPSHOT" \
  --device mps --dtype float16 --batch-size 32

.venv/bin/python scripts/benchmark_technical_retrieval.py evaluate \
  --questions eval_results/technical/retrieval-benchmark-20261013/questions-dev.json \
  --index "$BENCH_DIR/index-replay" --split dev --mode supplied --cold-dev-profile
.venv/bin/python scripts/benchmark_technical_retrieval.py evaluate \
  --questions eval_results/technical/retrieval-benchmark-20261013/questions-dev.json \
  --index "$BENCH_DIR/index-replay" --split dev --mode global --cold-dev-profile
.venv/bin/python scripts/benchmark_technical_retrieval.py evaluate \
  --questions eval_results/technical/retrieval-benchmark-20261013/questions-holdout.json \
  --index "$BENCH_DIR/index-replay" --split holdout --mode supplied
.venv/bin/python scripts/benchmark_technical_retrieval.py evaluate \
  --questions eval_results/technical/retrieval-benchmark-20261013/questions-holdout.json \
  --index "$BENCH_DIR/index-replay" --split holdout --mode global

.venv/bin/python scripts/benchmark_technical_retrieval.py profile-lazy \
  --questions eval_results/technical/retrieval-benchmark-20261013/questions-dev.json \
  --index "$BENCH_DIR/index-replay" --out "$BENCH_DIR/lazy-dev-replay.json"
```

Les chemins de modèles sont ceux de la machine mesurée. Les commandes sont séquentielles : éviter toute autre inférence locale pendant l'évaluation. Le snapshot source original ou une copie d'empreinte identique est requis. Un CPU ou une autre précision constitue une nouvelle configuration, à mesurer séparément. `--resume` continue un premier passage interrompu, sans modifier ses paramètres ni écraser un passage terminé.

Tests : `HF_HUB_OFFLINE=1 BIKEFINDER_JEV_ROUTER=0 RUN_CATALOG_INTEGRATION=0 .venv/bin/python -m pytest -q` → 947 réussis, 8 désactivés.

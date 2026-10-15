# Bikefinder RAG

Un prototype de catalogue moto sourcé pour chercher, compter et comparer des
caractéristiques techniques par **modèle, année et variante**. Il fonctionne
localement sur un Mac M5 / 32 Go, avec SQL, BGE-M3, Jev et Mistral.

## Voir les résultats

- **[Benchmark interactif SQL + RAG](https://maax6.github.io/bikefinder-rag/benchmark.html)** — huit modèles, deux passes, réponses, sources, temps et coûts.
- **[Annexe : fine-tuning de BGE-M3](https://maax6.github.io/bikefinder-rag/benchmark-finetuning.html)** — comparaison avant/après, 156 questions inspectables et erreurs détaillées.

Ces pages se consultent sans compte ni installation.

## Où on en est — 15 octobre 2026

- Le snapshot utilisé contient **11 478 fiches et 105 687 passages techniques**. Le corpus complet, les index et les modèles restent locaux.
- Le chat existant combine Jev, SQL et, lorsque la recherche documentaire est activée, BGE-M3 puis Mistral local. Le nouveau service commun SQL + RAG a été évalué séparément ; son raccordement au chat reste à faire.
- **BGE-M3 d’origine est conservé.** La fusion ajustée et le pilote LoRA améliorent certains scores, mais perdent des preuves utiles. Aucun des deux n’est activé dans le chat.

Le fine-tuning porte sur 512 questions d’apprentissage. En recherche hybride,
la couverture complète passe de 60 à 61 sur 64 questions inédites et de 66 à 78
sur 92 anciens cas, avec neuf questions qui perdent une preuve. Ces chiffres
mesurent la recherche de passages, pas la qualité finale des réponses du bot.

## Lancer le chat local

Prérequis : Python 3.11+, Docker Compose, Ollama et le catalogue importé.
Suivre le **[guide d’installation](docs/guides/local-setup.md)** pour préparer
les données, les modèles et la configuration, puis :

```bash
AGENT_BACKEND=ollama BIKEFINDER_JEV_ROUTER=1 BIKEFINDER_JEV_RAG=1 PYTHONPATH=src \
  .venv/bin/python src/bikefinder_rag/app.py
```

Ouvrir <http://127.0.0.1:7860>. Un clone seul ne contient pas le corpus complet.

## Prochaine étape : tester le parcours complet

Le **[plan de validation](docs/phase-test-20261015.md)** sépare les régressions
connues, les nouvelles questions et le raccordement au chat. Il faut mesurer
les réponses réellement produites, leurs preuves, les délais et les coûts avant
de retenir une nouvelle configuration. Le [bilan de la phase d’expérimentation](https://github.com/maax6/bikefinder-rag/issues/4)
est conservé dans l’issue #4.

[Documentation](docs/README.md) · [Architecture](docs/reference/architecture.md) ·
[Scripts](scripts/README.md) · [Évaluations et tests](docs/guides/evaluation.md)

Validation du 15 octobre : **1 201 tests réussis, 8 ignorés**. Les tests logiciels
ne constituent pas un score de précision du chatbot.

Code sous [licence MIT](LICENSE). Les données tierces conservent les conditions
de leurs sources ; la licence du code n’accorde pas leur redistribution.

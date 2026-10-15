# Bikefinder RAG

Un prototype de catalogue moto sourcé pour chercher, compter et comparer des
caractéristiques techniques par **modèle, année et variante**. Il fonctionne
localement sur un Mac M5 / 32 Go, avec SQL, BGE-M3, Jev et Mistral.

## Voir les résultats

- **[Bilan du vrai chat : avant / après](https://maax6.github.io/bikefinder-rag/benchmark-chat-20261015.html)** — réponses, erreurs, temps et prix moyen, avec BGE-M3 d’origine.
- **[Benchmark interactif SQL + RAG](https://maax6.github.io/bikefinder-rag/benchmark.html)** — huit modèles, deux passes, réponses, sources, temps et coûts.
- **[Annexe : fine-tuning de BGE-M3](https://maax6.github.io/bikefinder-rag/benchmark-finetuning.html)** — comparaison avant/après, 156 questions inspectables et erreurs détaillées.

Ces pages se consultent sans compte ni installation.

## Où on en est — 15 octobre 2026

- **11 478 fiches et 105 687 passages techniques** ; corpus complet, index et modèles locaux.
- Le chat corrige les valeurs perdues, maximums, moyennes — dont les prix de catalogue France — et suivis de conversation. **25/36 → 36/36 réponses satisfaisantes** sur le lot de régression ; **15/15 tours supplémentaires**, sans régression de contenu observée sur les 42 tours comparables. Relecture par le même agent, sans validation humaine indépendante.
- **BGE-M3 d’origine est conservé.** Fusion ajustée et LoRA restent isolés à cause de pertes de preuves. Le service commun SQL + RAG a été évalué séparément ; son raccordement au chat reste à faire.

## Lancer le chat local

Prérequis : Python 3.11+, Docker Compose, Ollama et le catalogue importé.
Suivre le **[guide d’installation](docs/guides/local-setup.md)** pour préparer
les données, les modèles et la configuration, puis :

```bash
AGENT_BACKEND=ollama BIKEFINDER_JEV_ROUTER=1 BIKEFINDER_JEV_RAG=1 PYTHONPATH=src \
  .venv/bin/python src/bikefinder_rag/app.py
```

Ouvrir <http://127.0.0.1:7860>. Un clone seul ne contient pas le corpus complet.

## Prochaine étape

Faire relire un nouveau lot indépendant, améliorer les avertissements, la
clarification XJ6 A2 et les délais de rédaction. Le **[plan de validation](docs/phase-test-20261015.md)**
détaille la suite ; le [bilan des expérimentations](https://github.com/maax6/bikefinder-rag/issues/4)
reste dans l’issue #4.

[Documentation](docs/README.md) · [Architecture](docs/reference/architecture.md) ·
[Scripts](scripts/README.md) · [Évaluations et tests](docs/guides/evaluation.md)

Validation : **1 232 tests réussis + 11 tests SQL réussis séparément**.
Les tests logiciels ne constituent pas un score de précision du chatbot.

Code sous [licence MIT](LICENSE). Les données tierces conservent les conditions
de leurs sources ; la licence du code n’accorde pas leur redistribution.

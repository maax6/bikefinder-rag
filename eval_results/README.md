# Résultats d'évaluation

Les résultats publiés des deux couches d'évaluation du projet — la convention
du repo est « les résultats sont commités, les caches ne le sont pas ».

| Dossier | Couche | Ce qui est mesuré |
|---|---|---|
| [`retrieval/`](retrieval/) | 1 — retrieval seul, **aucun LLM** | La recherche sémantique pgvector + BGE-M3 fonctionne-t-elle vraiment ? |
| [`trajectory/`](trajectory/) | 1,5 — tool calls, **aucun juge LLM** | Le modèle choisit-il les bons outils avec les bons arguments ? (prédicats déterministes sur les appels enregistrés) |
| [`ragas/`](ragas/) | 2 — agent complet | Qualité des réponses finales (faithfulness, answer relevancy) notée par deux juges indépendants |

Chaque dossier contient un README qui publie les chiffres et pointe vers le
document de preuve hébergé sur GitHub Pages :

- [Preuve de fonctionnement — recherche sémantique](https://maax6.github.io/bikefinder-rag/preuve-retrieval.html)
- [De la page web au score RAGAS — le pipeline](https://maax6.github.io/bikefinder-rag/pipeline-et-evaluation.html)
- [Un agent RAG sans framework — la méthode](https://maax6.github.io/bikefinder-rag/methode-sans-langchain.html)

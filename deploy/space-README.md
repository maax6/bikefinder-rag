---
title: Bikefinder RAG
emoji: 🏍️
colorFrom: gray
colorTo: red
sdk: docker
app_port: 7860
pinned: false
---

# 🏍️ Bikefinder RAG

Agentic RAG over **32,395 motorcycles (1894–2024)** and **107,952 embedded
owner comments**, scraped from bikez.com and enriched with French launch
prices (motoplanete), NHTSA safety recalls and an indicative 2022
used-price cote.

Ask in any language — the embeddings (BGE-M3) are multilingual, so French
questions retrieve English forum comments. **Bring your own
[Anthropic](https://console.anthropic.com/) or
[OpenRouter](https://openrouter.ai/keys) API key** (detected by its
prefix): it stays in your browser session and is never stored.

- Source, methodology and layered evaluations (retrieval proof, tool-call
  trajectories, RAGAS): [github.com/maax6/bikefinder-rag](https://github.com/maax6/bikefinder-rag)
- Proof documents: [maax6.github.io/bikefinder-rag](https://maax6.github.io/bikefinder-rag/preuve-retrieval.html)

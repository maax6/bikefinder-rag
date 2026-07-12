# Retour critique et opérationnel — Bikefinder RAG

*Revue faite par Claude (Fable 5) le 12 juillet 2026 : lecture complète du code
(loop, tools, eval, scraper, load_db, README, golden questions) + vérifications
directes contre la base Postgres.*

## Ce qui tient vraiment la route

Le projet a des qualités rares pour un premier RAG de portfolio :

- La boucle agentique à la main (pas de LangChain) est lisible et défendable en entretien.
- Le SQL est paramétré partout — le LLM n'écrit jamais de SQL. C'est le bon réflexe sécurité.
- Le README est honnête sur les limites (prix, couverture des avis).
- Les choix sont argumentés (BGE-M3 multilingue, scraping éthique documenté).
- Il y a des tests sur le scraper avec fixtures HTML.
- Le retrieval fonctionne, prouvé indépendamment du LLM (voir `eval_retrieval_report.json`
  et le document de preuve).

C'est au-dessus de la moyenne des projets "RAG demo" qu'on voit passer.

## Les problèmes réels, par ordre de gravité

### 1. Le jeu de questions d'éval teste des motos qui ne sont pas dans la base

`golden_questions.json` demande le Honda X-ADV et le Yamaha TMAX (narrative-1,
narrative-3, hybrid-2) — vérifié : **aucun des deux n'est dans les 206 motos
chargées**. Le X-ADV existe comme fixture de test du scraper, mais pas dans le
sample pilote. Si tu fais tourner RAGAS aujourd'hui, 3 questions sur 12 testent
la capacité du bot à dire "je ne sais pas", pas le RAG.

### 2. RAGAS n'a jamais tourné

Pas de `ragas_results.json` nulle part. Pour un portfolio, une éval qui existe
en code mais sans résultats publiés, c'est pire que pas d'éval : ça se voit en
30 secondes et ça pose la question "pourquoi il ne l'a pas lancée ?". Il faut
des chiffres dans le README.

### 3. Les commentaires sont rattachés à la mauvaise année — piège de crédibilité en démo

Le smoke test l'a montré : un commentaire daté **2008** attaché à une
**Pulsar N250 2023** (le forum bikez est partagé par famille de modèle, pas par
fiche année). Le bot répond "voici ce que disent les propriétaires de la N250
2023" avec un avis qui parle d'une Pulsar de 2007. Un recruteur motard le
remarquera. Même cause pour les 103 groupes de doublons (même fil sur
CB 250 K1 et CB 250 N).

### 4. Le sample pilote est invendable en démo

- 44 % des avis sont du Harley-Davidson.
- 94 motos sur 206 n'ont aucun avis.
- Seulement 45 motos post-2015.
- **Aucune des motos que quelqu'un taperait spontanément** (MT-07, Z650, CB500, TMAX…).

Un visiteur pose 3 questions, obtient 3 "pas de données", et conclut que ça ne
marche pas — alors que le retrieval est bon. L'échantillonnage stratifié par
catégorie × décennie × marque était rigoureux statistiquement mais anti-démo :
il fallait stratifier par *popularité*.

### 5. `filter_specs` ne peut pas répondre à ses propres questions d'éval

`ORDER BY year DESC` est codé en dur. La question struct-3 ("the lightest
enduro bike") est impossible à répondre correctement : le tool renvoie les 10
plus récentes, et le LLM devra prétendre que la plus légère de cette liste
tronquée est la plus légère de la base. Il manque un paramètre `order_by`.

### 6. La boucle agent n'a aucun garde-fou

- `while True` sans plafond d'itérations → un modèle qui boucle sur des tool
  calls = coût infini sur la clé du visiteur.
- Aucun try/except autour de l'appel API → une clé invalide = stacktrace brute
  dans Gradio.
- `max_tokens=1024` peut tronquer silencieusement.
- L'historique Gradio grossit sans limite.

Pour une démo publique BYOK, c'est le minimum à blinder.

### 7. Pas de chunking du tout

Un commentaire = un embedding, avec un max constaté de 65 535 caractères —
BGE-M3 tronque silencieusement au-delà de sa fenêtre, donc la fin des longs
commentaires est invisible à la recherche, et un pavé de 65k chars balancé
dans le contexte du LLM coûte cher pour rien.

## Pour en faire un vrai « moto génie » — roadmap priorisée

### P0 — crédibilité de la démo (avant de montrer à qui que ce soit)

1. Re-scraper un sample orienté démo : les ~100 motos les plus discutées + les
   best-sellers récents, pas un échantillon statistique.
2. Rattacher les avis à la *famille* de modèle (nouvelle table ou colonne
   `model_family`), dédupliquer, et toujours afficher la date du commentaire
   dans les réponses.
3. Ajouter `order_by` à `filter_specs`, plafonner la boucle (max 8 itérations),
   try/except API avec message propre.
4. Corriger les golden questions pour matcher la base, lancer RAGAS +
   `scripts/eval_retrieval.py`, publier les deux dans le README.

### P1 — qualité retrieval

- Chunker les longs commentaires (~500 tokens, avec overlap).
- Recherche hybride BM25 + vecteur (le test « fiabilité » à 1.2× de lift montre
  la limite du pur vectoriel sur les thèmes diffus), et déduplication au moment
  du retrieval.
- Citations cliquables vers la page bikez dans l'UI — c'est ce qui transforme
  "un chatbot" en "un outil auquel on fait confiance".

### P2 — le différenciant produit (ce qui parle à un employeur français)

- **Filtre permis A2** : 35 kW / 47,5 ch max — la donnée `power_hp` existe
  déjà, c'est trois lignes dans `filter_specs` et c'est LA question que se pose
  tout jeune motard français. Aucun concurrent grand public ne le fait bien.
- Profil utilisateur (taille → `seat_height_mm`, usage ville/duo/voyage)
  injecté dans le system prompt.
- Prix : plutôt que les marketplaces bloquées, viser une cote officielle ou un
  dataset licencié — et le documenter comme c'est déjà fait pour le reste.

## Conclusion

Le fond est sain — l'architecture et les réflexes sont bons. Ce qui sépare ce
POC d'un portfolio convaincant, ce n'est pas plus de features, c'est :

1. **des chiffres d'éval publiés**,
2. **un sample de données qui donne envie**,
3. **une démo qui ne peut pas planter**.

Dans cet ordre.

# Catalogue complet enrichi et raccordé au chatbot

État vérifié le 12 octobre 2026. Les résultats sont dans
[l’évaluation finale](../eval_results/technical/enriched_chat_final_20261012.json),
[le test de l’interface](../eval_results/technical/enriched_chat_ui_20261012.json)
et [la passe complète](../eval_results/technical/equipment_enrichment_full_20261012.json).

> Ce document décrit la version du 12 octobre. Le [routage Jev du 13 octobre](jev-routing-natural-questions.md) est désormais actif : il remplace le recours systématique au générateur sur les formulations non reconnues. Les mesures ci-dessous restent celles de la version historique.

## Collecte et exceptions

Les 11 479 URL découvertes sont traitées : **11 478 fiches réelles validées**
et une fiche fictive exclue du catalogue réel, conservée en archive.
La CFMoto 800 MT Explore 2025 a été récupérée après son échec DNS.
Les pages Benda Dark Flag 950 et Ducati Desmo450 Sm demandées en 2026
redirigent vers 2027 : leur identité 2027 est acceptée, sans reconstruire une
fiche 2026. Les enregistrements et preuves de redirection restent inchangés.
La page Yaiba Kusanagi CT-3X 2078 se présente comme une moto de Cyberpunk 2077.

Une sauvegarde SQLite précède ces décisions. Leur journal est conservé dans
`data/technical/motoplanete/final-resolution.json`. Le collecteur est terminé.

## Enrichissement intégral

Le nouveau snapshot contient 11 478 objets, 411 954 lignes techniques et
105 687 passages. Les **6 168 fiches avec autonomie** gardent leur texte
original, y compris « calculée mais non vérifiée ».

Les 26 599 couples fiche–équipement représentent 1 080 entrées distinctes.
Les caches de la première passe ne sont réutilisés qu’avec le même modèle et
les mêmes consignes. La passe complète ajoute **290 appels Jev et 46 appels
Mistral**, sans erreur. Le coût des nouveaux appels Jev renvoyé par OpenRouter
est **0,008311548 USD**. Les fichiers complets contiennent aussi les réponses
réutilisées : 675 entrées Jev et 334 Mistral, à ne pas présenter comme des appels
tous nouvellement réalisés.

Les règles de preuve établissent 25 994 décisions littérales. **163 décisions,
soit 52 entrées distinctes, restent à examiner** ; 442 cas évalués ne donnent
pas de preuve technique cible. Aucune décision finale de ce lot ne nécessite
un modèle après application des règles : les modèles servent ici au contrôle,
pas à compléter les inconnus.

L’export SQL contient 31 435 lignes d’équipement : 25 011 de série, 975 en
option, 8 absences explicites et 5 441 inconnues. Ce total inclut les statuts
ABS inconnus ajoutés aux fiches sans preuve ABS. Une absence de ligne pour
un autre équipement reste également inconnue à la recherche.

Sur les annotations présentes dans ce nouveau lot : 64/64 conformités dans
l’audit ciblé et 52/55 références historiques. Les trois désaccords historiques
restants sont les groupes optionnels à portée incertaine, conservés inconnus.
Des contrôles négatifs ont changé lors de la sélection du nouveau snapshot :
les dénominateurs ne sont pas ceux de la première passe. Ces audits ciblés ne
sont pas une mesure représentative de précision du catalogue.

## Chemin réellement connecté

`scripts/load_enriched_catalog.py` importe atomiquement le snapshot SQLite
dans des tables PostgreSQL distinctes : fiches, équipements, passages et
cache de vecteurs. Il conserve les autres données du chatbot. Une comparaison
complète confirme que les 11 478 enregistrements importés sont identiques à
leur export et que leurs empreintes correspondent.

Le chatbot expose trois nouveaux outils : filtrage du catalogue enrichi,
fiche exacte par modèle/millésime et recherche sémantique technique BGE-M3.
Les outils historiques restent disponibles comme source distincte ; leurs
mesures numériques anciennes ne deviennent pas des mesures Motoplanète.
Les filtres d’équipement distinguent série, option, absence explicite et inconnu.
Un filtre de marché France reste indisponible : un prix français n’établit pas
le marché technique d’une variante.

BGE-M3 fonctionne localement dans une identité et un millésime explicites.
Les vecteurs sont calculés à la première recherche de cette fiche, puis
conservés dans PostgreSQL par texte exact. **Les 105 687 passages sont importés,
mais tous leurs vecteurs ne sont pas précalculés.** Une recherche ambiguë ne
se rabat pas sur une autre variante ou année. Cette première intégration ne
fait pas encore de recherche sémantique globale entre toutes les motos.

Les formulations reconnues sans ambiguïté concernant l’ABS d’un millésime,
une autonomie ou une comparaison d’autonomies reçoivent une réponse SQL
avec sources. Le chemin est conservateur : des contraintes supplémentaires
ou des formulations non reconnues vont à l’agent Mistral. Jev n’est pas appelé
à chaque message : il a contrôlé l’enrichissement ; son routage conversationnel
général reste celui envisagé dans le POC, pas une fonctionnalité ajoutée ici.

## Mesures et ajustements

| Cas final mesuré | Temps du backend |
|---|---:|
| Liste ABS 2000 | 14 ms |
| Compte ABS de série 2025 | 24 ms |
| Liste ABS en option 2025 | 9 ms |
| Autonomie BMW R 1150 GS 2000 | 5 ms |
| ABS et autonomie CFMoto 800 MT Explore 2025 | 3 ms |
| Comparaison des deux autonomies avec qualifications | 10 ms |
| Fiche Ducati 2026 absente, réponse par Mistral | 17,1 s |
| BGE-M3, premier chargement du processus | 8,4 s |
| BGE-M3, modèle et vecteurs en cache | 88 ms |

Après chargement de la version finale, le test à travers l’API de l’interface
Gradio prend **169 ms** pour ABS 2000 et **55 ms** pour la comparaison d’autonomies.
Les durées backend n’incluent pas le navigateur, et les durées BGE ne sont pas
des durées de réponse complète du chatbot.

Les essais intermédiaires ont révélé une limite importante : une comparaison
générée prenait 154 s, puis 79 s avec des preuves bornées. Mistral y affirmait
à tort que les deux fiches provenaient de catalogues différents. La variante
à 79 s est marquée en échec après revue substantielle, malgré ses contrôles
initiaux de présence de valeurs corrects. La version finale de ce cas est
une comparaison SQL déterministe conservant les qualifications des sources.
Ce résultat ne démontre pas que Mistral est fiable sur toutes les questions
complexes ; il réduit le besoin de génération sur les faits structurés.

**508 tests passent**, avec les tests PostgreSQL dans un schéma isolé.
La vérification réelle comprend six comptes SQL par millésime, sept réponses
du chatbot, deux recherches BGE et un appel de l’interface. Ce jeu limité
n’est pas un taux d’erreur général du chatbot.

## Reproduction locale

```bash
PYTHONPATH=src .venv/bin/python scripts/load_enriched_catalog.py \
  --source data/technical/enrichment-full-20261012/pass2/catalogue.enriched.sqlite3
BIKEFINDER_CATALOG_FAST_PATH=1 PYTHONPATH=src .venv/bin/python src/bikefinder_rag/app.py
PYTHONPATH=.:src RUN_CATALOG_INTEGRATION=1 .venv/bin/pytest -q
```

Le chemin SQL direct est activé dans le `.env` local. Aucun push ou déploiement
public n’a été effectué. Les prochaines améliorations concernent les 52 entrées
ambiguës, un jeu de questions indépendant, le routage général et les mesures
normalisées/variantes/marchés ; elles ne bloquent pas cette intégration locale.

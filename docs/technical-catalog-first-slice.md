# Premier parcours technique — 10 octobre 2026

Étape 2 de [l'issue de refonte](https://github.com/maax6/bikefinder-rag/issues/2),
à partir de `23cf58a`. Le [cadrage](technical-catalog-refactor.md) reste la référence.
Le parcours a été activé dans la démo locale le 10 octobre, après autorisation
du redémarrage et des inférences. Les contrôles SQL, tests simulés et essais du
vrai modèle sont distingués ci-dessous.

## Comportement préparé

- Deux outils proposés : `filter_specs` et `get_bike_details`. Les avis sont
  bloqués à l'exécution, même si le modèle invente cet appel. Une conversation
  ancienne contenant un appel d'avis est écartée du contexte technique.
- Une fiche exige un millésime explicite. Une comparaison simple récupère
  séparément les deux fiches d'une même année. Les variantes restent distinctes ;
  un nom exact est préféré à une correspondance partielle.
- Les outils conservent les URL, dates de collecte, libellés, unités et
  qualificatifs des mesures brutes. Les valeurs numériques absentes restent
  nulles. Les placeholders vides ou `Loading...` ne deviennent pas des valeurs.
- Les listes sont bornées à vingt fiches ; les comptes portent sur toutes les
  fiches correspondantes du catalogue. Une recherche de modèle ambiguë retourne
  au plus trois fiches et signale les résultats supplémentaires. Il n'y a pas
  encore de pagination ni de promesse d'exhaustivité du marché.
- Les arguments mal typés, bornes contradictoires, tris invalides et filtres
  inconnus sont rejetés avant SQL. Les alias connus restent explicitement
  signalés. Aucun filtre ABS/couleur n'est ajouté dans cette étape.
- Prix, calcul d'éligibilité A2 et contexte de famille ne sont plus proposés
  dans le parcours technique. Le code de recherche d'avis et le contexte de
  famille restent accessibles aux appels Python avec un opt-in explicite.
  Les corpus restent conservés.

## Validation effectuée

Le 10 octobre 2026 : **161 tests passent en 7,21 s**, compilation des Python
modifiés et `git diff --check` réussis. La relecture indépendante du code et du
cadrage n'a trouvé aucun problème bloquant. Le contrat de libellés bruts partagé
entre outils et scraper pourra être centralisé pendant la normalisation.

Les tests passent par `run_agent`, le vrai dispatch des outils et des curseurs
simulés. Ils vérifient les preuves transmises, les millésimes, variantes,
inconnues et restrictions ; les réponses HTTP du modèle et son texte final
sont des fixtures. Ils **ne mesurent pas la qualité de génération**.

Dix contrôles des outils ont aussi passé sur PostgreSQL, dans une transaction
`READ ONLY`, sans Ollama ni embeddings. Le catalogue observé contient toujours
32 395 fiches, de 1894 à 2024. Le
[rapport daté](../eval_results/technical/catalog_tools_20261010T002429.727695Z.json)
conserve les arguments, résultats, preuves brutes et empreintes du code utilisé.

```bash
.venv/bin/python -m pytest -q
# Nécessite le corpus complet audité et PostgreSQL déjà disponible.
PYTHONPATH=src .venv/bin/python scripts/validate_technical_catalog.py
```

Le vérificateur n'importe aucun corpus et n'appelle aucun modèle. Il écrit un
nouveau rapport daté ; `--output` permet de choisir son chemin. Ses exemples
attendent les fiches du corpus complet, pas seulement le petit corpus pilote.

## Validation avec le modèle local

Gradio a été redémarré sur `http://127.0.0.1:7860/`, avec le backend Ollama
explicitement choisi. Le conteneur PostgreSQL existant était arrêté ; il a
été démarré sur son volume conservé. Le catalogue contient toujours 32 395
fiches, de 1894 à 2024. Aucun réimport ni application de schéma n'a eu lieu.

Les essais utilisent Ollama **0.32.15** et le modèle déjà installé
`mistral-small3.2:latest`, 24B Q4_K_M, digest
`5a408ab55df5c1b5cf46533c368813b30bf9e4d8fc39263bf2a3338cfa3b895b`.
Le contexte configuré est de 16 384 tokens, le budget coopératif de 180 s.
Les inférences sont séquentielles, sans juge distant ni téléchargement.

Une première réponse affichait correctement les valeurs demandées, mais
ajoutait à tort vitesse et freinage parmi les données inconnues, alors que
ces champs existent dans `raw_specs`. Le prompt exige maintenant les seuls
champs demandés, une vérification des libellés bruts et des inconnues placées
dans les cellules correspondantes. Un autre essai transformait une fiche
absente en affirmation d'inexistence du modèle ; le prompt distingue désormais
absence dans le catalogue et absence sur le marché. Le
[premier rapport](../eval_results/technical/live_gradio_20261010.json) garde
ces défauts observés et leur relecture, sans les masquer comme des succès.

Après correction et redémarrage, les cas sont rejoués via le vrai `/chat`
Gradio, avec une session neuve par cas : fiche sourcée avec poids sec,
comparaison Bandit N / ER-5 de 2000, couple absent, année manquante, fiche 2025
absente, recherche ABS non prise en charge, date de lancement non documentée
et avis différés. Les preuves attendues sont lues séparément en SQL `READ ONLY`.
Les [deux premiers cas](../eval_results/technical/live_gradio_20261010T024831.474990Z.json)
et les [six suivants](../eval_results/technical/live_gradio_20261010T025154.125390Z.json)
conservent réponses, erreurs éventuelles, durées et empreintes du code.
Cette seconde série révèle encore un mauvais choix d'outil sur le couple
absent et deux formulations trop générales sur équipements et millésime.
La [trace de diagnostic](../eval_results/technical/missing_torque_trace_20261010.json)
reproduit un `filter_specs(model=...)` rejeté, transformé à tort en fiche
absente. Le prompt précise désormais le routage vers `get_bike_details`, la
distinction erreur/absence et le maintien d'une fiche dont un champ est inconnu.
Il distingue également filtre ABS indisponible et informations brutes possibles,
ainsi que millésime du catalogue et année réelle de fabrication.
Le [rejeu des huit cas](../eval_results/technical/live_gradio_20261010T025614.784488Z.json)
utilise ces règles et le vérificateur borné ; les observations de relecture
sont enregistrées par cas, sans transformer ce petit jeu en score général.
Sept cas respectent leurs contraintes documentaires ; le cas sans année
choisit encore 2000. Cette régression montre que le prompt seul ne suffit pas
à empêcher un millésime inventé.

Une protection de provenance est donc appliquée aux appels `get_bike_details`
avant l'exécution de tout leur lot, dans les trois backends. Le millésime doit
être fourni dans une formulation datée (`en/de/in 2000`, `année`, `millésime`,
`year`) ou une réponse numérique seule ; à défaut, le dernier millésime explicite
de l'utilisateur peut servir au suivi. Plusieurs années héritées demandent
une clarification. Les nombres des noms de modèles et les blocs de résultats
d'outils ne deviennent pas des dates. Une clarification directe conserve la
question et l'historique achevé, sans les traces d'outils du tour rejeté.

Cette règle numérique reste volontairement limitée : années écrites en lettres
et raccourcis comme « Bandit 2000 » demandent une date explicite ; une plage
autorise ses bornes, et n'associe pas automatiquement chaque année à un modèle.
Elle contrôle les appels de fiches, pas chaque affirmation du texte généré.
Les trois fournisseurs sont couverts par les tests simulés ; seul Ollama est
rejoué réellement ici.

La [conversation réelle après correction](../eval_results/technical/live_year_conversation_20261010.json)
vérifie « puissance de la Bandit N ? » → clarification → « 2000 » → puissance
sourcée → « et son poids à sec ? » → 214 kg, avec la même fiche de 2000.
Un premier tour a aussi produit la clarification directe du garde. Le client
de test transmet ensuite les blocs d'historique renvoyés par Gradio ; une
première tentative au format texte ancien avait échoué avant le callback.
La réponse à « 2000 » ajoute des caractéristiques documentées non demandées :
les valeurs sont justes, mais la concision prescrite n'est pas encore garantie.

Le [test de reprise](../eval_results/technical/live_retry_20261010.json)
induit un timeout HTTP réel avec un budget de 0,01 s, puis appelle « réessaie »
avec le budget normal : état incomplet vide, question initiale réutilisée,
appel `get_bike_details` et réponse sourcée terminée. Il appelle directement
le même callback que Gradio pour capturer les requêtes et outils ; ce cas
ne teste pas le transport Gradio et n'est pas un incident naturel de latence.

```bash
# Démo, PostgreSQL et Ollama déjà démarrés ; un seul essai à la fois.
.venv/bin/python scripts/eval_technical_demo.py
# Ou un sous-ensemble :
.venv/bin/python scripts/eval_technical_demo.py --case sheet --case missing_year
```

Le script enregistre les sorties ; la vérification du texte reste manuelle.
La télémétrie du client est désactivée. L'attente de résultat Gradio est bornée
à 240 s par défaut (`--gradio-timeout-seconds`) ; une erreur arrête la série.
Une annulation est tentée mais ne prouve pas l'arrêt du traitement serveur :
vérifier celui-ci avant un autre essai. Ce délai n'est pas une limite globale
de durée du script ou une garantie d'interruption des outils en cours.
Il n'expose pas les traces internes du chat via l'API Gradio. Ces essais
ponctuels ne constituent ni un score global, ni le protocole de comparaison
des modèles à trois passages. Les corrections de prompt réduisent les erreurs
observées mais ne garantissent pas toutes les générations futures.
La vérification finale du dépôt compte **314 tests passant en 6,67 s**,
compilation réussie et `git diff --check` propre.

## Limites et suite

Les colonnes existantes gardent leurs limites : mélange poids sec/tous pleins,
convention de puissance à valider, identité historique imparfaite, variantes et
marchés parfois regroupés, catégories potentiellement contradictoires. Le
prompt impose les libellés bruts, l'abstention et l'absence de calcul de rapport
puissance/poids à partir des colonnes héritées ; la normalisation versionnée de
l'étape 3 devra fournir les garanties au niveau des données.

La recherche ABS à l'échelle d'un millésime, les couleurs normalisées, l'index
technique et la comparaison des modèles locaux restent les étapes suivantes.

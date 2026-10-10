# Premier parcours technique — 10 octobre 2026

Étape 2 de [l'issue de refonte](https://github.com/maax6/bikefinder-rag/issues/2),
à partir de `23cf58a`. Le [cadrage](technical-catalog-refactor.md) reste la référence.
Le parcours est préparé et vérifié sur disque ; son activation et sa validation
avec le modèle dans la démo restent différées jusqu'au redémarrage autorisé.

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

## Validation restante et limites

Le processus Gradio existant a été laissé ouvert. Il n'a pas chargé ces
changements. Aucun redémarrage, téléchargement de modèle, benchmark, réimport
de données ou push n'a été effectué pour cette étape.

Après autorisation de redémarrage, rejouer d'abord :

1. « Donne la fiche technique de la Suzuki GSF 1200 N Bandit de 2000, avec
   les unités, les sources et les données inconnues. »
2. « Compare la Suzuki GSF 1200 N Bandit et la Kawasaki ER-5 Twister de 2000
   dans un tableau : cylindrée, puissance, couple et poids, avec les sources. »
3. Une fiche inexistante et une demande sans année : vérifier l'abstention ou
   la clarification, puis une relance après échec avec les protections déjà
   préparées avant cette reprise.

Vérifier réellement que chaque affirmation provient de la bonne fiche, que les
sources sont citées et qu'aucune inconnue n'est complétée. Aucun gain de latence
ou score de qualité n'est établi à ce stade.

Les colonnes existantes gardent leurs limites : mélange poids sec/tous pleins,
convention de puissance à valider, identité historique imparfaite, variantes et
marchés parfois regroupés, catégories potentiellement contradictoires. Le
prompt impose les libellés bruts, l'abstention et l'absence de calcul de rapport
puissance/poids à partir des colonnes héritées ; la normalisation versionnée de
l'étape 3 devra fournir les garanties au niveau des données.

La recherche ABS à l'échelle d'un millésime, les couleurs normalisées, l'index
technique et la comparaison des modèles locaux restent les étapes suivantes.

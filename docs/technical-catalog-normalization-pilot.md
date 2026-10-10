# Pilote d'identité et de mesures — 10 octobre 2026

Première partie de l'étape 3 du [cadrage](technical-catalog-refactor.md).
Le module `catalog` produit un candidat de migration versionné
`technical-catalog-v1` à partir d'une fiche conservée. Il ne modifie ni le
corpus ni PostgreSQL ; les outils de la démo utilisent encore les colonnes
héritées et leurs libellés bruts.

## Identité conservatrice

Les identifiants de marque, modèle complet, millésime et variante sont
déterministes. Ils normalisent casse, composition Unicode et espaces ;
ponctuation, numéros et suffixes restent significatifs. Une Bandit N n'est
pas fusionnée avec une Bandit S. Les caractéristiques d'une année ne sont
jamais transférées à une autre.

Le découpage utilise le plus long préfixe exact d'un vocabulaire sourcé :
liste de marques de la fixture Bikez conservée, plus Royal Enfield documenté
par son site officiel. Les provenances sont dans `catalog/brands.json`.
Le scraper utilise aussi les options de marque explicites de la page.
Une marque non reconnue conserve son libellé et un statut `needs_review`.
La correction d'une marque composée est visible, avec l'identité brute.
Enfield et Royal Enfield restent distincts.

Marché et variante nécessitent un libellé explicite. Un suffixe du modèle
ne devient pas automatiquement une variante. Les divergences de noms,
millésimes ou libellés explicites produisent des avertissements et nécessitent
une revue. Ce contrat ne prétend pas résoudre toute la nomenclature historique.

## Mesures avec preuves

Chaque champ contient valeur, unité, nature, statut, libellé et valeur bruts,
URL, date de collecte et, en cas de conversion, facteur et référence.
Les huit champs sont cylindrée, poids sec, poids tous pleins, poids sans type,
puissance en kW, couple, hauteur de selle et vitesse maximale.

Les valeurs viennent exclusivement des libellés bruts documentés. Les anciennes
colonnes numériques sont conservées pour audit, sans compléter les inconnues.
Poids sec et tous pleins restent séparés. Une valeur propre à une option ou
configuration, un qualificatif contradictoire ou un alias substantiel non
interprétable empêche de publier un scalaire général. Les contradictions entre
valeurs interprétables ont un statut `conflict` ; les preuves restent visibles.

Les conversions utilisent des facteurs explicites et des références NIST/BIPM
et européennes conservées dans les preuves. `HP`, `bhp` ou `CV` seuls restent
ambigus ; un kW explicite est utilisable, et `PS`/`ch` explicitement métriques
ont leur conversion documentée. Les arrondis de deux unités d'une même valeur
sont tolérés selon leur précision affichée. Aucun rapport puissance/poids
n'est calculé. Une performance reste de nature non précisée si la fiche ne
documente pas une annonce ou une mesure.

## Audit et vérification

Le [rapport final](../eval_results/technical/normalization_pilot_20261010T025140.674222Z.json)
porte sur **20 fiches choisies par strates**, dans le catalogue de 32 395 fiches.
Il contient les enregistrements bruts complets, candidats, statuts, empreintes
du code et de chaque fiche. Préservation intégrale et déterminisme passent.
Les identités comptent 13 normalisées, 4 découpages corrigés et 3 à examiner
(Hildebrand-Wolfmüller, millésimes 1894–1896). Ce n'est pas un taux de couverture
du corpus. La strate de poids générique ne trouve aucune fiche dans ce petit
échantillon ; les fixtures vérifient ce cas séparément.

Les tests protègent marques composées, numéros, variantes, années, conflits,
absence de fallback numérique, unités, qualificatifs conditionnels et
préservation brute. Deux relectures indépendantes ont conduit à corriger les
qualificatifs de poids contradictoires, le libellé `Model`, les alias non
interprétables et les mentions d'option. **314 tests passent en 6,67 s** sur
l'ensemble du dépôt, y compris les protections du vérificateur Gradio et de
provenance du millésime. La
compilation réussit. Un paquet Python a été construit hors ligne ; son fichier
de marques correspond exactement à celui du dépôt (612 noms).

```bash
.venv/bin/python -m pytest -q
# PostgreSQL et corpus existants, lecture seule, aucun modèle appelé.
PYTHONPATH=src .venv/bin/python scripts/audit_technical_normalization.py
```

Avant de remplacer les filtres de la démo : examiner les identités signalées,
élargir l'audit aux conflits du corpus, puis appliquer une migration additive
versionnée et tester les outils sur les nouveaux champs. Équipements, couleurs
et passages techniques restent les étapes suivantes.

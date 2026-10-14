# Diagnostic ciblé des embeddings — 14 octobre 2026

Lecture de l'index global figé du benchmark, sans réindexation, appel distant,
modification du catalogue ou changement du front. Une question utilisateur et
deux reformulations manuelles servent uniquement au diagnostic.

## Résultat

- Les cinq fichiers de l'index correspondent à leurs SHA256 enregistrés.
- Les 105 687 vecteurs ont 1 024 dimensions, des valeurs finies et une norme
  comprise entre 0,99999982 et 1,00000012. Cela contrôle l'intégrité, pas la pertinence.
- Avec la formulation exacte Gold Wing / RT de l'utilisateur, BGE-M3 retrouve
  le passage Transmission de la Gold Wing Tour DCT/Airbag 2018 au rang 6.
- Les dix premiers passages sont tous Honda. Une récupération globale top-10
  ne couvre donc pas toutes les entités de cette demande.
- La reformulation manuelle BMW RT / boîte automatique / ASA place les passages
  Transmission R 1300 RT 2025 et 2026 aux deux premiers rangs. Ils décrivent une
  boîte manuelle et un shifter en option : proximité sémantique ne vaut pas preuve.
- Les 369 passages des 38 fiches BMW avec le token RT ne comportent aucune
  mention du token ASA. Ce manque ne prouve pas l'absence d'une option automatique.

## Portée de la conclusion

Les vecteurs existants peuvent retrouver un passage pertinent. Ce diagnostic
ne démontre ni une qualité générale suffisante ni la fiabilité du bot.
La question échoue sur le front avant toute récupération : voir
l'[audit d'architecture](../../../docs/research-architecture-audit-20261014.md).
L'index utilisé ici reste distinct du parcours actif.

Il faut d'abord raccorder une recherche permettant la découverte, couvrir chaque
famille, puis distinguer classement par similarité et recherche du premier
millésime documenté. Les sources manquantes doivent être ajoutées au corpus,
puis encodées. Aucun défaut observé ici ne justifie de recalculer tout l'index
à représentation et modèle identiques.

## Configuration et limites

Modèle local BGE-M3, révision `5617a9f61b028005a4858fdac845db406aefb181`.
Questions encodées sur CPU en float32, maximum 512 tokens ; documents existants
encodés sur MPS en float16, puis stockés en float32 normalisé. C'est une
configuration diagnostique distincte du benchmark initial, sans comparaison
de temps ni nouveau taux de pertinence. Les périmètres de familles ont été
sélectionnés manuellement par marque et expression sur le nom ; les deux
reformulations ne sont pas une capacité démontrée du bot.

[Observations et classements](observations.json). Les sources et qualifications
originales sont conservées dans ces résultats ; aucun score n'établit à lui
seul une date de lancement ou une présence d'équipement.

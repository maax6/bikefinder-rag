# Première passe d’enrichissement sur 7 698 fiches

Exécution du 12 octobre 2026. [Résultats agrégés](../eval_results/technical/equipment_enrichment_20261012.json).

Le traitement a figé **7 698 fiches** pendant que le collecteur individuel
continuait. L’export enrichi conserve à l’identique les 252 551 lignes
techniques, les identités et la provenance de ce snapshot, dont les **3 499
fiches avec une autonomie**. Il reste séparé du catalogue du chat et de la
base du collecteur.

## Première passe, vérification et ajustement

Les 4 116 couples fiche–équipement, dont 400 contrôles sans mention d’ABS,
représentent 755 entrées distinctes. Jev a classé les 755 entrées ; Mistral a
traité 198 entrées de repli ou d’audit. Les consignes d’origine appliquaient
un qualificatif final « en option » à toute une liste : les deux modèles
pouvaient donc confirmer le même choix sur une portée incertaine.

Une seconde consigne impose l’inconnu sur les portées non résolues. Jev a été
appelé sur les 385 entrées disposant d’une mention technique, Mistral sur
288 entrées de repli ou d’audit. Elle améliore les décisions Jev brutes, mais
rend Mistral trop prudent sur des options explicites. La cascade provisoire
baisse ainsi à 53/67 dans le nouvel audit. Ses résultats sont conservés dans
`data/technical/enrichment-20261012/summary-before-literal-facts.json`.

Le dernier ajustement donne priorité aux faits littéraux de la source :
option explicite, absence explicite de la cible, équipement non qualifié dans
la rubrique de série, ou spécification de transmission nommant la marche
arrière. Une injection nommant intégralement Ride by Wire conserve cette
information même si un détail supplémentaire est tronqué ; ce détail reste
tronqué dans les données. Les modèles ne complètent aucun texte source.

Un prix avec ABS seul reste inconnu. Les groupes dont la portée n’est pas
résolue, les contradictions et les libellés génériques comme « Freinage »
restent à examiner. Ces contrôles s’appliquent aussi à Mistral.

| Conformité aux annotations source | Première cascade | Après ajustement |
|---|---:|---:|
| 67 nouveaux extraits | 57/67 | **67/67** |
| Régressions historiques présentes | 54/59 | **56/59** |

Les 67 annotations ont été écrites par l’agent sur les extraits avant
consultation des nouvelles sorties. L’échantillon est ciblé et les règles
ont été ajustées sur des problèmes observés ; ces nombres mesurent une
conformité source et des régressions, pas une précision représentative ni
une validation humaine ou constructeur. Un contrôle historique sans mention
n’a pas été resélectionné dans le nouveau lot, d’où 59 références sur 60.
Les trois désaccords historiques restants sont conservés : leur référence
qualifie d’optionnel un élément de groupe ; la politique prudente garde ce
groupe inconnu. Les références n’ont pas été modifiées pour améliorer le score.

## Ce que les modèles ont réellement apporté

Sur les 67 nouveaux extraits, Jev brut passe de 58/67 à 66/67, Mistral brut
de 57/67 à 49/67 avec la consigne plus prudente. L’amélioration finale vient
des contrôles de preuve et de la priorité des faits explicites, pas d’un
générateur plus précis.

Le lot actuel est suffisamment structuré pour que les 3 590 décisions
établies soient traitables en code. **84 décisions** restent à examiner,
soit 22 entrées distinctes ; **442** décisions du lot n’établissent aucun
équipement technique cible. Le code garde leurs preuves et l’inconnu.
Dans cette exécution, les modèles ont servi à évaluer et diagnostiquer les
règles ; aucune décision finale ne nécessite leur réponse après les
ajustements. Jev et Mistral restent disponibles pour les cas réellement
interprétatifs du RAG, sans forcer leur usage sur des faits structurés.

Les appels réalisés ne sont pas présentés comme des appels évités :
**1 140 appels Jev**, **486 appels Mistral**, sans erreur API ou locale.
Le coût Jev renvoyé par OpenRouter totalise **0,0352863 USD**. La médiane d’un
appel est de 0,390 s puis 0,315 s pour Jev, et 1,263 s puis 1,246 s pour
Mistral. Les durées murales Jev sont de 107,8 s puis 31,6 s, Mistral de
272,5 s puis 376,1 s ; elles excluent le téléchargement du modèle et ne sont
pas des temps de réponse du chat. Jev utilise quatre requêtes concurrentes,
Mistral des requêtes séquentielles.

## Export et reproduction

Les fichiers de travail sont ignorés par Git :

- `data/technical/enrichment-20261012/pass2/catalogue.enriched.sqlite3` : les
  7 698 objets sources et 8 371 lignes d’équipement, avec preuve et statut.
- `data/technical/enrichment-20261012/pass2/decisions.json` : les décisions
  évaluées et leurs motifs ; `source_review` identifie les 84 cas à examiner.
- `data/technical/enrichment-20261012/enriched-samples.json` : quelques exemples.
- `data/technical/enrichment-20261012/pass2/pipeline-protocol.json` : empreintes
  du snapshot et du code, consignes figées et modèle local exact.

Le fournisseur est OpenRouter, modèle demandé `typesafe/jev-1.13`, réponse
observée `typesafe/jev-1.13-20260917`. Le modèle local remis à disposition est
`mistral-small3.2:latest`, 24B Q4_K_M, digest `5a408ab55df5…`. Les preuves Jev
passent par une API distante ; les décisions Mistral restent locales.

```bash
PYTHONPATH=src:scripts .venv/bin/python scripts/enrich_equipment.py \
  --out data/technical/enrichment-20261012 --pass pass2 --action finalize
PYTHONPATH=src:scripts .venv/bin/python scripts/enrich_equipment.py \
  --out data/technical/enrichment-20261012 --action report
```

Ces commandes rejouent les décisions sauvegardées. Les actions `jev` et
`mistral` exécutent les modèles avec cache lié aux consignes ; le snapshot
ne doit jamais être remplacé par la base de collecte. Les empreintes
identifient les artefacts nécessaires à une reproduction exacte.

**489 tests passent**, dont 18 régressions sur les portées, les faits
explicites, les replis et la conservation complète du source dans l’export.
Le collecteur est resté au même PID 16466 et a dépassé 7 870 fiches pendant
le traitement. Aucun serveur de suivi HTML n’a été démarré.

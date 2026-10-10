# Collecte technique des motos et de leurs équipements

Périmètre demandé le 10 octobre 2026 : motos historiques et récentes de
toutes marques et régions, avec leurs équipements intégrés. Casques,
vêtements et avis des propriétaires sont hors de cette collecte. Les fiches
sources sont conservées séparément : une identité, une année ou une variante
ne sont pas fusionnées automatiquement parce que leurs noms se ressemblent.

## Ce que l'audit a établi

Le [rapport local](../eval_results/technical/data_inventory_20261010.json)
recense **32 395 URL Bikez distinctes**, de 1894 à 2024, sur 131 millésimes.
Ces chiffres décrivent les fichiers présents, pas un catalogue mondial
exhaustif. **548 fiches de 2024** contiennent encore `Loading...`. Les
équipements étaient partiellement présents dans les textes : **4 664 fiches**
mentionnent l'ABS hors identité/navigation ; **624** mentionnent aussi une
option. Ce repérage n'établit pas un état d'équipement ni un marché.

Motoplanete avait **11 418 fiches** sauvegardées, uniquement identité,
catégorie et prix. Les caractéristiques et équipements n'étaient pas
conservés. Son ancien journal compte **60 URL terminées sans donnée** ; le
nouveau collecteur ne dépend pas de ce journal. Un millésime 2078 est isolé
pour examen ; un millésime annoncé pour l'année prochaine reste admissible.

Les fichiers historiques ne contiennent ni date de collecte, ni HTML
original. Une exportation locale peut conserver leur source et leur
empreinte, mais ne peut pas reconstruire ces métadonnées manquantes.

## Sources vérifiées et ordre de collecte

Les règles ci-dessous ont été vérifiées le **10 octobre 2026**. Il faut les
revérifier avant d'activer un nouveau connecteur ou un usage différent.

| Source | Apport | Portée et conditions observées | Action |
|---|---|---|---|
| [Motoplanete](https://www.motoplanete.com/sitemap_moto.php) | Fiches, moteur, dimensions, poids qualifiés, freinage, équipements, couleurs et tarifs | [CGU](https://www.motoplanete.com/article/41/Conditions-Generales-dUtilisation/page.html) : exploitation commerciale interdite ; aucune licence ouverte de redistribution. [Robots](https://www.motoplanete.com/robots.txt) : fiches accessibles, délai 10 s. Le pays du tarif ne prouve pas le marché de toute la fiche. | Connecteur technique mis en œuvre pour le POC local non commercial. |
| [Wikidata](https://www.wikidata.org/wiki/Wikidata:Data_access) | Identifiants, labels et classifications de modèles dans le monde | Données structurées CC0. [Moto Q34493](https://www.wikidata.org/wiki/Q34493) et [modèle Q23866334](https://www.wikidata.org/wiki/Q23866334) sont deux classes à explorer ; couverture contributive incomplète. | Inventaire indépendant, sans le présenter comme des fiches millésimées ni déduire un équipement d'une photo. |
| [Bikez](https://bikez.com/about/index.php) | Corpus historique existant, nombreux champs techniques anglophones | Autorisation écrite préalable demandée pour reproduire les contenus, malgré robots permissif. | Préserver/auditer les fichiers locaux ; aucune nouvelle collecte Bikez. |
| [Honda, archives deux roues](https://global.honda/jp/pressroom/products/motor/) | Fiches et communiqués historiques, variantes, couleurs, dates, mesures | [Conditions](https://global.honda/en/terms-and-conditions/) : exception personnelle/interne non commerciale ; autres usages soumis à autorisation. Documents japonais à garder comme tels. | Prochain connecteur primaire pour compléter les équipements et dates documentées. |
| [Suzuki Digital Archive](https://www.globalsuzuki.com/motorcycle/smgs/digital-archive/) | Archives depuis 1952, tableaux de caractéristiques et descriptions | Spécifications principalement japonaises ; [droits réservés](https://www.globalsuzuki.com/foruse/), pas de licence de catalogue ouverte. | Qualifier l'usage avant activation. |
| [Yamaha Products History](https://global.yamaha-motor.com/stories/history/products/) | Historique depuis 1955, dates de sortie, descriptions, documents | [Conditions](https://global.yamaha-motor.com/copyright/) restrictives ; données lors de la sortie, pas nécessairement chaque millésime. | Connecteur candidat, conservation de la portée historique. |
| [BMW Classic](https://www.bmwgroup-classic.com/en/models/bmw-motorcycle-classics.html) | Catalogue officiel et archives historiques | Contenu dynamique ; détails non validés par ce pilote. [Conditions](https://www.bmwgroup-classic.com/en/general/legal-disclaimer.html) : aucune licence ouverte accordée. | Valider les documents originaux et le contrat d'accès. |
| [Ducati Heritage](https://www.ducati.com/ww/en/heritage/bikes) | Sélection de motos patrimoniales et descriptions d'équipement | [Conditions](https://my.ducati.com/ww/en/footer/terms-of-use) interdisant stockage/reproduction sauf permission expresse. | Aucun crawl de stockage activé. |

Cet ordre couvre d'abord les sources structurées accessibles. Les manuels,
brochures et communiqués constructeur apporteront ensuite une preuve plus
précise de **série / option / absence explicite**, par variante et marché.
Un catalogue ne garantit pas à lui seul cette granularité.

## Contrat de la nouvelle collecte

`scripts/collect_technical_data.py` emploie un parseur Motoplanete dédié et
une file SQLite isolée de PostgreSQL. Il ne charge rien automatiquement
dans le chat et ne collecte aucun forum ou avis. Il conserve :

- identité brute, millésime de l'URL et du titre, contradictions et marché inconnu ;
- lignes ordonnées avec section, libellé et valeur d'origine ; doublons préservés ;
- textes des équipements, couleurs, tarifs et performances, sans perdre leurs unités ;
- URL demandée/finale, date UTC, statut HTTP, SHA-256 de la réponse et version du parseur ;
- un snapshot HTML reconstruit à partir des seuls textes techniques, sans photo, script ou avis.

Les candidats équipements restent `unclassified`. Le cas réel
[ST1100 2000](https://www.motoplanete.com/honda/885/ST-1100-PAN-EUROPEAN-2000/contact.html)
montre pourquoi : une section intitulée équipement de série contient une
ligne décrivant ABS/CBS/TCS en option. Le titre de section ne suffit pas à
résoudre cette contradiction. La normalisation future devra conserver le
passage, la portée de variante et les états inconnus.

Une transaction SQLite associe chaque succès à ses données. Une seconde
exécution saute les succès et ne dépend pas d'un fichier `done` séparé.
Les timeouts et extractions vides restent rejouables. Les réponses 404/410
sont des erreurs terminales visibles, distinctes des succès. Une réponse
429/5xx arrête le lot en conservant `Retry-After` ; une interdiction arrête
l'accès. Les redirections vers un autre hôte et les chemins robots exclus
ne sont pas suivis. Un verrou commun empêche deux instances du nouveau
collecteur de solliciter Motoplanete simultanément ; laisser les anciens
collecteurs arrêtés car ils ne participent pas à ce verrou.

## Exécution et contrôle

Les nouvelles données restent dans `data/technical/`, hors Git ; rapports
et scripts sont versionnés. Le corpus historique et la base du chat ne
sont pas réécrits. Depuis la racine du dépôt :

```bash
# Audit local, sans réseau ni base
.venv/bin/python scripts/audit_technical_data.py --help

# Mesures par champ sur un snapshot cohérent de la collecte en cours
.venv/bin/python scripts/audit_collected_technical_data.py \
  --database data/technical/motoplanete/crawl.sqlite3

# Pilote ciblé, avec une liste d'URL de fiches canoniques
PYTHONPATH=src .venv/bin/python scripts/collect_technical_data.py \
  --out data/technical/motoplanete --urls-file /chemin/urls.txt --limit 20

# Découverte des sitemaps actuels et collecte de toutes les fiches accessibles
PYTHONPATH=src .venv/bin/python scripts/collect_technical_data.py \
  --out data/technical/motoplanete --refresh-sitemaps --all

# Reprise du même corpus : les succès sont sautés
PYTHONPATH=src .venv/bin/python scripts/collect_technical_data.py \
  --out data/technical/motoplanete --all

# Export/état hors réseau, lorsque le collecteur est arrêté
PYTHONPATH=src .venv/bin/python scripts/collect_technical_data.py \
  --out data/technical/motoplanete --export-only
```

La reprise utilise aussi la file SQLite déjà enregistrée lorsque la mise à
jour des sitemaps a échoué et qu'aucun cache final n'a été publié. Elle ne
dépend pas d'une nouvelle réussite de la découverte.

**État vérifié le 10 octobre :** le pilote a réussi sur 14 fiches, de 1871 à
2027. La mise à jour des sitemaps a ensuite rencontré un HTTP 500 ; après
le refroidissement enregistré, la collecte complète a été reprise avec
les **11 479 URL du cache historique** (dont une isolée pour examen).
Ce lot ne prétend donc pas inclure les nouvelles fiches absentes de ce
cache. L'actualisation des sitemaps devra être retentée séparément après
la collecte ou un arrêt contrôlé.

L'export local contient **32 395 candidats normalisés**, dont 44 identités
à examiner ; ses 188 219 passages d'équipement restent non classifiés.
L'inventaire Wikidata contient **3 255 entités candidates**, avec des types
génériques possibles et une découverte des sous-classes bornée à 100.
Ces comptes ne s'additionnent pas en un total de motos distinctes.

Le [premier audit des données collectées](../eval_results/technical/motoplanete_coverage_20261010.json)
mesure 40 fiches réussies, 1 301 lignes techniques et 62 candidats d'équipement
sur 9 fiches au 10 octobre à 11:12 UTC. Les 40 marchés techniques restent inconnus, même lorsque le
tarif nomme un pays. Il sépare les états de la file, les fiches acceptées et
celles à examiner ; il distingue nombre de lignes et nombre de fiches par
section/libellé/année. Un champ absent n'est pas détectable par le seul
comptage des lignes présentes : ces mesures ne prouvent ni une fiche
complète, ni l'absence d'un équipement.

Deux valeurs partiellement inconnues (`Ø nc`) sont signalées sans éliminer
les autres informations présentes dans ces lignes.

`status.json` donne l'état des URL par année, `last_run.json` le résultat du
dernier lot, `records.jsonl` les succès exportés et `crawl.sqlite3` les
données canoniques durables. Le JSONL est actualisé tous les 25 succès et
à l'arrêt. `pid.txt` contient le dernier PID lancé ; vérifier qu'il existe
encore avant de l'utiliser. Un arrêt avec SIGTERM passe par l'export final.

Au délai minimal, **11 500 fiches demandent au moins 32 heures**, auxquelles
s'ajoutent le temps des réponses et la découverte. Ce calcul n'est pas une
promesse de durée. Aucune limite de débit n'est abaissée pour accélérer la
collecte. La couverture finale se mesure par URL source réussie, par
millésime et par champ, pas par une affirmation « toutes les motos du monde ».

Validation finale : **429 tests passent** (suite complète, 6,86 s), avec
compilation des fichiers Python modifiés et contrôle des différences Git.
Les tests couvrent notamment reprise et interruption, temporisation
persistante, concurrence, redirections, extraction des équipements et
lecture cohérente de SQLite pendant la collecte. Le pilote HTTP de 14
fiches et l'inventaire Wikidata sont des vérifications réelles distinctes
des tests simulés. Les revues du contrat et de l'implémentation ont conduit
à corriger la reprise après échec de découverte, le refroidissement partagé
et les redirections changeant d'identité.

## Suivi visuel local

Le collecteur fonctionne sur ce Mac, dans un processus Python indépendant
de la page de chat. Un suivi local est disponible sur
<http://127.0.0.1:7861/> : progression, fiches restantes, cadence mesurée,
durée estimée, dernières fiches et couverture par période. La page se
rafraîchit toutes les dix secondes et peut être fermée sans arrêter la
collecte.

Pour relancer uniquement ce suivi :

```bash
.venv/bin/python scripts/monitor_technical_collection.py --port 7861
```

Le moniteur lit SQLite en mode lecture seule, dans une transaction courte.
Il vérifie le PID, le programme et le répertoire du collecteur, plutôt que
de déduire son activité du seul `running` enregistré dans `status.json`.
La cadence utilise les succès récents et exclut l'ancien pilote ; l'ETA
est masquée si le processus est arrêté ou si les données ne sont plus
récentes. Les huit tests du moniteur vérifient ces cas et la lecture WAL
pendant une écriture indépendante.

Après ajout du suivi, la suite complète passe : **437 tests** (7,68 s).
La page a été vérifiée dans le navigateur local, y compris le rafraîchissement
des compteurs et l'identification du processus de collecte.

## Livraison suivante

Après la collecte : contrôler les identités, unités et variantes, classer
les preuves d'équipement, puis ajouter un index technique et une recherche
paginée dans la base locale. Les données brutes nouvellement collectées ne
changent pas encore la réponse ABS dans le chat ; cette intégration est une
étape distincte et doit être évaluée sur le cas année/marché/option.

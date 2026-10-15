# Lot annoté BGE-M3 — 15 octobre 2026

24 cas : 11 de réglage, 9 de vérification sur des marques distinctes, 4 sur des
documents ou autorités absents. Les textes et preuves proviennent du snapshot
figé ; cette relecture est faite par l’assistant à partir des annotations source
existantes, sans panel humain indépendant. Les 20 questions positives sont
connues et choisies pour leurs erreurs ou comme témoins : ce n’est pas un nouveau
lot de généralisation. Les quatre audits de couverture ne participent pas au
choix du réglage.

Chaque fiche ci-dessous précise la question, le défaut recherché, les preuves
attendues, les limites et deux passages proches susceptibles de tromper le
classement. Les fichiers JSON associés conservent les empreintes sources, les
identités, groupes de preuves et grades. Les documents non jugés dans le corpus
global ne sont pas automatiquement des preuves négatives. Aucun entraînement
n’est effectué ; ce lot n’est pas exporté comme corpus d’apprentissage.

## Réglage

### HOLDOUT-001 — wrong_model

La CFMOTO 450 MT 2024 n’a pas une selle fixe ? Donne-moi aussi son encombrement en longueur et sa masse annoncée.

Le premier passage concerne la 450 SR, pas la 450 MT ; selle, longueur et masse ne sont pas transférables.

Preuves attendues :

- `1145a40178537481:section:0` — CFMOTO 450 MT 2024, Châssis : « Cadre : tubulure en acier; Réservoir : 17,50 litres; Hauteur de selle réglable entre 800 mm et 820 mm; Longueur : 2 210 mm; Largeur : 870 mm; Hauteur min : 1 390 mm; Empattement : 1 505 mm; Poids à sec : 175 kg » [Source](https://www.motoplanete.com/cfmoto/10690/450-MT-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. Le poids indiqué est à sec, pas tous pleins faits.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `adc61111646f273b:section:0` — CFMOTO 450 SR 2024, Châssis : « Selle biplaces; Cadre : tubulure en acier; Réservoir : 14 litres; Hauteur de selle : 795 mm; Longueur : 1 990 mm; Largeur : 735 mm; Hauteur min : 1 130 mm; Empattement : 1 370 mm; Poids à sec : 168 kg; Poids tous pleins faits : 179 kg » [Source](https://www.motoplanete.com/cfmoto/10833/450-SR-2024/contact.html).

- Rang 2, `a0386692164cbb7e:section:0` — CFMOTO 450 CL-C 2024, Châssis : « Selle biplaces; Cadre : tubulure en acier; Réservoir : 12 litres; Hauteur de selle : 705 mm; Longueur : 2 208 mm; Largeur : 829 mm; Hauteur min : 1 130 mm; Garde au sol min : 160 mm Empattement : 1 486 mm Poids à sec : 183 kg » [Source](https://www.motoplanete.com/cfmoto/10844/450-CL-C-2024/contact.html).

### HOLDOUT-005 — wrong_variant_multi_evidence

La Moto-Guzzi 850 V7 Stone 2024 roule avec une chaîne ? Et son moteur refroidit à l’eau ou à l’air ?

La Stone Corsa ne remplace pas la Stone. Il faut les deux passages moteur et transmission pour air/cardan.

Preuves attendues :

- `d0795676152e69de:section:2` — Moto-Guzzi 850 V7 Stone 2024, Transmission : « boîte à 6 rapports , manuelle; Secondaire par cardan » [Source](https://www.motoplanete.com/moto-guzzi/10566/850-V7-Stone-2024/contact.html).

- `d0795676152e69de:section:4` — Moto-Guzzi 850 V7 Stone 2024, Moteur : « Bicylindre en L à 90° , 4 temps; Injection Ø 38 mm; Refroidissement : par air; culbuté; 2 soupapes par cylindre; 853 cc (Alésage * course: 84 x 77 mm); 65 ch à 6 800 tr/min; 7,50 mkg à 5 000 tr/min; Rapport poids / puissance : 3.05 kg/ch; Rapport poids / couple : 26.4 kg/mkg; Compression : 10,5 : 1; Emission CO² : 119 g/km » [Source](https://www.motoplanete.com/moto-guzzi/10566/850-V7-Stone-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `044cfbe09d8c22a5:section:4` — Moto-Guzzi 850 V7 Stone Corsa 2024, Moteur : « Bicylindre en L à 90° , 4 temps; Injection Ø 38 mm; Refroidissement : par air; culbuté; 2 soupapes par cylindre; 853 cc (Alésage * course: 84 x 77 mm); 65 ch à 6 800 tr/min; 7,50 mkg à 5 000 tr/min; Rapport poids / puissance : 3.05 kg/ch; Rapport poids / couple : 26.4 kg/mkg; Compression : 10,5 : 1; Emission CO² : 119 g/km » [Source](https://www.motoplanete.com/moto-guzzi/10024/850-V7-Stone-Corsa-2024/contact.html).

- Rang 2, `044cfbe09d8c22a5:section:3` — Moto-Guzzi 850 V7 Stone Corsa 2024, Train arrière : « 2 amortisseurs latéraux, déb : 120 mm; Freinage : 1 disque Ø 260 mm, étrier 2 pistons; Roue arrière : 150 / 70 - 17; Pression : 2.5 bars » [Source](https://www.motoplanete.com/moto-guzzi/10024/850-V7-Stone-Corsa-2024/contact.html).

### HOLDOUT-007 — incomplete_comparison

La Yamaha MT-09 900 Y-AMT 2024 change quoi face à la MT-09 900 2024 : la boîte seulement, ou aussi la cylindrée et la puissance ?

Les passages Y-AMT seuls ne prouvent pas les caractéristiques de la version manuelle ; couvrir les deux fiches et moteur/transmission.

Preuves attendues :

- `5f8c8c61b3eeb916:section:2` — Yamaha MT-09 900 Y-AMT 2024, Transmission : « boîte à 6 rapports , manuelle automatisée; Secondaire par chaîne » [Source](https://www.motoplanete.com/yamaha/10704/MT-09-900-Y-AMT-2024/contact.html).

- `2a224bbc503cf279:section:2` — Yamaha MT-09 900 2024, Transmission : « boîte à 6 rapports , manuelle - shifter de série; Secondaire par chaîne » [Source](https://www.motoplanete.com/yamaha/10099/MT-09-900-2024/contact.html).

- `5f8c8c61b3eeb916:section:4` — Yamaha MT-09 900 Y-AMT 2024, Moteur : « 3 cylindres en ligne , 4 temps; Injection; Refroidissement : liquide; 2 ACT; 4 soupapes; 889 cc (Alésage * course: 78 x 62.1 mm); 119 ch à 10 000 tr/min; 9,50 mkg à 7 000 tr/min; Rapport poids / puissance : environ 1.52 kg/ch; Rapport poids / couple : environ 18.99 kg/mkg; Compression : 11.5 : 1; Emission CO² : 116 g/km » [Source](https://www.motoplanete.com/yamaha/10704/MT-09-900-Y-AMT-2024/contact.html).

- `2a224bbc503cf279:section:4` — Yamaha MT-09 900 2024, Moteur : « 3 cylindres en ligne , 4 temps; Injection; Refroidissement : liquide; 2 ACT; 4 soupapes; 889 cc (Alésage * course: 78 x 62.1 mm); 119 ch à 10 000 tr/min; 9,50 mkg à 7 000 tr/min; Rapport poids / puissance : environ 1.52 kg/ch; Rapport poids / couple : environ 18.99 kg/mkg; Compression : 11.5 : 1; Emission CO² : 116 g/km » [Source](https://www.motoplanete.com/yamaha/10099/MT-09-900-2024/contact.html).

- `5f8c8c61b3eeb916:section:5` — Yamaha MT-09 900 Y-AMT 2024, Équipement de série : « Assistance au freinage : ABS; Nombre de mode de conduite : 5; Taille de l'écran TFT couleur : 12,70 cm / 5 pouces; Jantes aluminium; Indicateur de vitesse engagée; Régulateur de vitesse; Boîte automatique; Bluetooth; Prise USB; Démarrage sans clé; Contrôle de traction; Contrôle anti wheeling; Jantes forgées; Contrôle de glisse; Embrayage anti-dribble; Repose-pieds réglables; Contrôle du frein moteur » [Source](https://www.motoplanete.com/yamaha/10704/MT-09-900-Y-AMT-2024/contact.html).

- `2a224bbc503cf279:section:5` — Yamaha MT-09 900 2024, Équipement de série : « Assistance au freinage : ABS; Nombre de mode de conduite : 5; Taille de l'écran TFT couleur : 12,70 cm / 5 pouces; Jantes aluminium; Shifter; Indicateur de vitesse engagée; Régulateur de vitesse; Bluetooth; Prise USB; Contrôle de traction; Contrôle anti wheeling; Jantes forgées; Contrôle de glisse; Embrayage anti-dribble; Repose-pieds réglables; Contrôle du frein moteur » [Source](https://www.motoplanete.com/yamaha/10099/MT-09-900-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. Comparer seulement les caractéristiques demandées. L’égalité de cylindrée et de puissance ne prouve pas que toutes les autres pièces sont identiques.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 3, `7ac85eaa82d54a1f:section:4` — Yamaha MT-09 900 Y-AMT 2025, Moteur : « 3 cylindres en ligne , 4 temps; Injection; Refroidissement : liquide; 2 ACT; 4 soupapes; 889 cc (Alésage * course: 78 x 62.1 mm); 119 ch à 10 000 tr/min; 9,50 mkg à 7 000 tr/min; Rapport poids / puissance : environ 1.52 kg/ch; Rapport poids / couple : environ 18.99 kg/mkg; Compression : 11.5 : 1; Emission CO² : 116 g/km » [Source](https://www.motoplanete.com/yamaha/10932/MT-09-900-Y-AMT-2025/contact.html).

- Rang 5, `b8b2de9d55edcc60:section:4` — Yamaha MT-09 SP 900 2024, Moteur : « 3 cylindres en ligne , 4 temps; Injection; Refroidissement : liquide; 2 ACT; 4 soupapes; 889 cc (Alésage * course: 78 x 62.1 mm); 119 ch à 10 000 tr/min; 9,50 mkg à 7 000 tr/min; Rapport poids / puissance : environ 1.52 kg/ch; Rapport poids / couple : environ 19.1 kg/mkg; Compression : 11.5 : 1; Emission CO² : 116 g/km » [Source](https://www.motoplanete.com/yamaha/10100/MT-09-SP-900-2024/contact.html).

### HOLDOUT-010 — excluded_variant

J’ai besoin de la largeur de la BMW R 1250 GS 2023 et de sa plage de réglage de selle, pas de l’Adventure.

La demande exclut Adventure : son châssis donne une selle 890–910 mm, contre 850–870 mm pour la GS demandée.

Preuves attendues :

- `4d902be1a67428c8:section:0` — BMW R 1250 GS 2023, Châssis : « Cadre : Structure en tubes d'acier; Réservoir : 20 litres; Hauteur de selle réglable entre 850 mm et 870 mm; Longueur : 2 207 mm; Largeur : 953 mm; Hauteur min : 1 430 mm; Empattement : 1 514 mm; Poids tous pleins faits : 249 kg » [Source](https://www.motoplanete.com/bmw/9459/R-1250-GS-2023/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. L’extraction ne précise pas la largeur avec ou sans rétroviseurs.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `2f3029ce1e32cf71:section:0` — BMW R 1250 GS Adventure 2023, Châssis : « Cadre : Structure en tubes d'acier; Réservoir : 30 litres; Hauteur de selle réglable entre 890 mm et 910 mm; Longueur : 2 270 mm; Largeur : 952 mm; Hauteur min : 1 460 mm; Empattement : 1 504 mm; Poids tous pleins faits : 268 kg » [Source](https://www.motoplanete.com/bmw/9455/R-1250-GS-Adventure-2023/contact.html).

- Rang 2, `26976d151574533e:section:5` — BMW R 1250 GS Adventure Ultimate Edition 2024, Équipement de série : « Assistance au freinage : El ABS en curvas puede desactivarse; Nombre de mode de conduite : 7; Volume de rangement : 112 litres; Taille de l'écran TFT couleur : 16,51 cm / 6.5 pouces; Jantes à rayon; Shifter; Béquille centrale; Indicateur de vitesse engagée; Régulateur de vitesse; Bluetooth; Prise USB; Aide au démarrage en côte (Hill Hold Control); Démarrage sans clé; Contrôle de traction; Poignées chauffantes; Pare brise réglable; Suspensions réglables électroniquement; Valises; Crash Bars / Top Blocks; Embrayage anti-dribble; Selle réglable; Selle chauffante; Phares adaptatifs en virage; Contrôle du frein moteur; Surveillance de la pression des pneus » [Source](https://www.motoplanete.com/bmw/10312/R-1250-GS-Adventure-Ultimate-Edition-2024/contact.html).

### HOLDOUT-015 — qualification_control

Si je prends une KTM 790 Duke 2024, le système pour passer les rapports sans débrayer est compris ou marqué en option ?

Conserver « shifter en option ». Le premier résultat est déjà juste ; vérifier que le réglage ne le dégrade pas.

Preuves attendues :

- `08413f04a1acc6df:section:2` — KTM 790 Duke 2024, Transmission : « boîte à 6 rapports , manuelle - shifter en option; Secondaire par chaîne » [Source](https://www.motoplanete.com/ktm/10069/790-Duke-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. La fiche n’explicite pas son fonctionnement à la montée et à la descente ni le prix de l’option.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 2, `5ba13c4387c23c17:section:2` — KTM 790 Duke 2023, Transmission : « boîte à 6 rapports , manuelle - shifter en option; Secondaire par chaîne » [Source](https://www.motoplanete.com/ktm/9637/790-Duke-2023/contact.html).

- Rang 3, `362d75eab533950e:section:2` — KTM 790 Duke 2027, Transmission : « boîte à 6 rapports , manuelle - shifter en option; Secondaire par chaîne » [Source](https://www.motoplanete.com/ktm/12229/790-Duke-2027/contact.html).

### HOLDOUT-016 — partial_evidence_control

La Ducati Monster SP 2024 a bien l’aide au départ arrêté et un shifter fourni ? La fiche précise s’il marche aussi en descendant les vitesses ?

Conserver transmission et équipements pour shifter/Launch Control. Ne pas déduire bidirectionnel d'une mention de shifter.

Preuves attendues :

- `02d3dd07d44cc430:section:2` — Ducati Monster SP 2024, Transmission : « boîte à 6 rapports , manuelle - shifter de série; Secondaire par chaîne » [Source](https://www.motoplanete.com/ducati/10190/Monster-SP-2024/contact.html).

- `02d3dd07d44cc430:section:5` — Ducati Monster SP 2024, Équipement de série : « Assistance au freinage : ABS en curvas; Nombre de mode de conduite : 3; Taille de l'écran TFT couleur : 10,92 cm / 4.3 pouces; Jantes aluminium; Shifter; Amortisseur de direction; Indicateur de vitesse engagée; Bluetooth; Prise USB; Aide au départ arrêté (Launch Control); Contrôle de traction; Contrôle anti wheeling; Embrayage anti-dribble » [Source](https://www.motoplanete.com/ducati/10190/Monster-SP-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. Aucun sens de fonctionnement montée/descente du shifter n’est précisé. Ne pas déduire up/down du seul mot Shifter.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 2, `bee3c7dd647a8e92:section:2` — Ducati Monster SP "Monster Hunter" 2024, Transmission : « boîte à 6 rapports , manuelle - shifter de série; Secondaire par chaîne » [Source](https://www.motoplanete.com/ducati/10848/Monster-SP-Monster-Hunter-2024/contact.html).

- Rang 4, `bee3c7dd647a8e92:section:5` — Ducati Monster SP "Monster Hunter" 2024, Équipement de série : « Assistance au freinage : ABS; Nombre de mode de conduite : 3; Taille de l'écran TFT couleur : 10,92 cm / 4.3 pouces; ABS Cornering; Jantes aluminium; Shifter; Amortisseur de direction; Indicateur de vitesse engagée; Bluetooth; Prise USB; Aide au départ arrêté (Launch Control); Contrôle de traction; Contrôle anti wheeling; Embrayage anti-dribble » [Source](https://www.motoplanete.com/ducati/10848/Monster-SP-Monster-Hunter-2024/contact.html).

### HOLDOUT-023 — wrong_year_missing_fact

Pour le Honda Forza 750 2024, tu peux confirmer la prise USB et le démarrage sans clé à partir de la fiche ?

La fiche 2026 ou 2025 ne prouve pas l'équipement 2024. USB est cité ; démarrage sans clé reste non établi dans la fiche visée.

Preuves attendues :

- `5fc29da37183ee6c:section:5` — Honda Forza 750 2024, Équipement de série : « Assistance au freinage : ABS; Taille de l'écran TFT couleur : 12,70 cm / 5 pouces; Prise USB » [Source](https://www.motoplanete.com/honda/10623/Forza-750-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. Démarrage sans clé non documenté dans les sections fournies. L’absence d’un équipement ou d’un coloris dans cette extraction ne prouve pas son indisponibilité réelle.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `37dbe9facb439707:section:5` — Honda Forza 750 2026, Équipement de série : « Assistance au freinage : ABS; Nombre de mode de conduite : 5; Taille de l'écran TFT couleur : 12,70 cm / 5 pouces; Jantes aluminium; Béquille centrale; Indicateur de vitesse engagée; Régulateur de vitesse; Bluetooth; Prise USB; Démarrage sans clé; Pare brise réglable électriquement; Contrôle de couple; Commodes rétro-éclairés; Contrôle du frein moteur » [Source](https://www.motoplanete.com/honda/11471/Forza-750-2026/contact.html).

- Rang 2, `aaa5c7ffd0a53d40:section:5` — Honda Forza 750 2025, Équipement de série : « Assistance au freinage : ABS; Nombre de mode de conduite : 5; Taille de l'écran TFT couleur : 12,70 cm / 5 pouces; Jantes aluminium; Béquille centrale; Indicateur de vitesse engagée; Régulateur de vitesse; Bluetooth; Prise USB; Démarrage sans clé; Pare brise réglable électriquement; Contrôle de couple; Commodes rétro-éclairés; Contrôle du frein moteur » [Source](https://www.motoplanete.com/honda/10910/Forza-750-2025/contact.html).

### HOLDOUT-028 — excluded_variant

Quels coloris sont réellement écrits pour la Ducati Monster standard 2024 ? Je ne veux pas ceux de la SP.

Les coloris de Monster SP ou Monster Hunter ne sont pas ceux de la Monster standard explicitement demandée.

Preuves attendues :

- `284312cf0b7a7ed2:section:9` — Ducati Monster 2024, Coloris : « Coloris : rouge; Coloris : gris; Coloris : blanc » [Source](https://www.motoplanete.com/ducati/9868/Monster-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `bee3c7dd647a8e92:section:9` — Ducati Monster SP "Monster Hunter" 2024, Coloris : « Coloris : non défini » [Source](https://www.motoplanete.com/ducati/10848/Monster-SP-Monster-Hunter-2024/contact.html).

- Rang 2, `02d3dd07d44cc430:section:9` — Ducati Monster SP 2024, Coloris : « Coloris : rouge / noir » [Source](https://www.motoplanete.com/ducati/10190/Monster-SP-2024/contact.html).

### HOLDOUT-038 — incomplete_comparison

Honda CRF 1100 L Africa Twin 2024 et Adventure Sports 2024 : laquelle a une roue avant de 19 pouces, et leurs selles se règlent entre quelles hauteurs ?

Lire train avant et châssis des deux Africa Twin : une preuve Adventure Sports ne couvre pas la standard.

Preuves attendues :

- `16e03bf9b38a2949:section:1` — Honda CRF 1100 L Africa Twin 2024, Train avant : « Fourche téléhydraulique inversée Ø 45 mm, déb : 230 mm; Freinage : 2 disques Ø 310 mm, fixation radiale, étrier 4 pistons; Roue avant : 90 / 90 - 21; Pression : 2.25 bars » [Source](https://www.motoplanete.com/honda/10064/CRF-1100-L-Africa-Twin-2024/contact.html).

- `eb337e430e4513b5:section:1` — Honda CRF 1100 L Africa Twin Adventure Sports 2024, Train avant : « Fourche téléhydraulique inversée Ø 45 mm, déb : 210 mm; Réglage de la compression et de la détente; Freinage : 2 disques Ø 310 mm, fixation radiale, étrier 4 pistons; Roue avant : 110 / 80 - 19 » [Source](https://www.motoplanete.com/honda/10068/CRF-1100-L-Africa-Twin-Adventure-Sports-2024/contact.html).

- `16e03bf9b38a2949:section:0` — Honda CRF 1100 L Africa Twin 2024, Châssis : « Cadre : Double poutre + simple berceau dédoublé en acier; Réservoir : 18,80 litres; Hauteur de selle réglable entre 850 mm et 870 mm; Longueur : 2 330 mm; Largeur : 960 mm; Hauteur min : 1 485 mm; Empattement : 1 570 mm; Poids tous pleins faits : 231 kg » [Source](https://www.motoplanete.com/honda/10064/CRF-1100-L-Africa-Twin-2024/contact.html).

- `eb337e430e4513b5:section:0` — Honda CRF 1100 L Africa Twin Adventure Sports 2024, Châssis : « Cadre : Double poutre + simple berceau dédoublé en acier; Réservoir : 24,80 litres; Hauteur de selle réglable entre 835 mm et 855 mm; Longueur : 2 305 mm; Largeur : 960 mm; Hauteur min : 1 475 mm; Empattement : 1 575 mm; Poids tous pleins faits : 253 kg » [Source](https://www.motoplanete.com/honda/10068/CRF-1100-L-Africa-Twin-Adventure-Sports-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 2, `eb337e430e4513b5:section:3` — Honda CRF 1100 L Africa Twin Adventure Sports 2024, Train arrière : « Mono-amortisseur, déb : 200 mm; Réglage de la précharge, de la compression et de la détente; Freinage : 1 disque Ø 256 mm, étrier simple piston; Roue arrière : 150 / 70 - 18 » [Source](https://www.motoplanete.com/honda/10068/CRF-1100-L-Africa-Twin-Adventure-Sports-2024/contact.html).

- Rang 4, `ec5d9933968050a4:section:0` — Honda CRF 1100 L Africa Twin Adventure Sports 2022, Châssis : « Cadre : Double poutre + simple berceau dédoublé en acier; Réservoir : 24,80 litres; Hauteur de selle réglable entre 850 mm et 870 mm; Longueur : 2 330 mm; Largeur : 960 mm; Hauteur entre 1 490 mm et 1 545 mm; Empattement : 1 575 mm; Poids tous pleins faits : 238 kg » [Source](https://www.motoplanete.com/honda/8887/CRF-1100-L-Africa-Twin-Adventure-Sports-2022/contact.html).

### HOLDOUT-039 — incomplete_comparison

Kawasaki Z 900 2024 contre Z 900 SE 2024 : la fiche cite-t-elle Brembo pour les deux, et les dimensions de fourche et de disques avant diffèrent-elles ?

La SE Performance ne remplace pas la SE ; lire les deux trains avant standard/SE, sans transformer une absence de mention Brembo en absence de marque.

Preuves attendues :

- `4a1aafa4f4cf6001:section:1` — Kawasaki Z 900 2024, Train avant : « Fourche téléhydraulique inversée Ø 41 mm, déb : 120 mm; Freinage : 2 disques Ø 300 mm, étrier 4 pistons; Roue avant : 120 / 70 - 17; Pression : 2.5 bars » [Source](https://www.motoplanete.com/kawasaki/9989/Z-900-2024/contact.html).

- `507e76e937b8921f:section:1` — Kawasaki Z 900 SE 2024, Train avant : « Fourche téléhydraulique inversée Ø 41 mm, déb : 120 mm; Freinage : 2 disques Brembo Ø 300 mm, étrier 4 pistons; Roue avant : 120 / 70 - 17; Pression : 2.5 bars » [Source](https://www.motoplanete.com/kawasaki/9996/Z-900-SE-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. L’absence d’un équipement ou d’un coloris dans cette extraction ne prouve pas son indisponibilité réelle. Ne pas affirmer la marque des pièces de la standard quand elle n’est pas écrite.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 2, `f33f15b781aa31a0:section:1` — Kawasaki Z 900 SE Performance 2024, Train avant : « Fourche téléhydraulique inversée Ø 41 mm, déb : 120 mm; Réglage de la précharge, de la compression et de la détente; Freinage : 2 disques Brembo Ø 300 mm, fixation radiale, étrier 4 pistons; Roue avant : 120 / 70 - 17; Pression : 2.5 bars » [Source](https://www.motoplanete.com/kawasaki/10550/Z-900-SE-Performance-2024/contact.html).

- Rang 3, `0053ed60ac009b1a:section:1` — Kawasaki Z 900 SE 2023, Train avant : « Fourche téléhydraulique inversée Ø 41 mm, déb : 120 mm; Freinage : 2 disques Brembo Ø 300 mm, étrier 4 pistons; Roue avant : 120 / 70 - 17; Pression : 2.5 bars » [Source](https://www.motoplanete.com/kawasaki/9519/Z-900-SE-2023/contact.html).

### HOLDOUT-041 — wrong_year_changes_fact

Pour les Yamaha Tracer 9 GT et GT+ de 2024, la base parle-t-elle d’une boîte automatique et d’un radar sur les deux ?

Le premier passage GT+ 2025 semi-robotisé répondrait faux à une comparaison des transmissions 2024 ; conserver aussi les preuves de radar.

Preuves attendues :

- `6e32b3574417e76e:section:2` — Yamaha Tracer 9 GT 2024, Transmission : « boîte à 6 rapports , manuelle - shifter de série; Secondaire par chaîne » [Source](https://www.motoplanete.com/yamaha/10297/Tracer-9-GT-2024/contact.html).

- `593360357e043c46:section:2` — Yamaha Tracer 9 GT+ 2024, Transmission : « boîte à 6 rapports , manuelle - shifter de série; Secondaire par chaîne » [Source](https://www.motoplanete.com/yamaha/10298/Tracer-9-GT-2024/contact.html).

- `6e32b3574417e76e:section:5` — Yamaha Tracer 9 GT 2024, Équipement de série : « Assistance au freinage : ABS de série; Nombre de mode de conduite : 4; Volume de rangement : 60 litres; Taille de l'écran TFT couleur : 8,89 cm / 3.5 pouces; Jantes aluminium; Shifter; Béquille centrale; Indicateur de vitesse engagée; Régulateur de vitesse; Contrôle de traction; Poignées chauffantes; Pare brise réglable; Suspensions réglables électroniquement; Contrôle anti wheeling; Valises; Jantes forgées; Contrôle de glisse; Embrayage anti-dribble; Selle réglable; Phares adaptatifs en virage; Contrôle du frein moteur » [Source](https://www.motoplanete.com/yamaha/10297/Tracer-9-GT-2024/contact.html).

- `593360357e043c46:section:5` — Yamaha Tracer 9 GT+ 2024, Équipement de série : « Assistance au freinage : ABS de série; Nombre de mode de conduite : 4; Taille de l'écran TFT couleur : 17,78 cm / 7 pouces; Shifter; Béquille centrale; Indicateur de vitesse engagée; Régulateur de vitesse; Bluetooth; Prise USB; Contrôle de traction; Poignées chauffantes; Pare brise réglable; Suspensions réglables électroniquement; Contrôle anti wheeling; Valises; Système radar; Contrôle de glisse; Embrayage anti-dribble; Commodes rétro-éclairés; Phares adaptatifs en virage » [Source](https://www.motoplanete.com/yamaha/10298/Tracer-9-GT-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. L’absence d’un équipement ou d’un coloris dans cette extraction ne prouve pas son indisponibilité réelle. Ne pas confondre les fiches 2024 avec un autre millésime ou déduire une boîte automatique du shifter.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `3cc9b91ec07c4148:section:2` — Yamaha Tracer 9 GT+ 2025, Transmission : « boîte à 6 rapports , semi-robotisée; Secondaire par chaîne » [Source](https://www.motoplanete.com/yamaha/11019/Tracer-9-GT-2025/contact.html).

- Rang 2, `4f1e896b22928213:section:2` — Yamaha Tracer 9 GT 2026, Transmission : « boîte à 6 rapports , manuelle - shifter de série - robotisée en option; Secondaire par chaîne » [Source](https://www.motoplanete.com/yamaha/11884/Tracer-9-GT-2026/contact.html).

## Vérification

### HOLDOUT-004 — wrong_section_mass_basis

Pour la Royal-Enfield 450 Himalayan 2024, quelles sont les deux hauteurs de selle et les masses à sec et prête à rouler indiquées ?

Un passage moteur ne couvre pas selle/poids. Conserver séparément 181 kg à sec et 196 kg tous pleins faits dans Châssis.

Preuves attendues :

- `a694ca2a26252015:section:0` — Royal-Enfield 450 Himalayan 2024, Châssis : « Cadre : tubulaire en acier; Réservoir : 17 litres; Hauteur de selle réglable entre 825 mm et 845 mm; Longueur : 2 245 mm; Largeur : 852 mm; Hauteur min : 1 316 mm; Empattement : 1 510 mm; Poids à sec : 181 kg; Poids tous pleins faits : 196 kg » [Source](https://www.motoplanete.com/royal-enfield/10210/450-Himalayan-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. Conserver le libellé tous pleins faits pour la seconde masse ; ne pas attribuer la différence à un composant précis.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `a694ca2a26252015:section:4` — Royal-Enfield 450 Himalayan 2024, Moteur : « Monocylindre , 4 temps; Injection Ø 42 mm; Refroidissement : liquide; 2 ACT; 4 soupapes; 452 cc (Alésage * course: 84 x 81,5 mm); 40 ch à 8 000 tr/min; 4,20 mkg à 5 500 tr/min; Rapport poids / puissance : 4.53 kg/ch; Rapport poids / couple : 43.1 kg/mkg; Compression : 11.5:1; Emission CO² : 76 g/km » [Source](https://www.motoplanete.com/royal-enfield/10210/450-Himalayan-2024/contact.html).

- Rang 2, `ad1cadc7de95e217:section:4` — Royal-Enfield 450 Himalayan 2026, Moteur : « Monocylindre , 4 temps; Injection Ø 42 mm; Refroidissement : liquide; 2 ACT; 4 soupapes; 452 cc (Alésage * course: 84 x 81,5 mm); 40 ch à 8 000 tr/min; 4,20 mkg à 5 500 tr/min; Rapport poids / puissance : 4.53 kg/ch; Rapport poids / couple : 43.1 kg/mkg; Compression : 11.5:1; Système de démarrage : électrique; Emission CO² : 76 g/km; Émission sonore : 91 db » [Source](https://www.motoplanete.com/royal-enfield/12147/450-Himalayan-2026/contact.html).

### HOLDOUT-008 — wrong_year_incomplete

La Suzuki GSX-8R 800 de 2024 fait vraiment 800 cm³ ? Et à quelle hauteur se trouve la selle, avec quel réservoir ?

L'édition anniversaire 2026 ou la fiche 2025 ne prouve pas les valeurs 2024 ; il faut moteur et châssis pour 776 cc, selle et réservoir.

Preuves attendues :

- `e5ae298425ec85ab:section:4` — Suzuki GSX-8R 800 2024, Moteur : « Bicylindre parallèle , 4 temps; Injection Ø 42 mm; Refroidissement : liquide; 2 ACT; 4 soupapes par cylindre; 776 cc (Alésage * course: 84 x 70 mm); 83 ch à 8 500 tr/min; 8 mkg à 6 800 tr/min; Rapport poids / puissance : environ 2.32 kg/ch; Rapport poids / couple : environ 24.05 kg/mkg; Compression : 12.8 : 1; Emission CO² : 99 g/km » [Source](https://www.motoplanete.com/suzuki/10088/GSX-8R-800-2024/contact.html).

- `e5ae298425ec85ab:section:0` — Suzuki GSX-8R 800 2024, Châssis : « Cadre : structure en tubes d'acier; Réservoir : 14 litres; Hauteur de selle : 810 mm; Longueur : 2 150 mm; Largeur : 770 mm; Hauteur min : 1 135 mm; Empattement : 1 465 mm; Poids tous pleins faits : 205 kg » [Source](https://www.motoplanete.com/suzuki/10088/GSX-8R-800-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `7d421688d6cdf817:section:0` — Suzuki GSX-8R 800 Edition Anniversaire 2026, Châssis : « Selle biplaces; Cadre : structure en tubes d'acier; Réservoir : 14 litres; Capacité d'huile : 3,90 litres; Hauteur de selle : 810 mm; Longueur : 2 155 mm; Largeur : 770 mm; Hauteur min : 1 135 mm; Garde au sol min : 145 mm Empattement : 1 465 mm Poids tous pleins faits : 205 kg » [Source](https://www.motoplanete.com/suzuki/12117/GSX-8R-800-Edition-Anniversaire-2026/contact.html).

- Rang 2, `ab101598296196a1:section:0` — Suzuki GSX-8R 800 2025, Châssis : « Selle biplaces; Cadre : structure en tubes d'acier; Réservoir : 14 litres; Capacité d'huile : 3,90 litres; Hauteur de selle : 810 mm; Longueur : 2 155 mm; Largeur : 770 mm; Hauteur min : 1 135 mm; Empattement : 1 465 mm; Poids tous pleins faits : 205 kg » [Source](https://www.motoplanete.com/suzuki/10813/GSX-8R-800-2025/contact.html).

### HOLDOUT-012 — missing_second_topic

La Harley-Davidson RH 975 Nightster 2024 a quel angle entre ses deux cylindres, et quelle hauteur de selle ?

Le moteur répond à l'angle de 60°, mais la hauteur de selle est dans Châssis ; ne pas s'arrêter au premier bon passage.

Preuves attendues :

- `d646e539b110fb4b:section:4` — Harley-Davidson RH 975 Nightster 2024, Moteur : « Bicylindre en V à 60° , 4 temps; Injection; Refroidissement : liquide; 2 ACT, disribution variable; 4 soupapes par cylindre; 975 cc (Alésage * course: 97 x 66 mm); 89 ch à 7 500 tr/min; 9,70 mkg à 5 750 tr/min; Rapport poids / puissance : 2.37 kg/ch; Rapport poids / couple : 21.75 kg/mkg; Compression : 12 : 1; Emission CO² : 128 g/km » [Source](https://www.motoplanete.com/harley-davidson/10262/RH-975-Nightster-2024/contact.html).

- `d646e539b110fb4b:section:0` — Harley-Davidson RH 975 Nightster 2024, Châssis : « Cadre : Structures en tubes d'acier; Réservoir : 11,70 litres; Hauteur de selle : 705 mm; Longueur : 2 250 mm; Largeur : 836 mm; Hauteur min : 1 108 mm; Empattement : 1 545 mm; Poids à sec : 211 kg; Poids tous pleins faits : 221 kg » [Source](https://www.motoplanete.com/harley-davidson/10262/RH-975-Nightster-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 2, `030bd8d030d19064:section:4` — Harley-Davidson RH 975 S Nightster Special 2024, Moteur : « Bicylindre en V à 60° , 4 temps; Injection; Refroidissement : liquide; 2 ACT, disribution variable; 4 soupapes par cylindre; 975 cc (Alésage * course: 97 x 66 mm); 89 ch à 7 500 tr/min; 9,70 mkg à 5 750 tr/min; Rapport poids / puissance : 2.43 kg/ch; Rapport poids / couple : 22.27 kg/mkg; Compression : 12 : 1; Emission CO² : 128 g/km » [Source](https://www.motoplanete.com/harley-davidson/10263/RH-975-S-Nightster-Special-2024/contact.html).

- Rang 3, `aa875368936b1b7a:section:0` — Harley-Davidson RH 975 Nightster 2026, Châssis : « Selle biplaces; Cadre : Structures en tubes d'acier; Réservoir : 11,70 litres; Capacité d'huile : 4,50 litres; Hauteur de selle : 705 mm; Longueur : 2 250 mm; Largeur : 840 mm; Hauteur min : 1 108 mm; Garde au sol min : 110 mm Empattement : 1 545 mm Poids à sec : 211 kg Poids tous pleins faits : 220 kg » [Source](https://www.motoplanete.com/harley-davidson/11752/RH-975-Nightster-2026/contact.html).

### HOLDOUT-022 — missing_qualification

Sur une Suzuki GSX-8S 800 2024, le contrôle de traction et le shifter sont mentionnés ? Pour le shifter, quelle précision donne la transmission ?

La transmission seule ne prouve pas la mention du contrôle de traction ; conserver aussi la liste des équipements 2024.

Preuves attendues :

- `3c7991fb5c47484a:section:5` — Suzuki GSX-8S 800 2024, Équipement de série : « Assistance au freinage : ABS; Nombre de mode de conduite : 3; Taille de l'écran TFT couleur : 12,70 cm / 5 pouces; Jantes aluminium; Shifter; Indicateur de vitesse engagée; Aide au démarrage; Aide à la manoeuvre; Contrôle de traction; Embrayage anti-dribble » [Source](https://www.motoplanete.com/suzuki/10161/GSX-8S-800-2024/contact.html).

- `3c7991fb5c47484a:section:2` — Suzuki GSX-8S 800 2024, Transmission : « boîte à 6 rapports , manuelle - shifter de série; Secondaire par chaîne » [Source](https://www.motoplanete.com/suzuki/10161/GSX-8S-800-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 2, `d699e8b8d747b332:section:2` — Suzuki GSX-8S 800 édition Kevin Schwantz 2023, Transmission : « boîte à 6 rapports , manuelle - shifter de série; Secondaire par chaîne » [Source](https://www.motoplanete.com/suzuki/10010/GSX-8S-800-edition-Kevin-Schwantz-2023/contact.html).

- Rang 3, `f5bb5945265002d8:section:2` — Suzuki 800 GSX-8R Legend Edition 2024, Transmission : « boîte à 6 rapports , manuelle - shifter de série; Secondaire par chaîne » [Source](https://www.motoplanete.com/suzuki/10841/800-GSX-8R-Legend-Edition-2024/contact.html).

### HOLDOUT-026 — colour_control

La Triumph 660 Trident 2025 est citée en bleu uni ou en bleu avec une autre couleur ? Donne les combinaisons écrites.

Le résultat correct bleu/noir doit rester prioritaire ; la Tribute Edition n'établit pas toutes les combinaisons de la version visée.

Preuves attendues :

- `0ce7454d1b7fa796:section:9` — Triumph 660 Trident 2025, Coloris : « Coloris : bleu / noir; Coloris : jaune / noir; Coloris : rouge / noir; Coloris : noir » [Source](https://www.motoplanete.com/triumph/10851/660-Trident-2025/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. La désignation bleu / noir doit être conservée ; ne pas réduire les bicolores à leur couleur principale.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 2, `49d6ef0875131f2f:section:9` — Triumph 660 Trident Tribute Edition 2025, Coloris : « Coloris : bleu / noir » [Source](https://www.motoplanete.com/triumph/11290/660-Trident-Tribute-Edition-2025/contact.html).

- Rang 3, `d465caee3ef392ee:section:9` — Triumph 660 Trident Tribute Edition 2024, Coloris : « Coloris : bleu / blanc / rouge » [Source](https://www.motoplanete.com/triumph/10543/660-Trident-Tribute-Edition-2024/contact.html).

### HOLDOUT-033 — exact_a2_variant_control

Sur la Triumph 765 Street Triple R A2 2025, quels chevaux et quelle cylindrée sont écrits, et que dit la rubrique permis ?

La R A2 annonce 94 ch ; la R voisine 120 ch. Conserver moteur et mention de permis, sans certifier un exemplaire.

Preuves attendues :

- `e1eb267f9d1f697b:section:4` — Triumph 765 Street Triple R A2 2025, Moteur : « 3 cylindres en ligne , 4 temps; Injection; Refroidissement : liquide; 2 ACT; 4 soupapes par cylindre; 765 cc (Alésage * course: 77.99 x 53.4 mm); 94 ch à 10 100 tr/min; 7,20 mkg à 8 750 tr/min; Rapport poids / puissance : environ 1.87 kg/ch; Rapport poids / couple : environ 24.4 kg/mkg; Compression : 13,25 : 1; Emission CO² : 120 g/km » [Source](https://www.motoplanete.com/triumph/10695/765-Street-Triple-R--A2-2025/contact.html).

- `e1eb267f9d1f697b:section:6` — Triumph 765 Street Triple R A2 2025, Infos pratiques : « Véhicule accessible au permis A2 ou bridable à 47.5ch / 35 Kw; La moto est accessible aux permis : A, A2 » [Source](https://www.motoplanete.com/triumph/10695/765-Street-Triple-R--A2-2025/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. Une mention A2 ou de bridage sur Motoplanete ne prouve ni une homologation, ni l’existence d’un kit précis, ni la configuration légale d’un exemplaire. Aucun corpus juridique officiel ou certificat constructeur n’est fourni. Le A2 du nom du modèle ne démontre pas que la puissance inscrite est celle d’un exemplaire déjà bridé.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 2, `4a41f060667a4657:section:4` — Triumph 765 Street Triple R 2025, Moteur : « 3 cylindres en ligne , 4 temps; Injection; Refroidissement : liquide; 2 ACT; 4 soupapes par cylindre; 765 cc (Alésage * course: 77.99 x 53.4 mm); 120 ch à 11 500 tr/min; 8,20 mkg à 9 500 tr/min; Rapport poids / puissance : environ 1.46 kg/ch; Rapport poids / couple : environ 21.42 kg/mkg; Compression : 13,25 : 1; Emission CO² : 120 g/km » [Source](https://www.motoplanete.com/triumph/10607/765-Street-Triple-R-2025/contact.html).

- Rang 4, `c28516902dad7523:section:4` — Triumph 765 Street Triple R 2022, Moteur : « 3 cylindres en ligne , 4 temps; Injection; Refroidissement : liquide; 2 ACT; 4 soupapes par cylindre; 765 cc (Alésage * course: 77.99 x 53.4 mm); 118 ch à 12 000 tr/min; 7,90 mkg à 9 400 tr/min; Rapport poids / puissance : 1.42 kg/ch; Rapport poids / couple : 21.27 kg/mkg; Compression : 12.5 : 1; Emission CO² : 119 g/km » [Source](https://www.motoplanete.com/triumph/9125/765-Street-Triple-R-2022/contact.html).

### HOLDOUT-034 — missing_second_topic_source_limit

Je regarde une Royal-Enfield Meteor 350 2024 avec mon A2. Quelle puissance donne la fiche et cite-t-elle ce permis, sans faire une déduction réglementaire ?

La puissance 20 ch n'établit pas A2 ; restituer la rubrique ne mentionnant que A, sans transformer ce silence en incompatibilité réglementaire.

Preuves attendues :

- `9932cf3c8b15ee49:section:4` — Royal-Enfield Meteor 350 2024, Moteur : « Monocylindre , 4 temps; Injection; Refroidissement : par air; 1 ACT; 2 soupapes; 349 cc (Alésage * course: 70 x 90 mm); 20 ch à 6 100 tr/min; 2,90 mkg à 4 000 tr/min; Rapport poids / puissance : 9.55 kg/ch; Rapport poids / couple : 65.86 kg/mkg; Compression : 9.5 : 1; Emission CO² : 67 g/km » [Source](https://www.motoplanete.com/royal-enfield/10288/Meteor-350-2024/contact.html).

- `9932cf3c8b15ee49:section:6` — Royal-Enfield Meteor 350 2024, Infos pratiques : « La moto est accessible aux permis : A » [Source](https://www.motoplanete.com/royal-enfield/10288/Meteor-350-2024/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. Une mention A2 ou de bridage sur Motoplanete ne prouve ni une homologation, ni l’existence d’un kit précis, ni la configuration légale d’un exemplaire. Aucun corpus juridique officiel ou certificat constructeur n’est fourni. Le permis A2 n’est pas documenté pour cette fiche ; son silence ne constitue pas un refus d’éligibilité.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 2, `9b9fa6fd48a80d63:section:4` — Royal-Enfield Meteor 350 Aurora 2024, Moteur : « Monocylindre , 4 temps; Injection; Refroidissement : par air; 1 ACT; 2 soupapes; 349 cc (Alésage * course: 70 x 90 mm); 20,20 ch à 6 100 tr/min; 2,90 mkg à 4 000 tr/min; Rapport poids / puissance : 9.46 kg/ch; Rapport poids / couple : 65.86 kg/mkg; Compression : 9.5 : 1; Emission CO² : 67 g/km » [Source](https://www.motoplanete.com/royal-enfield/10285/Meteor-350-Aurora-2024/contact.html).

- Rang 3, `0bcc78b5c63433ae:section:4` — Royal-Enfield Meteor 350 Stellar 2024, Moteur : « Monocylindre , 4 temps; Injection; Refroidissement : par air; 1 ACT; 2 soupapes; 349 cc (Alésage * course: 70 x 90 mm); 20 ch à 6 100 tr/min; 2,90 mkg à 4 000 tr/min; Rapport poids / puissance : 9.55 kg/ch; Rapport poids / couple : 65.86 kg/mkg; Compression : 9.5 : 1 » [Source](https://www.motoplanete.com/royal-enfield/10287/Meteor-350-Stellar-2024/contact.html).

### HOLDOUT-040 — incomplete_comparison_qualification

La Triumph 660 Trident 2025 apporte quoi par rapport à la 2024 pour le shifter, le régulateur et le nombre de modes de conduite, selon les fiches ?

Conserver les deux années et transmission/équipements utiles : shifter option en 2024, série en 2025 ; régulateur 2024 non cité, pas déclaré absent.

Preuves attendues :

- `2973af16198fdb41:section:2` — Triumph 660 Trident 2024, Transmission : « boîte à 6 rapports , manuelle - shifter en option; Secondaire par chaîne » [Source](https://www.motoplanete.com/triumph/9920/660-Trident-2024/contact.html).

- `0ce7454d1b7fa796:section:2` — Triumph 660 Trident 2025, Transmission : « boîte à 6 rapports , manuelle - shifter de série; Secondaire par chaîne » [Source](https://www.motoplanete.com/triumph/10851/660-Trident-2025/contact.html).

- `2973af16198fdb41:section:5` — Triumph 660 Trident 2024, Équipement de série : « Assistance au freinage : ABS; Nombre de mode de conduite : 2; Jantes aluminium; Indicateur de vitesse engagée; Contrôle de traction; Embrayage anti-dribble » [Source](https://www.motoplanete.com/triumph/9920/660-Trident-2024/contact.html).

- `0ce7454d1b7fa796:section:5` — Triumph 660 Trident 2025, Équipement de série : « Assistance au freinage : ABS; Nombre de mode de conduite : 3; ABS Cornering; Jantes aluminium; Shifter; Indicateur de vitesse engagée; Régulateur de vitesse; Bluetooth; Contrôle de traction; Embrayage anti-dribble » [Source](https://www.motoplanete.com/triumph/10851/660-Trident-2025/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. L’absence d’un équipement ou d’un coloris dans cette extraction ne prouve pas son indisponibilité réelle. Le fait que le régulateur ne soit pas extrait en 2024 ne prouve pas l’absence sur toute configuration 2024.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 2, `2973af16198fdb41:section:4` — Triumph 660 Trident 2024, Moteur : « 3 cylindres en ligne , 4 temps; Injection; Refroidissement : liquide; 2 ACT; 4 soupapes par cylindre; 660 cc (Alésage * course: 74 x 51.1 mm); 81 ch à 10 250 tr/min; 6,60 mkg à 6 250 tr/min; Rapport poids / puissance : environ 2.18 kg/ch; Rapport poids / couple : environ 26.73 kg/mkg; Compression : 11.95 : 1; Emission CO² : 107 g/km » [Source](https://www.motoplanete.com/triumph/9920/660-Trident-2024/contact.html).

- Rang 3, `0ce7454d1b7fa796:section:4` — Triumph 660 Trident 2025, Moteur : « 3 cylindres en ligne , 4 temps; Injection; Refroidissement : liquide; 2 ACT; 4 soupapes par cylindre; 660 cc (Alésage * course: 74 x 51.1 mm); 81 ch à 10 250 tr/min; 6,60 mkg à 6 250 tr/min; Rapport poids / puissance : environ 2.19 kg/ch; Rapport poids / couple : environ 26.88 kg/mkg; Compression : 11.95 : 1; Emission CO² : 107 g/km » [Source](https://www.motoplanete.com/triumph/10851/660-Trident-2025/contact.html).

### HOLDOUT-044 — wrong_section_ambiguous_year

On me propose une Royal-Enfield 450 Himalayan blanche, année oubliée. Entre les fiches 2024 et 2025, laquelle cite le blanc, et cela suffit-il à dater la moto ?

Les passages moteur/permis ne prouvent pas les coloris ; comparer les deux rubriques Coloris et conserver la limite sur la datation de l'exemplaire.

Preuves attendues :

- `a694ca2a26252015:section:9` — Royal-Enfield 450 Himalayan 2024, Coloris : « Coloris : bleu; Coloris : jaune / noir; Coloris : vert; Coloris : beige; Coloris : rouge / gris » [Source](https://www.motoplanete.com/royal-enfield/10210/450-Himalayan-2024/contact.html).

- `75ec63edc171c1bc:section:9` — Royal-Enfield 450 Himalayan 2025, Coloris : « Coloris : blanc; Coloris : jaune / noir; Coloris : gris; Coloris : rouge / gris; Coloris : beige » [Source](https://www.motoplanete.com/royal-enfield/11248/450-Himalayan-2025/contact.html).

Limites à conserver : Les jugements sont exhaustifs uniquement pour les fiches fournies dans le périmètre ; des passages équivalents d’autres fiches ne sont pas déclarés non pertinents globalement. Les valeurs sont celles de la fiche Motoplanete figée, avec ses libellés et unités ; elles ne constituent pas une vérification indépendante du constructeur ni une spécification distincte par marché. L’absence d’un équipement ou d’un coloris dans cette extraction ne prouve pas son indisponibilité réelle. La couleur seule ne date pas un exemplaire : année, marché, peinture ajoutée et identité complète restent inconnus. Les deux candidats sont un périmètre de comparaison, pas toute l’histoire mondiale du modèle.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `a694ca2a26252015:section:4` — Royal-Enfield 450 Himalayan 2024, Moteur : « Monocylindre , 4 temps; Injection Ø 42 mm; Refroidissement : liquide; 2 ACT; 4 soupapes; 452 cc (Alésage * course: 84 x 81,5 mm); 40 ch à 8 000 tr/min; 4,20 mkg à 5 500 tr/min; Rapport poids / puissance : 4.53 kg/ch; Rapport poids / couple : 43.1 kg/mkg; Compression : 11.5:1; Emission CO² : 76 g/km » [Source](https://www.motoplanete.com/royal-enfield/10210/450-Himalayan-2024/contact.html).

- Rang 2, `75ec63edc171c1bc:section:6` — Royal-Enfield 450 Himalayan 2025, Infos pratiques : « La moto est accessible aux permis : A; Pays de fabrication : Inde » [Source](https://www.motoplanete.com/royal-enfield/11248/450-Himalayan-2025/contact.html).

## Limites de couverture

### HOLDOUT-045 — coverage_authority_gap

Retrouve le certificat officiel de bridage A2 de la KTM 790 Duke 2024 et son numéro d’homologation français.

Une mention commerciale A2 n'est ni le certificat officiel de bridage ni un numéro d'homologation.

Aucune preuve positive de l’autorité ou du document demandé dans ce snapshot. Une fiche commerciale retrouvée ne comble pas ce manque.

Limites à conserver : La fiche cite A2 ou bridage, mais aucun certificat officiel, numéro d’homologation français ou corpus juridique officiel ne figure dans cette base. La mention commerciale ne prouve pas le certificat demandé. Le corpus figé contient uniquement des extractions de fiches techniques Motoplanete, pas le document demandé. Une fiche ressemblante ou une mention voisine n’est pas une réponse. Ne pas inventer de chiffre, de document, de lien constructeur ou de verdict. Indiquer précisément la donnée ou la source manquante.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `08413f04a1acc6df:section:6` — KTM 790 Duke 2024, Infos pratiques : « Véhicule accessible au permis A2 ou bridable à 47.5ch / 35 Kw; La moto est accessible aux permis : A, A2 » [Source](https://www.motoplanete.com/ktm/10069/790-Duke-2024/contact.html).

- Rang 2, `4198bdff2e6960a3:section:6` — KTM 790 Duke 2022, Infos pratiques : « Véhicule accessible au permis A2 ou bridable à 47.5ch / 35 Kw; La moto est accessible aux permis : A, A2 » [Source](https://www.motoplanete.com/ktm/9344/790-Duke-2022/contact.html).

### HOLDOUT-046 — coverage_gap

Pour la Honda NC 750 X 2024, donne le schéma constructeur du connecteur du calculateur avec le numéro de broche du capteur de béquille.

La fiche technique n'est pas un schéma constructeur de câblage ; aucun numéro de broche ne doit être inventé.

Aucune preuve positive de l’autorité ou du document demandé dans ce snapshot. Une fiche commerciale retrouvée ne comble pas ce manque.

Limites à conserver : Aucun schéma électrique constructeur, brochage de calculateur ou documentation de capteur de béquille n’est présent. Les données moteur et DCT ne permettent pas de déduire le numéro de broche. Le corpus figé contient uniquement des extractions de fiches techniques Motoplanete, pas le document demandé. Une fiche ressemblante ou une mention voisine n’est pas une réponse. Ne pas inventer de chiffre, de document, de lien constructeur ou de verdict. Indiquer précisément la donnée ou la source manquante.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `ca659e852f01b07e:section:4` — Honda NC 750 X 2024, Moteur : « Bicylindre en ligne , 4 temps; Injection Ø 36 mm; Refroidissement : liquide; 1 ACT; 4 soupapes par cylindre; 745 cc (Alésage * course: 77 x 80 mm); 58,50 ch à 6 750 tr/min; 7,10 mkg à 4 750 tr/min; Rapport poids / puissance : environ 3.61 kg/ch; Rapport poids / couple : environ 29.78 kg/mkg; Compression : 10.7 : 1; Emission CO² : 82 g/km » [Source](https://www.motoplanete.com/honda/10218/NC-750-X-2024/contact.html).

- Rang 2, `2f30b910489d97b2:section:4` — Honda NC 750 X 2023, Moteur : « Bicylindre en ligne , 4 temps; Injection Ø 36 mm; Refroidissement : liquide; 1 ACT; 4 soupapes par cylindre; 745 cc (Alésage * course: 77 x 80 mm); 58,50 ch à 6 750 tr/min; 7,10 mkg à 4 750 tr/min; Rapport poids / puissance : environ 3.61 kg/ch; Rapport poids / couple : environ 29.78 kg/mkg; Compression : 10.7 : 1; Emission CO² : 82 g/km » [Source](https://www.motoplanete.com/honda/9558/NC-750-X-2023/contact.html).

### HOLDOUT-048 — coverage_authority_market_gap

Pour une BMW R 1250 GS 2023 destinée aux États-Unis, retrouve dans les documents BMW la masse remorquable homologuée et la référence du document.

La fiche conservée ne constitue pas le document BMW d'homologation US demandé.

Aucune preuve positive de l’autorité ou du document demandé dans ce snapshot. Une fiche commerciale retrouvée ne comble pas ce manque.

Limites à conserver : Aucune documentation BMW de marché américain ni valeur homologuée de remorquage n’est présente. L’identité technique n’est pas séparée par marché ; ne pas inventer une variante américaine ou traiter un prix de pays comme preuve d’un régime d’homologation. Le corpus figé contient uniquement des extractions de fiches techniques Motoplanete, pas le document demandé. Une fiche ressemblante ou une mention voisine n’est pas une réponse. Ne pas inventer de chiffre, de document, de lien constructeur ou de verdict. Indiquer précisément la donnée ou la source manquante.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `4d902be1a67428c8:section:4` — BMW R 1250 GS 2023, Moteur : « Bicylindre à plat , 4 temps; Injection Ø 52 mm; Refroidissement : liquide; 2 ACT, variable; 4 soupapes par cylindre; 1 254 cc (Alésage * course: 102.5 x 76 mm); 136 ch à 7 750 tr/min; 14,50 mkg à 6 250 tr/min; Rapport poids / puissance : environ 1.71 kg/ch; Rapport poids / couple : environ 15.99 kg/mkg; Compression : 12.5 : 1; Emission CO² : 110 g/km » [Source](https://www.motoplanete.com/bmw/9459/R-1250-GS-2023/contact.html).

- Rang 2, `4f8d7d5ecf54bd0c:section:4` — BMW R 1250 RS 2023, Moteur : « Bicylindre à plat , 4 temps; Injection Ø 52 mm; Refroidissement : liquide; 2 ACT, variable; 4 soupapes par cylindre; 1 254 cc (Alésage * course: 102.5 x 76 mm); 136 ch à 7 750 tr/min; 14,50 mkg à 6 250 tr/min; Rapport poids / puissance : environ 1.67 kg/ch; Rapport poids / couple : environ 15.68 kg/mkg; Compression : 12.5 : 1; Emission CO² : 110 g/km » [Source](https://www.motoplanete.com/bmw/9632/R-1250-RS-2023/contact.html).

### HOLDOUT-049 — coverage_gap

Quel intervalle en kilomètres le manuel d’atelier Kawasaki prescrit-il pour contrôler le jeu aux soupapes d’une Ninja 500 2024 ?

Un intervalle de contrôle du jeu aux soupapes exige une source d'entretien absente de ce corpus de fiches.

Aucune preuve positive de l’autorité ou du document demandé dans ce snapshot. Une fiche commerciale retrouvée ne comble pas ce manque.

Limites à conserver : Aucun manuel d’atelier Kawasaki ni calendrier d’entretien avec contrôle du jeu aux soupapes n’est présent. Le nombre de soupapes dans une fiche moteur ne donne pas l’intervalle d’entretien. Le corpus figé contient uniquement des extractions de fiches techniques Motoplanete, pas le document demandé. Une fiche ressemblante ou une mention voisine n’est pas une réponse. Ne pas inventer de chiffre, de document, de lien constructeur ou de verdict. Indiquer précisément la donnée ou la source manquante.

Passages trompeurs observés dans la recherche dense historique (ne pas les convertir automatiquement en négatifs universels) :

- Rang 1, `a30f5db21011a187:section:4` — Kawasaki Ninja 500 2024, Moteur : « Bicylindre parallèle , 4 temps; Injection Ø 32 mm; Refroidissement : liquide; 2 ACT; 4 soupapes par cylindre; 451 cc (Alésage * course: 70 x 58,6 mm); 45,40 ch à 9 000 tr/min; 4,30 mkg à 6 000 tr/min; Rapport poids / puissance : environ 3.49 kg/ch; Rapport poids / couple : environ 36.84 kg/mkg; Compression : 11.3 : 1; Système de démarrage : électrique; Emission CO² : 89 g/km » [Source](https://www.motoplanete.com/kawasaki/10363/Ninja-500-2024/contact.html).

- Rang 2, `b2c29c5805fef512:section:7` — Kawasaki Ninja 1000 ZX-10RR WSBK-Edition 2024, Performances : « Vitesse max : environ 300 km/h; Consommation moyenne : 6,10 l/100km; Autonomie estimée : 279 km Autonomie jusqu'à la panne sèche, calculée mais non vérifiée. » [Source](https://www.motoplanete.com/kawasaki/9987/Ninja-1000-ZX-10RR-WSBK-Edition-2024/contact.html).

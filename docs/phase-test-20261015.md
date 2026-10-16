# Prochaine phase : validation du parcours complet

Plan préparé le 15 octobre 2026 à la clôture du [bilan #4](https://github.com/maax6/bikefinder-rag/issues/4).
**Mise à jour du 16 octobre :** [XJ6, avertissements et qualité des réponses](benchmark-chat-20261016.html).
Reprise de 57 tours, six répétitions et huit contrôles ciblés. Dix questions
publiques et un dialogue XJ6 de deux tours ont ensuite été exécutés, puis XJ6
a été rejoué après suppression d’un doublon A2 : 85 soumissions, grille sur
30 réponses. Les questions publiques donnent 3 limites justifiées, 2 réponses
partielles et 5 échecs. Les formulations sont externes ; la relecture reste
celle de l’assistant et ne constitue pas une validation humaine indépendante.
**Après correction des questions publiques :** les cinq échecs et deux réponses
partielles obtiennent désormais une réponse sourcée ou une limite utile sur leur
rejeu connu. Aucune perte de contenu sur les 69 tours comparables ; la rédaction
Mistral ralentit à 28,2 s de médiane avec neuf expirations. Le nouveau bilan
sépare ces limites des progrès fonctionnels et conserve la première passe.
**Campagne exploratoire puis corrections exécutées le 15 octobre 2026 :**
[Bilan avant/après via le vrai chat, avec BGE-M3 d’origine](bilan-chat-20261015.md).
Le lot comparable passe de 25/36 à 36/36 réponses satisfaisantes ; 15 tours
supplémentaires passent, dont trois sur le prix moyen. Aucune régression de
contenu observée sur les 42 tours appariés ; le cas XJ6 A2 reste partiel.
Le plan ci-dessous reste la cible de validation complète : cette campagne
ne remplace pas le lot final relu indépendamment ni le raccordement du service commun.

## Point de départ

Le chat existant et le service commun SQL + RAG sont deux parcours distincts.
Les comparer exige d’identifier celui qui reçoit réellement la question, le
modèle appelé et les preuves livrées. Le service commun reste à raccorder à
l’interface ; un test direct de ses outils ne valide pas ce raccordement.

BGE-M3 d’origine reste la référence. La fusion ajustée perd des preuves sur
quatre cas ; le pilote LoRA en perd sur neuf. Ces candidats restent isolés.
Les [résultats du fine-tuning](https://maax6.github.io/bikefinder-rag/benchmark-finetuning.html)
ne sont pas des scores de réponses finales du chat.

## Séquence proposée

1. **Figer une référence reproductible.** Relever versions, configuration,
   empreintes du corpus/index, modèles, outils, plafonds et état des caches.
   Vérifier le chat existant et le service commun séparément, avec les mêmes
   sources. Conserver chargement initial et temps à chaud distincts.
2. **Rejouer les erreurs connues.** Vérifier les pertes de preuves, les confusions
   d’année/variante, les identifiants de citation, l’édition fictive, les comptes
   après un suivi de conversation et la pagination. Ces cas restent des tests
   de régression ; ils ne deviennent pas des questions inédites.
3. **Préparer un nouveau lot final indépendant.** Proposition : 40 questions
   et 10 dialogues courts, avec des formulations écrites ou relues par une autre
   personne. Réserver les fiches/familles au niveau du découpage, annoter les
   preuves et les réponses acceptables avant tout essai, puis figer le lot.
   Si une même fiche revient, l’annoncer et ne pas traiter ses questions comme
   des observations indépendantes.
4. **Mesurer les vraies réponses de la configuration retenue.** Garder les
   appels d’outils, citations, erreurs, temps complets et coûts retournés ou
   manquants. Répéter un sous-ensemble pour observer la variabilité. Le lot final
   ne sert pas à choisir le modèle ou les réglages ; tout réglage utilise un
   lot de développement distinct. Toute comparaison distante supplémentaire
   doit avoir un périmètre de données et un plafond dédiés avant exécution.
5. **Raccorder le service commun au chat, puis valider l’interface.** Une fois
   le parcours choisi sur les mesures, vérifier les conversations via la vraie
   entrée Gradio : suivis, reprises après erreur, sources affichées et inconnus.
   Conserver la configuration précédente pour revenir en arrière si nécessaire.

## Cas à couvrir

| Famille | Vérification attendue |
|---|---|
| Fiche exacte et unités | Bonne année/variante, valeurs et qualificatifs conservés |
| Plusieurs rubriques | Toutes les preuves utiles présentes, pas seulement la première |
| Comparaison de millésimes | Sources et valeurs rattachées à la bonne fiche |
| Équipement | Série, option, absence explicite et inconnu restent distincts |
| Question ambiguë ou édition absente | Clarification ou absence signalée, sans substitution inventée |
| Comptes, filtres et calculs | Résultat SQL/Python vérifiable, critères conservés au tour suivant |
| Conversation et pagination | Continuité des contraintes, pas de doublons ni d’omissions silencieuses |
| Données insuffisantes | Réponse partielle explicite, aucune conclusion sans preuve |

## Critères de sortie à figer avant les essais

- Séparer qualité des réponses, complétude des preuves, identité, latence et coût.
- Présenter les gains **et chaque régression**, avec les passages correspondants.
- Bloquer la promotion d’une configuration qui invente une preuve ou substitue
  silencieusement une identité, même si son score moyen progresse.
- Définir sur le développement le niveau de qualité et les plafonds de temps/coût
  attendus ; ne pas les déplacer après lecture du test final.
- Conserver la première passe, les échecs et les limites d’annotation. Un succès
  de format, un replay de cache ou un test unitaire ne prouve pas la qualité.

Pour reprendre le fine-tuning, travailler d’abord les comparaisons de plusieurs
fiches et les rubriques complémentaires dans les marques d’apprentissage.
Choisir le prochain adaptateur sur la validation, puis utiliser un **nouveau**
test final : les erreurs du pilote actuel sont désormais connues.

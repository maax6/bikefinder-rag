"""Useful boundaries for questions a technical fiche cannot establish.

These are deterministic scope explanations, never generated mechanical advice
or evidence of model reasoning. Match request concepts, not benchmark identities.
"""
import re
from bikefinder_rag.agent.query_language import language


def scope_response(question):
    text = language(question)
    if re.search(r'carross|deboss|renfoncement|repar(?:er|ation)|repair|dent(?:ed|s)?\b', text) and re.search(
            r'reservoir|moto|bike|prix|cout|combien|devis|tank', text):
        return 'repair', ("Le catalogue ne décrit ni les dégâts de ton exemplaire ni les tarifs de réparation. "
            "Il ne permet pas de chiffrer ce travail ou de choisir la bonne intervention. "
            "Demande une inspection et un devis à un professionnel de la réparation ou de la carrosserie moto, "
            "avec des photos et l’identification exacte de la moto. Un prix neuf de catalogue ne serait pas un devis de réparation.")
    mileage = bool(re.search(r'\d[\d\s.,]*\s*(?:km|kilometres?|miles?)\b|kilometrage|mileage', text))
    if re.search(r'fiabilite|reliab|duree de vie', text) or (mileage and re.search(
            r'convenable|raisonnable|trop|beaucoup|acheter|achat|bon etat|risqu|acceptable|too much|too high|worth|buy', text)):
        return 'condition', ("Le kilométrage seul ne permet pas de juger l’état de cette moto. "
            "Les fiches ne donnent ni son historique d’entretien ni le résultat d’une inspection. "
            "Avant de décider, demande les factures et le suivi d’entretien, puis une inspection de l’exemplaire. "
            "Je peux comparer ses caractéristiques documentées, mais pas fixer un seuil de kilométrage fiable ni garantir son état.")
    if re.search(r'vibrations?|vibration wise|ressenti|sensations?|confort', text) and not re.search(
            r'\b(?:selle|siege) confort\b|nom de.*version', text):
        return 'riding_feel', ("Les fiches techniques ne permettent pas de conclure sur le ressenti des vibrations ou le confort sur autoroute. "
            "Un essai dans les conditions envisagées et des retours portant sur la même version seraient utiles. "
            "Pour lire les données du catalogue, précise la variante et le millésime ; "
            "si tu indiques une vitesse, précise son unité (km/h ou mph). Je ne déduis pas le ressenti des seules performances.")
    if re.search(r'petits? gabarits?|petite taille|je mesure|ma taille|short rider', text) and re.search(
            r'conseil|premiere?|1ere?|choisir|pieds|adapt|recommend', text):
        return 'rider_fit', ("Pour préparer une sélection, je peux comparer la hauteur de selle et le poids documentés, "
            "en distinguant poids à sec et tous pleins faits. Ta taille seule ne permet pas de garantir les pieds au sol : "
            "l’ergonomie demande un essai. Quel est ton budget, ton permis, ton usage et les modèles ou millésimes envisagés ? "
            "Le budget du catalogue correspond aux prix de lancement documentés, pas aux annonces actuelles.")
    if re.search(r'bridage|brider|bridable|restrict(?:ed|ion|ing)', text) and re.search(
            r'change|effet|impact|comportement|consommation|\bpoids\b|electronique|mecanique', text):
        return 'restriction_effects', ("Les effets du bridage dépendent de la configuration à comparer ; ces fiches ne décrivent pas "
            "systématiquement la moto avant et après modification. Précise le modèle, la variante, le millésime et le type de bridage "
            "(ou la référence du kit). Je pourrai comparer les caractéristiques explicitement documentées et signaler les manques. "
            "Sans ces preuves, je ne conclus ni sur le poids, ni sur la consommation, ni sur le comportement ou le mécanisme employé.")
    return None

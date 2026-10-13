"""Explicit arithmetic from unambiguous source projections, without generation."""
from decimal import Decimal, ROUND_HALF_UP
import re

from bikefinder_rag.catalog.enriched import folded
from bikefinder_rag.catalog.measures import number, project


_DIFFERENCE = r'\b(?:differences?|ecarts?|de combien)\b'
_POWER = r'\b(?:puissance|puissances|puissant(?:e|es|s)?|ch|cv|chevaux|kw|hp)\b'
_WEIGHT = r'\b(?:poids|leger(?:e|es|s)?|lourd(?:e|es|s)?|kg|kilos?|pleins|ordre de marche)\b'
_DISPLACEMENT = r'\b(?:cylindrees?|cc|cm[3³])\b'
_SEAT = r'\bhauteurs?\s+(?:de\s+)?selle\b'
_CONSEQUENCES = r'\b(?:consequences?|confort|fiabilite|sensations?|maniabilite|adherence|acceleration|pourquoi|effets?|impact)\b'
_RANK_POWER = r'\b(?:(?:plus|moins)\s+puissant(?:e|es|s)?|plus (?:de )?chevaux)\b'
_RANK_WEIGHT = r'\b(?:plus|moins)\s+(?:leger|legere|legers|legeres|lourd|lourde|lourds|lourdes)\b'
_RANK_SEAT = r'\b(?:plus|moins)\s+(?:basse?|basses?|haut(?:e|es|s)?)\s+(?:de\s+)?selle\b|\bselle\s+(?:la\s+)?(?:plus|moins)\s+(?:basse?|haut(?:e|es|s)?)\b'
_RANK_QUESTION = r'\b(?:lequel|laquelle|lesquels|lesquelles|qui|quel modele|quelle moto)\b'
_UNSUPPORTED_UNITS = r'\b(?:kw|hp|ps|lbs?|livres?|pouces?|inches?|cm(?![3³])|metres?)\b'
_RATIO_EXPRESSION = r'\b(?:(?:ratio|rapport)(?:\s+de)?\s+)?(?:puissance\s*(?:/|-|\s+sur\s+)\s*poids|(?:ch|cv)\s*/\s*kg)(?:\s+(?:a sec|tous? pleins(?: faits)?|en ordre de marche))?'


def _ratio_requested(text):
    return bool(re.search(r'\b(?:ch|cv)\s*/\s*kg\b|\bpuissance\s*[/−-]\s*poids\b', text) or (
        re.search(r'\b(?:ratio|rapport)\b', text)
        and re.search(_POWER, text) and re.search(_WEIGHT, text)))


def _weight_field(text):
    dry = bool(re.search(r'\b(?:a sec|sec|secs)\b', text))
    wet = bool(re.search(r'\b(?:tous? pleins(?: faits)?|pleins(?: faits)?|en ordre de marche)\b', text))
    if dry == wet:
        return None
    return 'weight_dry_kg' if dry else 'weight_wet_kg'


def is_arithmetic_question(question):
    """Recognize requested calculations, not a simple side-by-side source table."""
    text = folded(question)
    if re.search(_CONSEQUENCES, text):
        return False
    if _ratio_requested(text):
        return True
    if re.search(_RANK_QUESTION, text) and re.search(_RANK_POWER + '|' + _RANK_WEIGHT + '|' + _RANK_SEAT, text):
        return True
    return bool(re.search(_DIFFERENCE, text) and any(
        re.search(pattern, text) for pattern in (_POWER, _WEIGHT, _DISPLACEMENT, _SEAT)))


def _number(value):
    parsed = Decimal(str(value)) if value is not None else None
    return parsed if parsed is not None and parsed.is_finite() else None


def _format(value):
    return format(value, 'f').rstrip('0').rstrip('.').replace('.', ',') if value != value.to_integral() else str(int(value))


def _escape(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _name(record):
    return _escape(f"{record['brand']} {record['model']} ({record['year']})")


def _proof(proof, field):
    return ' ; '.join(_escape(row['section'] + ' — ' + row['label'] + ' : ' + row['value'])
                      for row in proof.get(field, []))


def _seat_interval(record, values):
    """Keep an explicit adjustable range; never turn its lower bound into a point."""
    point = _number(values.get('seat_height_mm'))
    candidates = [(point, point)] if point is not None else []
    pattern = (r'\bhauteur de selle\s*:?[ ]*(?:reglable\s*)?entre\s*'
               r'([\d\s.,]+)\s*mm\s*(?:et|a|[-–])\s*([\d\s.,]+)\s*mm\b')
    for row in record['record'].get('spec_rows', []):
        text = folded(row['label'] + ' ' + row['value'])
        for match in re.finditer(pattern, text):
            lo, hi = (_number(number(value)) for value in match.groups())
            if lo is None or hi is None or lo > hi:
                return None
            candidates.append((lo, hi))
    unique = set(candidates)
    return unique.pop() if len(unique) == 1 else None


def _interval_text(interval):
    lo, hi = interval
    return _format(lo) + ' mm' if lo == hi else _format(lo) + '–' + _format(hi) + ' mm'


def comparison_calculations(question, records):
    """Return requested arithmetic only; missing or mixed measurements stay unknown."""
    if not is_arithmetic_question(question):
        return ''
    if len(records) != 2:
        return 'Ces calculs nécessitent exactement deux fiches de modèles et millésimes explicitement identifiés.'
    text = folded(question)
    if re.search(_UNSUPPORTED_UNITS, text):
        return 'Le calcul demandé nécessite une unité ou une conversion non prise en charge. Aucune conversion implicite n’a été effectuée.'

    values, proofs = zip(*(project(record['record']) for record in records))
    names = [_name(record) for record in records]
    weight_field = _weight_field(text)
    ratio_requested = _ratio_requested(text)
    difference_requested = bool(re.search(_DIFFERENCE, text))
    rank_power = bool(re.search(_RANK_QUESTION, text) and re.search(_RANK_POWER, text))
    rank_weight = bool(re.search(_RANK_QUESTION, text) and re.search(_RANK_WEIGHT, text))
    rank_seat = bool(re.search(_RANK_QUESTION, text) and re.search(_RANK_SEAT, text))
    output = ['| Calcul demandé | Résultat |', '|---|---|']

    labels = {
        'power_ch': ('Puissance', 'ch'),
        'displacement_ccm': ('Cylindrée', 'cc'),
        'seat_height_mm': ('Hauteur de selle', 'mm'),
        'weight_dry_kg': ('Poids à sec', 'kg'),
        'weight_wet_kg': ('Poids tous pleins / en ordre de marche', 'kg'),
    }

    def pair(field):
        numbers = [_number(item.get(field)) for item in values]
        missing = [names[index] for index, value in enumerate(numbers) if value is None]
        if missing:
            return None, 'Valeur numérique univoque non documentée : ' + ' ; '.join(missing) + '. Aucune valeur substituée.'
        return numbers, None

    fields = []
    # A ratio's component words do not independently request component gaps.
    gap_text = re.sub(_RATIO_EXPRESSION, ' ', text) if ratio_requested else text
    if difference_requested:
        for pattern, field in ((_POWER, 'power_ch'), (_DISPLACEMENT, 'displacement_ccm'), (_SEAT, 'seat_height_mm')):
            if re.search(pattern, gap_text):
                fields.append(field)
        if re.search(_WEIGHT, gap_text) and weight_field:
            fields.append(weight_field)
    for field in fields:
        label, unit = labels[field]
        numbers, error = pair(field)
        result = error or f"|{_format(numbers[0])} − {_format(numbers[1])}| = {_format(abs(numbers[0] - numbers[1]))} {unit}. Ordre : {names[0]} ; {names[1]}."
        output.append('| Écart — ' + label + ' | ' + _escape(result) + ' |')

    if (difference_requested and re.search(_WEIGHT, text) or rank_weight or ratio_requested) and weight_field is None:
        output.append('| Poids | Précise un seul type commun : poids à sec ou tous pleins / en ordre de marche. Aucun mélange de types n’est calculé. |')

    for field, requested in (('power_ch', rank_power), (weight_field, rank_weight and weight_field is not None)):
        if not requested:
            continue
        label, unit = labels[field]
        numbers, error = pair(field)
        if error:
            result = error
        elif numbers[0] == numbers[1]:
            result = f"Égalité des valeurs de catalogue : {_format(numbers[0])} {unit}."
        else:
            ascending = bool(re.search(r'\bmoins\s+puissant', text)) if field == 'power_ch' else bool(
                re.search(r'\bplus\s+leger|\bmoins\s+lourd', text))
            index = 0 if (numbers[0] < numbers[1]) == ascending else 1
            result = f"{names[index]} : {_format(numbers[index])} {unit}, contre {_format(numbers[1-index])} {unit}. Valeurs de catalogue du même type."
        output.append('| Comparaison — ' + label + ' | ' + result + ' |')

    if rank_seat:
        intervals = [_seat_interval(record, item) for record, item in zip(records, values)]
        missing = [names[index] for index, interval in enumerate(intervals) if interval is None]
        if missing:
            result = 'Hauteur de selle en mm univoque non documentée : ' + ' ; '.join(missing) + '. Aucune valeur ni conversion substituée.'
        else:
            documented = ' ; '.join(name + ' : ' + _interval_text(interval) for name, interval in zip(names, intervals))
            if intervals[0][0] == intervals[0][1] == intervals[1][0] == intervals[1][1]:
                result = 'Égalité des hauteurs de selle documentées : ' + documented + '.'
            elif intervals[0][1] < intervals[1][0] or intervals[1][1] < intervals[0][0]:
                lower = 0 if intervals[0][1] < intervals[1][0] else 1
                want_lower = bool(re.search(r'\bplus\s+bas|\bmoins\s+haut', text))
                winner = lower if want_lower else 1 - lower
                requested = 'plus basse' if want_lower else 'plus haute'
                result = f"{names[winner]} a la selle {requested} sur toute la plage documentée. {documented}. Les intervalles ne se recouvrent pas."
            else:
                result = (documented + '. Les hauteurs documentées se recouvrent ; le classement dépend du réglage de la selle. '
                          'Aucun vainqueur unique ne peut être établi.')
        output.append('| Comparaison — Hauteur de selle | ' + result + ' |')

    if ratio_requested and weight_field:
        ratios = []
        for index, name in enumerate(names):
            power = _number(values[index].get('power_ch'))
            weight = _number(values[index].get(weight_field))
            if power is None or weight is None:
                missing = [label for label, number in (('puissance en ch', power), (labels[weight_field][0].lower(), weight)) if number is None]
                result = 'Non calculable : valeur numérique univoque non documentée pour ' + ', '.join(missing) + '.'
                ratios.append(None)
            elif weight <= 0:
                result = 'Non calculable : le poids documenté doit être strictement positif.'
                ratios.append(None)
            else:
                ratio = power / weight
                ratios.append((ratio, power, weight))
                rounded = ratio.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
                approximate = '≈' if rounded != ratio else '='
                result = (f"{_format(power)} ch / {_format(weight)} kg {approximate} {_format(rounded)} ch/kg. "
                          f"Calcul dérivé des valeurs de catalogue, rapport mesuré non établi. "
                          f"Puissance source : {_proof(proofs[index], 'power_ch')}. "
                          f"Poids source : {_proof(proofs[index], weight_field)}.")
            output.append('| Rapport puissance/' + labels[weight_field][0].lower() + ' — ' + name + ' | ' + result + ' |')
        if difference_requested and not fields:
            if any(ratio is None for ratio in ratios):
                result = 'Non calculable : au moins un rapport ne peut pas être établi avec les valeurs sources.'
            else:
                gap = abs(ratios[0][0] - ratios[1][0])
                rounded = gap.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)
                operator = '≈' if gap != rounded else '='
                formula = ' − '.join(f"({_format(power)} ch / {_format(weight)} kg)" for _, power, weight in ratios)
                result = _escape(f"|{formula}| {operator} {_format(rounded)} ch/kg. Calcul dérivé des valeurs de catalogue.")
            output.append('| Écart des rapports puissance/' + labels[weight_field][0].lower() + ' | ' + result + ' |')

    sources = [f"[{name}]({record['source_url']})" if record.get('source_url') else name + ' : URL source non fournie'
               for name, record in zip(names, records)]
    output.append('| Sources des valeurs de catalogue | ' + ' ; '.join(sources) + ' |')
    return '\n'.join(output)

"""Explicit unit conversions from intact, unambiguous source rows.

This renders a derived answer only: it never changes catalogue projections or
fills missing values. Decimal factors are exact definitions, not rounded factors
from a lookup table. One US liquid gallon is 231 cubic inches; one pound-force
uses the conventional standard gravity. References are linked in the answer.
"""
from decimal import Decimal, ROUND_HALF_UP
import re

from bikefinder_rag.catalog.enriched import folded


NIST_FACTORS = (
    'https://www.nist.gov/pml/special-publication-811/'
    'nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b9'
)
NIST_EXACT_DEFINITIONS = 'https://www.nist.gov/pml/special-publication-811/nist-guide-si-footnotes'
NIST_US_GALLON = 'https://www.nist.gov/document/appc-19-hb44-finalpdf'

INCH_IN_MM = Decimal('25.4')
POUND_IN_KG = Decimal('0.45359237')
STANDARD_GRAVITY = Decimal('9.80665')
# A metric horsepower is 75 kilogram-force metres per second, unlike hp.
CH_IN_KW = Decimal('75') * STANDARD_GRAVITY / Decimal('1000')
CUBIC_INCH_IN_CC = (INCH_IN_MM / Decimal('10')) ** 3
US_GALLON_IN_LITRES = Decimal('231') * CUBIC_INCH_IN_CC / Decimal('1000')
LBFT_IN_NM = POUND_IN_KG * STANDARD_GRAVITY * Decimal('0.3048')

_NUMBER = r'\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?'
_NM = r'n\s*[·.*]?\s*m'
_KGFM = r'(?:mkg|kgm|kgf\s*[·.*]?\s*m)'
_LBFT = r'(?:lbf?|lbs?|livres?)\s*[·.*-]?\s*(?:ft|feet|pieds?)'
_GALLONS = r'\bgallons?\b'
_US_GALLONS = (
    r'\bgallons?\s*\(?\s*(?:americains?|us\b|u\.s\.|des etats[- ]unis)'
    r'|\b(?:us|americains?)\s+gallons?\b'
)
_CUBIC_INCHES = r'\b(?:pouces?\s+cubes?|cubic\s+inches?|inches?\s+cubed|in\s*(?:\^\s*)?3)\b'
_CM3 = r'\bcm\s*(?:\^\s*)?3\b'
_SIMPLE_INCHES = r'\b(?:pouces?|inches?)\b'
_WEIGHT_LB = r'\b(?:livres?|lbs?)\b'
_MISSING = {'', '-', 'nc', 'n.c.', 'n.c', 'non defini', 'non communique', 'inconnu', 'n/a'}


def _number(text):
    return Decimal(re.sub(r'\s', '', text).replace(',', '.'))


def _format(value, places=None):
    if places is not None:
        value = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        return format(value, f'.{places}f').replace('.', ',')
    result = format(value, 'f')
    if '.' in result:
        result = result.rstrip('0').rstrip('.')
    return result.replace('.', ',')


def _safe(text):
    return str(text).replace('|', '\\|').replace('\n', ' ')


def _source(rows):
    originals = dict.fromkeys(
        ' — '.join(part for part in (row.get('section', ''), row.get('label', ''), row.get('value', '')) if part)
        for row in rows
    )
    return ' ; '.join('« ' + _safe(text) + ' »' for text in originals)


def _requested(text, pattern):
    """A mentioned target preceded by ``pas en`` is not a conversion request."""
    for match in re.finditer(pattern, text):
        prefix = text[max(0, match.start() - 40):match.start()]
        if not re.search(r'\b(?:pas|non|ni|sans)\s+(?:(?:en|de|les?|des?|conversion|gallons?)\s+)*$', prefix):
            return True
    return False


def _resolve(rows, parser):
    if not rows or all(folded(row.get('value', '')).strip() in _MISSING for row in rows):
        return None, 'valeur source univoque non documentée ; aucune conversion.'
    parsed = [parser(row) for row in rows]
    if any(value is None for value in parsed):
        return None, 'source qualifiée, non univoque ou unité non prise en charge ; aucune conversion globale.'
    if len(set(parsed)) != 1:
        return None, 'valeurs ou régimes sources contradictoires ; aucune conversion globale.'
    return parsed[0], None


def _simple_parser(labels, units):
    def parse(row):
        if folded(row.get('label', '')).strip() not in labels:
            return None
        match = re.fullmatch(rf'\s*({_NUMBER})\s*(?:{units})\s*', folded(row.get('value', '')))
        value = _number(match[1]) if match else None
        return (value,) if value is not None and value > 0 else None
    return parse


def _seat(row):
    label = folded(row.get('label', '')).strip()
    value = folded(row.get('value', '')).strip()
    if label not in {'', 'hauteur de selle', 'hauteur de selle reglable'}:
        return None
    if not label:
        prefix = re.match(r'^hauteur de selle\s*:?[ ]*', value)
        if not prefix:
            return None
        value = value[prefix.end():]
    point = re.fullmatch(rf'({_NUMBER})\s*mm', value)
    if point:
        height = _number(point[1])
        return (height, height) if height > 0 else None
    interval = re.fullmatch(
        rf'(?:reglable\s*)?(?:entre\s*)?({_NUMBER})\s*(?:mm\s*)?'
        rf'(?:et|a|[-–])\s*({_NUMBER})\s*mm', value,
    )
    if not interval:
        return None
    lo, hi = (_number(value) for value in interval.groups())
    return (lo, hi) if 0 < lo <= hi else None


def _torque(row):
    if folded(row.get('label', '')).strip() not in {'', 'couple'}:
        return None
    match = re.fullmatch(
        rf'\s*({_NUMBER})\s*({_NM}|{_KGFM})'
        rf'(?:\s*\(\s*({_NUMBER})\s*({_NM})\s*\))?'
        rf'(?:\s+a\s+({_NUMBER})\s*tr/min)?\s*', folded(row.get('value', '')),
    )
    if not match:
        return None
    value = _number(match[1])
    unit = 'N·m' if re.fullmatch(_NM, match[2]) else 'mkg'
    if match[3]:
        nm_source = _number(match[3])
        if unit != 'mkg' or nm_source <= 0:
            return None
        # Preserve an explicitly published Nm value. A parenthesized numerical
        # restatement is not a variant, but incompatible numbers remain blocked.
        # Each last written digit contributes at most half a unit of rounding.
        kgfm_error = Decimal(1).scaleb(value.as_tuple().exponent) / 2
        nm_error = Decimal(1).scaleb(nm_source.as_tuple().exponent) / 2
        if abs(value * STANDARD_GRAVITY - nm_source) > kgfm_error * STANDARD_GRAVITY + nm_error:
            return None
        value, unit = nm_source, 'N·m'
    rpm = _number(match[5]) if match[5] else None
    return (value, unit, rpm) if value > 0 and (rpm is None or rpm > 0) else None


def _displacement(row):
    if folded(row.get('label', '')).strip() not in {'', 'cylindree'}:
        return None
    # A bore/stroke description qualifies geometry, not a different variant.
    bore = rf'\(alesage\s*(?:\*|x|×)?\s*course\s*:\s*{_NUMBER}\s*[x×*]\s*{_NUMBER}\s*mm\)'
    match = re.fullmatch(rf'\s*({_NUMBER})\s*(?:cc|cm\s*3)(?:\s*{bore})?\s*',
                         folded(row.get('value', '')))
    value = _number(match[1]) if match else None
    return (value,) if value is not None and value > 0 else None


def _power(row):
    if folded(row.get('label', '')).strip() not in {'', 'puissance'}:
        return None
    match = re.fullmatch(
        rf'\s*({_NUMBER})\s*(?:ch|cv)(?:\s+a\s+({_NUMBER})\s*tr/min)?\s*',
        folded(row.get('value', '')),
    )
    if not match:
        return None
    value = _number(match[1])
    rpm = _number(match[2]) if match[2] else None
    # ch and CV are the same metric unit. Imperial hp and other labels are not.
    return (value, rpm) if value > 0 and (rpm is None or rpm > 0) else None


def requested_conversions(record, question):
    """Render conversions explicitly requested in ``question`` for one fiche.

    Input is the raw record containing ``spec_rows``, not a numeric projection.
    Return ``''`` when no supported target unit is requested. Missing, conflicting,
    variant-qualified and untyped weights receive an explicit limitation instead
    of an inferred numeric answer. Callers keep model/year scope outside here.
    """
    text = re.sub(r'\bkilowatts?\b', 'kw', folded(question))
    rows = record.get('spec_rows', [])
    output, converted = [], False
    references = []

    def add(label, candidates, parser, render):
        nonlocal converted
        value, error = _resolve(candidates, parser)
        if error:
            output.append(f'**{label}** : {error}' + (f' Source conservée : {_source(candidates)}.' if candidates else ''))
        else:
            converted = True
            output.append(f'**{label}** : {render(value)} Source conservée : {_source(candidates)}.')

    if _requested(text, _GALLONS):
        if not _requested(text, _US_GALLONS) or _requested(text, r'\b(?:imperial|imperiaux|britanniques?|uk)\b'):
            output.append('**Réservoir** : précise les gallons américains (US) ; aucune conversion en gallons non qualifiés ou impériaux.')
        else:
            candidates = [row for row in rows if folded(row.get('label', '')).startswith('reservoir')]
            add('Réservoir', candidates, _simple_parser({'reservoir'}, r'litres?|l'),
                lambda value: f'{_format(value[0])} L / {_format(US_GALLON_IN_LITRES)} ≈ '
                f'{_format(value[0] / US_GALLON_IN_LITRES, 2)} gallons américains (US).')
            references.append(f'[gallon US = 231 pouces cubes, NIST]({NIST_US_GALLON})')

    cubic_inches = _requested(text, _CUBIC_INCHES)
    linear_text = re.sub(_CUBIC_INCHES, ' ', text)
    if _requested(linear_text, _SIMPLE_INCHES):
        named_seat = bool(re.search(r'\bselle\b', text))
        named_wheelbase = bool(re.search(r'\bempattement\b', text))
        only_target = not (named_seat or named_wheelbase or re.search(r'\b(?:cylindree|reservoir|roues?|pneus?|longueur|largeur|hauteur)\b', text))
        if named_seat or only_target:
            candidates = [row for row in rows if 'hauteur de selle' in folded(row.get('label', '') + ' ' + row.get('value', ''))]

            def seat_result(value):
                lo, hi = value
                if lo == hi:
                    return f'{_format(lo)} mm / 25,4 ≈ {_format(lo / INCH_IN_MM, 2)} pouces.'
                return (f'{_format(lo)}–{_format(hi)} mm / 25,4 ≈ '
                        f'{_format(lo / INCH_IN_MM, 2)}–{_format(hi / INCH_IN_MM, 2)} pouces ; '
                        'plage réglable conservée, aucun point unique déduit.')
            add('Hauteur de selle', candidates, _seat, seat_result)
        if named_wheelbase or only_target:
            candidates = [row for row in rows if folded(row.get('label', '')).startswith('empattement')]
            add('Empattement', candidates, _simple_parser({'empattement'}, 'mm'),
                lambda value: f'{_format(value[0])} mm / 25,4 ≈ {_format(value[0] / INCH_IN_MM, 2)} pouces.')

    wants_nm = _requested(text, rf'(?<!\w){_NM}(?!\w)|\bnewtons?[- ]metres?\b')
    wants_lbft = _requested(text, rf'\b{_LBFT}\b')
    if wants_nm or wants_lbft:
        candidates = [row for row in rows if folded(row.get('section', '')) == 'moteur' and (
            folded(row.get('label', '')).startswith('couple') or re.match(
                rf'^\s*{_NUMBER}\s*(?:{_NM}|{_KGFM})\b', folded(row.get('value', ''))))]

        def torque_result(value):
            source, unit, rpm = value
            nm = source * STANDARD_GRAVITY if unit == 'mkg' else source
            statements = []
            formula = f'{_format(source)} mkg × 9,80665' if unit == 'mkg' else f'{_format(source)} N·m'
            if wants_nm:
                statements.append(formula + f' ≈ {_format(nm, 1)} N·m' if unit == 'mkg' else formula + ' (unité source normalisée)')
            if wants_lbft:
                statements.append(f'({formula}) / {_format(LBFT_IN_NM)} ≈ {_format(nm / LBFT_IN_NM, 1)} lb·ft')
            qualifier = ' Convention mkg = kgf·m.' if unit == 'mkg' else ''
            regime = f' Régime source conservé : {_format(rpm)} tr/min.' if rpm is not None else ' Régime source non documenté.'
            return ' ; '.join(statements) + '.' + qualifier + regime
        add('Couple', candidates, _torque, torque_result)

    explicit_power_conversion = (
        _requested(text, r'\b(?:convertir|convertis|convertissez|conversions?)\b')
        and _requested(text, r'\b(?:kw|kilowatts?)\b')
        and not re.search(r'\bconvert(?:is|issez)\s+pas\b', text)
        and not re.search(
            rf'(?:(?:moins|plus)\s+de|au\s+(?:moins|plus)|sous|[<>]=?)\s*{_NUMBER}\s*kw\b'
            rf'|\b{_NUMBER}\s*kw\s*(?:max(?:imum)?|min(?:imum)?|mini)\b'
            rf'|\bentre\s*{_NUMBER}\s*(?:kw\s*)?et\s*{_NUMBER}\s*kw\b', text,
        )
    )
    if explicit_power_conversion:
        candidates = [row for row in rows if folded(row.get('section', '')) == 'moteur' and (
            folded(row.get('label', '')).startswith('puissance') or re.match(
                rf'^\s*{_NUMBER}\s*(?:ch|cv|hp|ps|kw)\b', folded(row.get('value', ''))))]

        def power_result(value):
            power, rpm = value
            regime = f' Régime source conservé : {_format(rpm)} tr/min.' if rpm is not None else ' Régime source non documenté.'
            return (f'{_format(power)} ch × {_format(CH_IN_KW)} ≈ {_format(power * CH_IN_KW, 2)} kW. '
                    'Convention ch/CV métriques : 1 ch = 1 CV = 75 kgf·m/s = 0,73549875 kW exactement.' + regime)
        add('Puissance', candidates, _power, power_result)

    weight_text = re.sub(_LBFT, ' ', text)
    if _requested(weight_text, _WEIGHT_LB):
        dry_requested = bool(re.search(r'\b(?:a sec|sec)\b', text))
        wet_requested = bool(re.search(r'\b(?:pleins?|en ordre de marche)\b', text))
        definitions = (
            ('Poids à sec', r'^poids a sec\b', {'poids a sec'}, dry_requested or not wet_requested),
            ('Poids tous pleins / en ordre de marche', r'^poids (?:tous pleins(?: faits)?|en ordre de marche)\b',
             {'poids tous pleins', 'poids tous pleins faits', 'poids en ordre de marche'}, wet_requested or not dry_requested),
        )
        all_weights = [row for row in rows if folded(row.get('label', '')).startswith('poids')]
        typed_weights = [row for row in all_weights if any(re.search(pattern, folded(row.get('label', ''))) for _, pattern, _, _ in definitions)]
        if all_weights and not typed_weights:
            output.append('**Poids** : type sec / plein non documenté ; aucune conversion globale. '
                          f'Source conservée : {_source(all_weights)}.')
        else:
            for label, pattern, labels, requested in definitions:
                if not requested:
                    continue
                candidates = [row for row in rows if re.search(pattern, folded(row.get('label', '')))]
                add(label, candidates, _simple_parser(labels, 'kg'),
                    lambda value: f'{_format(value[0])} kg / {_format(POUND_IN_KG)} ≈ '
                    f'{_format(value[0] / POUND_IN_KG, 1)} livres (lb) ; 1 livre avoirdupois = 0,45359237 kg exactement.')

    wants_cm3 = _requested(text, _CM3)
    if wants_cm3 or cubic_inches:
        candidates = [row for row in rows if folded(row.get('section', '')) == 'moteur' and (
            folded(row.get('label', '')).startswith('cylindree') or
            re.match(rf'^\s*{_NUMBER}\s*(?:cc|cm\s*3)\b', folded(row.get('value', ''))))]

        def displacement_result(value):
            cc = value[0]
            statements = []
            if wants_cm3:
                statements.append(f'{_format(cc)} cc = {_format(cc)} cm³ (1 cc = 1 cm³)')
            if cubic_inches:
                statements.append(f'{_format(cc)} cc / {_format(CUBIC_INCH_IN_CC)} ≈ '
                                  f'{_format(cc / CUBIC_INCH_IN_CC, 2)} pouces cubes')
            return ' ; '.join(statements) + '.'
        add('Cylindrée', candidates, _displacement, displacement_result)

    if converted:
        references[:0] = [f'[facteurs NIST]({NIST_FACTORS})',
                          f'[définitions exactes NIST]({NIST_EXACT_DEFINITIONS})']
        output.append('Conversions calculées depuis les valeurs sources, arrondis au plus proche '
                      '(2 décimales pour pouces, pouces cubes, gallons et kW ; 1 décimale pour couple et livres). '
                      'Ces calculs ne constituent pas de nouvelles mesures. ' + ' ; '.join(references) + '.')
    return '\n\n'.join(output)

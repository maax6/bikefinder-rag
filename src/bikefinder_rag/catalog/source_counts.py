"""Closed, read-only compound counts from the original technical source rows.

This deliberately small grammar consumes every meaningful clause before a
query runs. It cannot turn a partially understood request into a wider count.
No category, market, licence, equipment inference or generated SQL is used.
"""
from dataclasses import dataclass
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile

from bikefinder_rag.catalog.enriched import _rows, folded
from bikefinder_rag.catalog.measures import number


DISPLAY_LIMIT = 20
EXPORT_DIRECTORY = Path(__file__).resolve().parents[3] / 'data' / 'technical' / 'chat-exports'
EXPORT_URL_PREFIX = '/gradio_api/file=data/technical/chat-exports/'
BRANDS = ('BMW', 'Yamaha', 'Honda', 'Kawasaki', 'Suzuki', 'Ducati', 'Triumph', 'KTM')
NUMBER = r'(?:\d{1,3}(?:\s\d{3})+|\d+)(?:[.,]\d+)?'
UNITS = {
    'displacement_ccm': r'(?:cm\s*3|cc|cm\^3|centimetres?\s+cubes?)',
    'seat_height_mm': r'(?:mm|millimetres?)',
    'wheelbase_mm': r'(?:mm|millimetres?)',
    'tank_l': r'(?:l|litres?)',
}
LABELS = {
    'displacement_ccm': r'(?:cylindree(?:s)?|moteur(?:s)?)',
    'seat_height_mm': r'(?:(?:hauteur\s+(?:de\s+(?:la\s+)?)?)?selles?)',
    'wheelbase_mm': r'(?:empattements?)',
    'tank_l': r'(?:reservoirs?|capacite\s+(?:du|de\s+reservoir))',
}
OPERATOR = (
    r'(?:<=|>=|<|>|=|au\s+plus|au\s+moins|maximum(?:\s+de)?|minimum(?:\s+de)?|'
    r'max(?:i)?(?:\s+de)?|min(?:i)?(?:\s+de)?|pas\s+plus\s+(?:de|haute?\s+que)|'
    r'ne\s+depass(?:e|ant)\s+pas|moins\s+de|plus\s+de|sous|'
    r'inferieur(?:e)?\s+a|superieur(?:e)?\s+a|egal(?:e)?\s+a|exactement)'
)
FIELD_NAMES = {
    'displacement_ccm': 'Cylindrée', 'seat_height_mm': 'Selle',
    'wheelbase_mm': 'Empattement', 'tank_l': 'Réservoir',
    'gears': 'Boîte', 'front_discs': 'Frein avant',
    'secondary': 'Transmission secondaire', 'abs_standard': 'ABS',
}


def _normalize(question):
    text = (folded(question).replace('’', "'").replace('≤', '<=')
            .replace('≥', '>=').replace('–', '-').replace('—', '-'))
    numerals = {'deux': '2', 'trois': '3', 'quatre': '4', 'cinq': '5',
                'six': '6', 'sept': '7', 'huit': '8', 'neuf': '9',
                'dix': '10', 'quinze': '15', 'vingt': '20'}
    return re.sub(r'\b(?:' + '|'.join(numerals) + r')\b', lambda m: numerals[m[0]], text)


def _operator(value):
    value = value.strip()
    if value in ('<=', '>=', '<', '>', '='):
        return value
    if value.startswith(('au plus', 'maximum', 'max', 'pas plus', 'ne depass')):
        return '<='
    if value.startswith(('au moins', 'minimum', 'min')):
        return '>='
    if value.startswith(('moins', 'sous', 'inferieur')):
        return '<'
    if value.startswith(('plus', 'superieur')):
        return '>'
    return '='


def _mark(work, pattern, callback=None):
    """Consume recognized spans without shifting positions."""
    def replace(match):
        if callback:
            callback(match)
        return ' ' * len(match[0])
    return re.sub(pattern, replace, work)


def parse_source_count(question):
    """Return a complete closed plan, a blocked plan, or None out of scope."""
    if not isinstance(question, str) or not question.strip():
        return None
    text = _normalize(question)
    # Do not intercept a factual model query or a conversational follow-up.
    request = re.search(r'\b(?:combien|compte|comptes|comptage|compter|nombre|liste|lister|recense|affiche|montre)\b', text)
    if not request:
        return None
    work = text
    years = []
    work = _mark(work, r'\b((?:18|19|20)\d{2})\s*(?:-|a|et)\s*((?:18|19|20)\d{2})\b',
                 lambda m: years.append((int(m[1]), int(m[2]))))
    if len(years) != 1:
        return None
    conditions = []
    fields = []

    def add(field, operator, value):
        conditions.append({'field': field, 'op': operator, 'value': number(value)})
        if field not in fields:
            fields.append(field)

    # Excluding "1000 cc ou plus" has a precise complement: strictly below
    # 1000 cc, not <= 1000. This grammar does not infer a complementary class.
    exclude_verb = r'(?:exclu(?:e|ez|re|ant|s|es)?|ecart(?:e|ez|er|ant))'
    excluded_numeric_ends = []

    def take_exclusion(field, match):
        add(field, '<' if 'plus' in match[2] else '>', match[1])
        excluded_numeric_ends.append(match.end())

    for field, label in LABELS.items():
        unit = UNITS[field]
        work = _mark(work, rf'\b{exclude_verb}\s+(?:(?:les|la|le)\s+)?{label}\s+(?:de\s+)?({NUMBER})\s*{unit}\s+(ou\s+plus|et\s+plus|ou\s+moins|et\s+moins)\b',
                     lambda m, f=field: take_exclusion(f, m))

    for field, label in LABELS.items():
        unit = UNITS[field]
        # "cylindrée entre 500 et 800 cc" and "500–800 cm³".
        range_pattern = (rf'\b(?:{label}\s*(?:de|comprise?\s+)?\s*)?(?:entre\s+)?'
                         rf'({NUMBER})\s*(?:{unit}\s*)?(?:-|a|et)\s*({NUMBER})\s*{unit}\b')
        # Ambiguous mm ranges require the field noun, unlike cc ranges.
        if field != 'displacement_ccm':
            range_pattern = (rf'\b{label}\s*(?:de|comprise?\s+)?\s*(?:entre\s+)?'
                             rf'({NUMBER})\s*(?:{unit}\s*)?(?:-|a|et)\s*({NUMBER})\s*{unit}\b')
        work = _mark(work, range_pattern,
                     lambda m, f=field: (add(f, '>=', m[1]), add(f, '<=', m[2])))
        bound_pattern = (rf'\b{label}\s*(?:de|d\x27|a|est|doit\s+etre)?\s*'
                         rf'({OPERATOR})\s*({NUMBER})\s*(?:{unit})?\b')
        work = _mark(work, bound_pattern, lambda m, f=field: add(f, _operator(m[1]), m[2]))
        work = _mark(work, rf'\b{label}\s*(?:de|a)?\s*({NUMBER})\s*{unit}\s+(?:au\s+)?(maximum|max(?:i)?|minimum|min(?:i)?)\b',
                     lambda m, f=field: add(f, '<=' if m[2].startswith('max') else '>=', m[1]))
        # The unit identifies displacement; mm/l without a noun is ambiguous.
        if field == 'displacement_ccm':
            work = _mark(work, rf'({OPERATOR})\s*({NUMBER})\s*{unit}\b',
                         lambda m: add('displacement_ccm', _operator(m[1]), m[2]))

    work = _mark(work, r'\b(?:boite(?:\s+(?:de\s+vitesses|de\s+vitesse))?\s+(?:a|de)?\s*)?(\d+)\s+(?:rapports?|vitesses?)\b',
                 lambda m: add('gears', '=', m[1]))
    work = _mark(work, r'\b(?:(?:transmission\s+)?(?:secondaire|finale)\s+(?:par|a)?\s*(?:la\s+)?chaine|transmission\s+(?:par|a)\s+(?:la\s+)?chaine)\b',
                 lambda m: add('secondary', '=', '1'))
    work = _mark(work, r'\b(\d+)\s+disques?\s+(?:(?:de\s+)?freins?\s+)?(?:a\s+l[\x27 ]?)?avant\b',
                 lambda m: add('front_discs', '=', m[1]))
    work = _mark(work, r'\b(?:frein(?:age)?\s+avant\s+(?:a|avec)?\s*)(\d+)\s+disques?\b',
                 lambda m: add('front_discs', '=', m[1]))
    work = _mark(work, r'\babs\s+(?:explicitement\s+)?(?:de\s+serie|en\s+serie|standard|d[\x27 ]origine)\b',
                 lambda m: add('abs_standard', '=', '1'))
    work = _mark(work, r'\babs\s+(?:explicitement\s+)?(?:en\s+)?(?:equipement\s+)?de\s+serie\b',
                 lambda m: add('abs_standard', '=', '1'))

    # Standalone variant letters only; XR, RS, Super Duke and R1 survive.
    excluded_variants = []
    variant_prefix = (r'(?:sans\s+(?:les?\s+)?(?:versions?|variantes?)|'
                      + exclude_verb + r'\s+(?:les?\s+)?(?:versions?|variantes?)(?:\s+dont\s+(?:le\s+)?nom\s+contient)?|'
                      r'(?:dont\s+)?(?:le\s+)?(?:nom|modele)\s+ne\s+comporte\s+(?:pas|ni))')
    work = _mark(work, rf'\b{variant_prefix}\s+([sr])\s*(?:,|/|ou|et|ni)\s*([sr])\b',
                 lambda m: excluded_variants.extend((m[1].upper(), m[2].upper())))
    sort_by = []
    work = _mark(work, r'\b(?:tri(?:e|ees|es)?(?:s)?|trier|classe(?:es|s|ment)?)\s+(?:par\s+)?empattement\s+(?:croissant|ascendant|asc)\b',
                 lambda m: sort_by.append('wheelbase_mm'))
    work = _mark(work, r'\bpar\s+empattement\s+(?:croissant|ascendant|asc)\b',
                 lambda m: sort_by.append('wheelbase_mm'))

    brand_lookup = {folded(brand): brand for brand in BRANDS}
    brand_pattern = '(?:' + '|'.join(re.escape(folded(brand)) for brand in BRANDS) + ')'
    sequence = brand_pattern + rf'(?:\s*(?:,|/|\bet\b|\bou\b|\bni\b)\s*{brand_pattern})*'
    included, excluded = [], []

    invalid_brand_descriptor = []

    def take_brands(target, match):
        target.extend(brand_lookup[name] for name in re.findall(brand_pattern, match[1]))
        if 'japonaises' in match[0] and any(name not in ('Honda', 'Kawasaki', 'Suzuki', 'Yamaha') for name in target):
            invalid_brand_descriptor.append('Qualification de marque contradictoire.')

    exclusion = r'(?:sans|hors|sauf|' + exclude_verb + r'|exclusion\s+de|pas\s+de|ni)\s+(?:(?:les|la|de|marques)\s+)*(?:japonaises\s+)?'
    work = _mark(work, rf'\b{exclusion}({sequence})\b', lambda m: take_brands(excluded, m))

    def coordinated_brand_exclusion(match):
        # "Exclue <seuil> et les marques <liste>" carries the exclusion
        # verb across its explicitly joined objects; a new sentence cannot.
        if any(end <= match.start() and not work[end:match.start()].strip()
               for end in excluded_numeric_ends):
            take_brands(excluded, match)
        else:
            invalid_brand_descriptor.append('Une exclusion de marques doit être explicite.')

    work = _mark(work, rf'\bet\s+les\s+marques\s+(?:japonaises\s+)?({sequence})\b',
                 coordinated_brand_exclusion)
    work = _mark(work, rf'\b({sequence})\b', lambda m: take_brands(included, m))
    # Optional descriptions of the closed exclusion semantics.
    work = _mark(work, r'\b(?:comme\s+(?:mots?\s+(?:separes?|isoles?)|mot\s+separe)|(?:mots?\s+(?:separes?|isoles?)))\b')
    work = _mark(work, r'\b(?:du\s+modele|dans\s+(?:le\s+)?nom|dans\s+(?:le\s+)?modele)\b')
    work = _mark(work, r'\b(?:precise|signale|explique|indique)\s+ce\s+que\s+tu\s+ne\s+peux\s+pas\s+trancher\s+faute\s+de\s+donnees\b')

    # These words add no constraint. Unknown semantic tokens remain visible.
    stop_words = {
        'je', 'j', 'tu', 'me', 'moi', 'mon', 'ton', 'on', 'nous', 'svp', 'stp', 'peux', 'peut', 'pourrais',
        'veux', 'voudrais', 'veut', 'voulant', 'voulais', 'avoir', 'savoir', 'donne', 'donner',
        'dis', 'dire', 'fait', 'fais', 'fiches', 'fiche', 'motos', 'moto', 'modeles', 'modele', 'entrees', 'entree',
        'catalogue', 'base', 'donnees', 'combien', 'nombre', 'compte', 'comptes', 'comptage',
        'compter', 'liste', 'lister', 'listes', 'recense', 'affiche', 'afficher', 'montre',
        'd', 'l', 'des', 'les', 'la', 'le', 'du', 'de', 'a', 'au', 'aux', 'en', 'avec', 'et',
        'ni', 'par', 'entre', 'pour', 'un', 'une', 'ce', 'ces', 'cette', 'sur', 'dans',
        'qui', 'que', 'qu', 'ayant', 'ont', 'est', 'sont', 'soit', 'dont', 'il', 'y', 'ca',
        'annonce', 'annoncent', 'marques', 'marque', 'millésimes', 'millesimes', 'millesime',
        'annees', 'annee', 'periode', 'inclus', 'incluses', 'inclusifs', 'compris', 'comprises',
        'respectivement', 'total', 'totaux', 'toutes', 'tous', 'complet', 'complete', 'exact',
        'exacte', 'exactement', 'correspondent', 'correspondant', 'resultats', 'resultat',
        'puis', 'aussi', 'egalement', 'seulement', 'uniquement', 'explicitement',
        'variantes', 'variante', 'retenus', 'retenues', 'retenu', 'retenue', 'chaque', 'seule', 'fois',
    }
    unresolved = [token for token in re.findall(r'[a-z0-9]+|[<>]=?|=', work)
                  if token not in stop_words]
    # Extended source dimensions are this module's remit; a simple unrelated
    # filter must continue to the general router instead of being intercepted.
    extended = {'tank_l', 'gears', 'front_discs', 'secondary', 'wheelbase_mm'}
    if not extended.intersection(fields) and len(set(fields)) < 2:
        return None
    plan = {
        'operation': 'source_count', 'min_year': years[0][0], 'max_year': years[0][1],
        'include_brands': sorted(set(included)), 'exclude_brands': sorted(set(excluded)),
        'exclude_variant_words': sorted(set(excluded_variants)), 'conditions': conditions,
        'order_by': sort_by[0] if sort_by else None, 'limit': DISPLAY_LIMIT,
        'source_question': question,
    }
    invalid = (plan['min_year'] > plan['max_year']
               or any(c['value'] < 0 for c in conditions)
               or set(included).intersection(excluded) or invalid_brand_descriptor)
    for field in fields:
        subset = [c for c in conditions if c['field'] == field]
        lowers = [(c['value'], c['op'] in ('>=', '=')) for c in subset if c['op'] in ('>', '>=', '=')]
        uppers = [(c['value'], c['op'] in ('<=', '=')) for c in subset if c['op'] in ('<', '<=', '=')]
        if lowers and uppers:
            lower = max(v for v, _ in lowers)
            upper = min(v for v, _ in uppers)
            invalid = invalid or lower > upper or (lower == upper and (
                not all(inclusive for v, inclusive in lowers if v == lower)
                or not all(inclusive for v, inclusive in uppers if v == upper)))
    if unresolved or invalid:
        plan['blocked_reason'] = ('Critères contradictoires ou intervalle invalide.' if invalid else
                                  'Clause non prise en charge : ' + ' '.join(dict.fromkeys(unresolved)) + '.')
    return plan


@dataclass(frozen=True)
class SourceValue:
    values: tuple
    rows: tuple


def project_source(record):
    """Only explicit, unambiguous values; keep every original supporting row."""
    candidates = {}

    def put(field, values, row):
        candidates.setdefault(field, []).append(SourceValue(tuple(values), (row,)))

    for row in record.get('spec_rows', []):
        section, label, value = (folded(str(row.get(key, ''))).strip()
                                 for key in ('section', 'label', 'value'))
        if section == 'moteur' and not label.startswith('rapport'):
            match = re.match(rf'^({NUMBER})\s*(?:cc|cm\s*3)\b', value)
            if match:
                put('displacement_ccm', (number(match[1]),), row)
        if section == 'chassis':
            for field, expected, unit in (
                ('tank_l', 'reservoir', r'(?:litres?|l)'),
                ('wheelbase_mm', 'empattement', 'mm'),
                ('seat_height_mm', 'hauteur de selle', 'mm'),
            ):
                if label == expected:
                    match = re.fullmatch(rf'({NUMBER})\s*{unit}', value)
                    if match:
                        put(field, (number(match[1]),), row)
            if label in ('', 'hauteur de selle'):
                match = re.fullmatch(rf'(?:hauteur de selle\s+)?reglable entre ({NUMBER})\s*mm et ({NUMBER})\s*mm', value)
                if match:
                    limits = tuple(number(match[index]) for index in (1, 2))
                    if limits[0] <= limits[1]:
                        put('seat_height_mm', limits, row)
        if section == 'transmission':
            # Compatible manual/shifter annotations do not change the gear
            # count. An alternative count or unrecognized suffix is rejected.
            suffix = (r'(?:\s*[,;/]?\s*(?:manuelle(?:\s*[-+/;,]\s*shifter(?:\s+(?:de\s+serie|en\s+option))?)?'
                      r'|(?:avec\s+)?shifter(?:\s+(?:de\s+serie|en\s+option))?))?')
            match = re.fullmatch(r'boite\s+(?:a|de)\s+(\d+)\s+(?:rapports?|vitesses?)' + suffix, value)
            if match:
                put('gears', (int(match[1]),), row)
            match = re.fullmatch(r'secondaire\s+par\s+(chaine|cardan|courroie)', value)
            if match:
                put('secondary', (1 if match[1] == 'chaine' else 0,), row)
        if section == 'train avant' and label in ('freinage', 'frein', ''):
            match = re.match(r'^(\d+)\s+disques?\b', value)
            if match:
                put('front_discs', (int(match[1]),), row)
        # No use of absence-of-mention as proof. Conflicting options/absence
        # remain unknown; an unrelated ABS model name cannot be equipment.
        if section.startswith('equipement') and re.search(r'\babs\b', value):
            if (re.search(r'\b(?:sans|absent|non|option|optionnel)\b', value)
                    or 'option' in section):
                put('abs_standard', (0,), row)
            elif 'de serie' in section or re.search(r'\b(?:de serie|en serie|standard)\b', value):
                put('abs_standard', (1,), row)
    output = {}
    for field, observations in candidates.items():
        distinct = {entry.values for entry in observations}
        if len(distinct) == 1:
            output[field] = SourceValue(observations[0].values,
                                       tuple(row for observation in observations for row in observation.rows))
    return output


def _matches(value, criterion):
    if value is None:
        return None
    op, target = criterion['op'], criterion['value']
    test = {
        '<': lambda x: x < target, '<=': lambda x: x <= target,
        '>': lambda x: x > target, '>=': lambda x: x >= target,
        '=': lambda x: x == target,
    }[op]
    flags = [test(entry) for entry in value.values]
    if all(flags):
        return True
    if not any(flags):
        return False
    # A seat adjustment spanning the threshold is not one fixed satisfying
    # value. We expose the limitation instead of selecting its minimum.
    return None


def _escape(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def _csv_cell(value):
    """Keep externally sourced names from becoming spreadsheet formulas."""
    text = str(value)
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


def _export_matches(matches, fields):
    """Write only these matching identities and requested proofs, atomically.

    The content hash names the complete result. It exposes neither the raw
    catalogue nor the surrounding process environment, and identical results
    reuse a single artifact rather than produce one file per request.
    """
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    columns = ['id', 'marque', 'modele', 'annee', 'source_url', 'source_sha256']
    columns += [column for field in fields for column in (field + '_source', field + '_preuves')]
    writer.writerow(columns)
    for row, projected in matches:
        cells = [row['id'], row['brand'], row['model'], row['year'], row['source_url'], row['source_sha256']]
        for field in fields:
            proof = projected[field].rows
            cells.append(' ; '.join(dict.fromkeys(str(item['value']) for item in proof)))
            cells.append(json.dumps(list(proof), ensure_ascii=False, sort_keys=True, separators=(',', ':')))
        writer.writerow([_csv_cell(cell) for cell in cells])
    payload = stream.getvalue().encode('utf-8-sig')
    digest = hashlib.sha256(payload).hexdigest()
    EXPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = EXPORT_DIRECTORY / (digest + '.csv')
    if not destination.exists():
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix='.count-', suffix='.tmp', dir=EXPORT_DIRECTORY, delete=False) as output:
                temporary = Path(output.name)
                output.write(payload)
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {'path': str(destination), 'url': EXPORT_URL_PREFIX + destination.name,
            'sha256': digest, 'rows': len(matches)}


def try_source_count(conn, question):
    """Count unique source IDs within parameterized identity/year bounds."""
    plan = parse_source_count(question)
    if plan is None:
        return None
    if plan.get('blocked_reason'):
        return {'answer': plan['blocked_reason'] +
                ' Aucun compte partiel ni liste élargie : précise ce critère avant de compter.',
                'plan': plan, 'route': 'clarification'}
    clauses = ['f.year >= %s', 'f.year <= %s']
    params = [plan['min_year'], plan['max_year']]
    if plan['include_brands']:
        clauses.append('lower(f.brand) = ANY(%s)')
        params.append([folded(brand) for brand in plan['include_brands']])
    if plan['exclude_brands']:
        clauses.append('NOT (lower(f.brand) = ANY(%s))')
        params.append([folded(brand) for brand in plan['exclude_brands']])
    rows = _rows(conn, 'SELECT f.id,f.brand,f.model,f.year,f.source_url,f.source_sha256,f.record '
                 'FROM technical_fiches f WHERE ' + ' AND '.join(clauses), params)
    matches, unknown = [], 0
    seen = set()
    for row in rows:
        if row['id'] in seen:
            continue
        seen.add(row['id'])
        if any(re.search(r'(?<!\w)' + re.escape(token) + r'(?!\w)', row['model'], re.I)
               for token in plan['exclude_variant_words']):
            continue
        projected = project_source(row['record'])
        verdicts = [_matches(projected.get(c['field']), c) for c in plan['conditions']]
        if False in verdicts:
            continue
        if None in verdicts:
            unknown += 1
            continue
        matches.append((row, projected))
    if plan['order_by']:
        matches.sort(key=lambda item: (item[1][plan['order_by']].values[0],
                                      folded(item[0]['brand']), folded(item[0]['model']), item[0]['id']))
    else:
        matches.sort(key=lambda item: (-item[0]['year'], folded(item[0]['brand']),
                                      folded(item[0]['model']), item[0]['id']))
    total = len(matches)
    shown = matches[:DISPLAY_LIMIT]
    fields = list(dict.fromkeys(c['field'] for c in plan['conditions']))
    export = _export_matches(matches, fields)
    units = {'displacement_ccm': 'cc', 'seat_height_mm': 'mm', 'wheelbase_mm': 'mm',
             'tank_l': 'L', 'gears': 'rapports', 'front_discs': 'disques'}
    signs = {'<=': '≤', '>=': '≥', '<': '<', '>': '>', '=': '='}
    summaries = []
    for criterion in plan['conditions']:
        field = criterion['field']
        if field == 'secondary':
            summary = 'transmission secondaire par chaîne'
        elif field == 'abs_standard':
            summary = 'ABS explicitement de série'
        else:
            value = f"{criterion['value']:g}".replace('.', ',')
            summary = FIELD_NAMES[field] + ' ' + signs[criterion['op']] + ' ' + value + ' ' + units.get(field, '')
        summaries.append(summary.strip())
    header = (f"**{total} fiches** satisfont tous les critères documentés ({plan['min_year']}–{plan['max_year']} inclus). "
              'Chaque marque, modèle, variante et millésime compte séparément ; chaque identifiant une seule fois.\n\n'
              'Critères conservés : ' + ' ; '.join(summaries) + '.')
    if plan['include_brands']:
        header += ' Marques retenues : ' + ', '.join(plan['include_brands']) + '.'
    if plan['exclude_brands']:
        header += ' Marques exclues : ' + ', '.join(plan['exclude_brands']) + '.'
    if plan['exclude_variant_words']:
        header += ' Mots de variante exclus : ' + ', '.join(plan['exclude_variant_words']) + ' (mots séparés uniquement).'
    uncertainty = (' ou une selle réglable chevauche le seuil' if 'seat_height_mm' in fields else '')
    header += (f'\n\n{unknown} autre(s) fiche(s) pourraient satisfaire les critères, mais une preuve manque, '
               'est contradictoire' + uncertainty + '. Elles ne sont pas comptées. '
               'Le résultat est un compte des fiches documentées de ce catalogue, pas une garantie exhaustive du marché.')
    if 'seat_height_mm' in fields:
        header += ' Pour une selle réglable, toute la plage doit satisfaire le seuil ; aucune option de selle basse n’est supposée.'
    header += f"\n\n[Liste complète sourcée — {total} fiches, CSV]({export['url']}) : toutes les correspondances, dans le même ordre que l’aperçu, avec leurs valeurs d’origine et leurs sources."
    if total:
        header += f'\n\nAffichage : {len(shown)} sur {total} fiches (limite {DISPLAY_LIMIT}).'
        if plan['order_by']:
            header += ' Tri par empattement croissant.'
        columns = ['Moto / millésime'] + [FIELD_NAMES[field] + ' — source' for field in fields] + ['Source']
        table = ['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join(['---'] * len(columns)) + ' |']
        for row, projected in shown:
            cells = [_escape(f"{row['brand']} {row['model']} {row['year']}")]
            for field in fields:
                cells.append(' ; '.join(dict.fromkeys(_escape(proof['value']) for proof in projected[field].rows)))
            cells.append(f"[Fiche]({row['source_url']})")
            table.append('| ' + ' | '.join(cells) + ' |')
        header += '\n\n' + '\n'.join(table)
    plan['total'] = total
    plan['unresolved_source_fiches'] = unknown
    plan['export'] = export
    plan['shown_sources'] = [{'id': row['id'], 'source_sha256': row['source_sha256'],
                             'source_url': row['source_url']} for row, _ in shown]
    return {'answer': header, 'plan': plan, 'route': 'count'}

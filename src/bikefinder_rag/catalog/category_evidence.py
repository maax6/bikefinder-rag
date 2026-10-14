"""Conservative category filters backed by existing, identified source rows.

Bikez categories are a different taxonomy, with partial Motoplanete coverage.
They are never replaced by the model-generated ``category_fr`` column. A raw
source label can support a qualified list, not a universal motorcycle class.
"""
import json
import re
from collections import defaultdict
from urllib.parse import urlsplit

from bikefinder_rag.catalog.enriched import _rows, folded


CATEGORY_LABELS = {
    "roadster": ("Naked bike",),
    "trail": ("Enduro/offroad",),
    "routiere": ("Touring", "Sport touring"),
    "sportive": ("Sport",),
    "electrique": (),
}
CATEGORY_NOTES = {
    "roadster": "Catégorie Bikez « Naked bike » ; elle ne couvre pas tous les roadsters au sens courant.",
    "trail": "Catégorie Bikez « Enduro/offroad », large : elle inclut aussi l'enduro et le tout-terrain, sans prouver un usage routier.",
    "routiere": "Catégories Bikez « Touring » et « Sport touring » ; classement source, pas une évaluation du confort.",
    "sportive": "Catégorie Bikez « Sport » ; classement source, pas une évaluation des performances.",
    "electrique": "Motorisation explicitement électrique dans la fiche Motoplanète ; le démarreur électrique ne suffit pas. Pour une exclusion, seul un carburant thermique explicite sans indice hybride est retenu : « 4 temps » seul ne prouve pas l'absence de propulsion électrique.",
}


def identity_key(brand, model, year):
    """Normalize typography while preserving year, variant and numeric identity.

    Numeric decimal/fraction separators stay meaningful (R25/2 != R252).
    All letters and digits stay in their original order; no fuzzy aliasing.
    """
    def compact(value):
        value = folded(value)
        return ''.join(char for index, char in enumerate(value)
                       if char.isalnum() or
                       (char in './,' and index and index + 1 < len(value)
                        and value[index - 1].isdigit() and value[index + 1].isdigit()))
    return compact(brand), compact(model), year


def _raw_category(value):
    return re.sub(r'\s+', ' ', folded(value)).strip()


def _valid_bikez_url(value):
    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        return False
    return parsed.scheme in ('https', 'http') and parsed.hostname in ('bikez.com', 'www.bikez.com')


def categories_from_text(text, protected_spans=()):
    """Recognize an explicit category noun; never infer one from a price.

    Callers can protect already resolved model-name spans, so a category-like
    word inside a named model does not silently become another constraint.
    """
    normalized = folded(text)
    patterns = {
        'roadster': r'roadsters?', 'trail': r'trails?',
        'routiere': r'routieres?', 'sportive': r'sportives?',
        'electrique': r'electriques?',
    }
    results = []
    for category, pattern in patterns.items():
        for match in re.finditer(r'\b' + pattern + r'\b', normalized):
            start, end = match.span()
            if any(start < right and end > left for left, right in protected_spans):
                continue
            before = normalized[max(0, start - 70):start]
            # Singular terms need a generic request construction. This avoids
            # treating "Triumph Roadster 2023" as a category without a resolver.
            generic = bool(re.search(r"(?:\b(?:les|des|de|du|un|une|le|la|ces|mes|vos|nos|quel|quelle|quels|quelles)\s+|\b(?:motos?|modeles?|moteur)\s+|\b(?:pas|sans|sauf|hors|non)\s+)$", before))
            generic = generic or match[0].endswith('s') or bool(re.search(r'\b(?:categorie|type)\s+(?:de\s+)?$', before))
            if not generic:
                continue
            # "Démarrage électrique" is equipment, not electric propulsion.
            if category == 'electrique' and re.search(r'\b(?:demarrage|demarreur|suspension|selle)\s+$', before):
                continue
            negative = bool(re.search(r"\b(?:pas|sans|sauf|hors|exclure|exclus|evite|eviter|non)\s+(?:(?:de|des|les|la|le|du)\s+)?$", before))
            # "Pas forcément sportive" is not a strict exclusion.
            if re.search(r'\bpas\s+(?:forcement|necessairement)\s+$', before):
                continue
            candidate = {'category': category, 'negated': negative,
                         'mention': text[start:end], 'span': (start, end)}
            if not any(item['category'] == category and item['negated'] == negative for item in results):
                results.append(candidate)
    return sorted(results, key=lambda item: item['span'])


def parse_category(text, protected_spans=()):
    """One explicit category request, or None when absent/ambiguous.

    A caller that handles multiple constraints can use categories_from_text.
    This small interface deliberately does not silently drop a second category.
    """
    mentions = categories_from_text(text, protected_spans)
    if len(mentions) != 1:
        return None
    return {key: mentions[0][key] for key in ('category', 'negated')}


def _validate_request(request):
    if (not isinstance(request, dict) or not isinstance(request.get('category'), str)
            or request['category'] not in CATEGORY_LABELS):
        raise ValueError('Unsupported source category')
    if not isinstance(request.get('negated', False), bool):
        raise ValueError('Category negation must be a boolean')
    identity = request.get('identity')
    if identity is None:
        identity = {}
    if not isinstance(identity, dict) or set(identity) - {'brand', 'model', 'year', 'min_year', 'max_year'}:
        raise ValueError('Unsupported category identity scope')
    for key, value in identity.items():
        if value is None:
            continue
        if key in ('brand', 'model'):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Identity names must be nonempty strings')
        elif isinstance(value, bool) or not isinstance(value, int):
            raise ValueError('Identity years must be integers')
    if identity.get('min_year') is not None and identity.get('max_year') is not None:
        if identity['min_year'] > identity['max_year']:
            raise ValueError('Invalid category year range')
    return identity


def _technical_rows(conn, identity, electric):
    clauses, params = ['TRUE'], []
    for name, operator in (('year', '='), ('min_year', '>='), ('max_year', '<=')):
        if identity.get(name) is not None:
            clauses.append('year ' + operator + ' %s')
            params.append(identity[name])
    columns = 'id,brand,model,year,source_url'
    if electric:
        # Fetch only motor rows, not the entire technical record per fiche.
        columns += ",COALESCE((SELECT jsonb_agg(s) FROM jsonb_array_elements(record->'spec_rows') s WHERE s->>'section'='Moteur'),'[]'::jsonb) AS motor_rows"
    rows = _rows(conn, 'SELECT ' + columns + ' FROM technical_fiches WHERE ' + ' AND '.join(clauses), params)
    for name in ('brand', 'model'):
        if identity.get(name):
            requested = identity_key(identity.get('brand', ''), identity.get('model', ''), 0)
            position = 0 if name == 'brand' else 1
            rows = [row for row in rows if identity_key(row['brand'], row['model'], 0)[position] == requested[position]]
    return rows


def _electric_evidence(row):
    """Return explicit propulsion evidence, or None for an unknown/conflict."""
    motor_rows = row.get('motor_rows', [])
    if isinstance(motor_rows, str):
        motor_rows = json.loads(motor_rows)
    electric, combustion, thermal_fuel = [], [], []
    hybrid = bool(re.search(r'\bhybrid(?:e|es|s)?\b', folded(row.get('brand', '') + ' ' + row.get('model', ''))))
    motor_battery = False
    for spec in motor_rows:
        if spec.get('section') != 'Moteur':
            continue
        label, text = folded(spec.get('label', '')), folded(spec.get('value', ''))
        if 'demarrage' not in label and 'demarreur' not in label:
            hybrid = hybrid or bool(re.search(r'\bhybrid(?:e|es|s)?\b', text))
            motor_battery = motor_battery or bool(re.search(r'\bbatterie\b', text))
        if label not in ('', 'carburant', 'type', 'type de moteur', 'motorisation'):
            continue
        electrical = bool(re.search(r'\belectrique\b', text) or
                          (label == 'carburant' and re.search(r'\belectricite\b', text)))
        fuel = label == 'carburant' and bool(re.search(r'\b(?:essence|diesel|sans\s*plomb|sp\s*9[58])\b', text))
        if electrical:
            electric.append(spec)
        if (re.search(r'\b[24]\s+temps\b', text)
                or fuel):
            combustion.append(spec)
        if fuel:
            thermal_fuel.append(spec)
        if fuel and electrical:
            hybrid = True
    # A hybrid is a legitimate mixed propulsion, not contradictory source
    # data. Neither a cylinder nor a four-stroke line excludes electric drive.
    if hybrid or (motor_battery and combustion):
        return None, False
    if electric and combustion:
        return None, True
    if not electric and not thermal_fuel:
        return None, False
    return {'source': 'motoplanete', 'source_url': row['source_url'],
            'source_identity': {'brand': row['brand'], 'model': row['model'], 'year': row['year']},
            'category_raw': 'motorisation électrique' if electric else 'carburant thermique explicite',
            'is_electric': bool(electric), 'spec_rows': electric or thermal_fuel}, False


def source_category_scope(conn, request):
    """Return exact object IDs and source proofs for one category constraint.

    ``request`` accepts category, optional negated and optional identity scope.
    Callers must intersect these IDs with other SQL constraints before LIMIT.
    Unknowns and conflicting sources are *never* selected by a negation.
    The helper is read-only and performs no classification with a model.
    """
    identity = _validate_request(request)
    category, negated = request['category'], request.get('negated', False)
    fiches = _technical_rows(conn, identity, category == 'electrique')
    proofs, known, conflicts, selected = {}, set(), set(), set()
    labels = {_raw_category(label) for label in CATEGORY_LABELS[category]}
    if category == 'electrique':
        for fiche in fiches:
            evidence, conflict = _electric_evidence(fiche)
            if conflict:
                conflicts.add(fiche['id'])
            if evidence is None:
                continue
            known.add(fiche['id'])
            if evidence['is_electric'] != negated:
                selected.add(fiche['id'])
                proofs[fiche['id']] = [evidence]
    else:
        source_rows = _rows(conn, 'SELECT brand,model,year,category,url FROM motorcycles', [])
        index = defaultdict(list)
        for row in source_rows:
            if _valid_bikez_url(row['url']):
                index[identity_key(row['brand'], row['model'], row['year'])].append(row)
        for fiche in fiches:
            candidates = index.get(identity_key(fiche['brand'], fiche['model'], fiche['year']), [])
            raw_labels = {_raw_category(row['category']) for row in candidates}
            if len(raw_labels) > 1:
                conflicts.add(fiche['id'])
            if len(raw_labels) != 1 or not candidates:
                continue
            raw_label = next(iter(raw_labels))
            if not raw_label or raw_label == 'unspecified category':
                continue
            known.add(fiche['id'])
            if (raw_label in labels) == negated:
                continue
            selected.add(fiche['id'])
            unique = {(row['url'], row['category']): row for row in candidates}
            proofs[fiche['id']] = [{'source': 'bikez', 'source_url': url,
                                    'category_raw': raw,
                                    'source_identity': {'brand': row['brand'], 'model': row['model'], 'year': row['year']},
                                    'identity_match': 'same brand, model and year; typography only'}
                                   for (url, raw), row in sorted(unique.items())]
    all_ids = {row['id'] for row in fiches}
    return {'category': category, 'negated': negated,
            'ids': sorted(selected), 'proofs': proofs,
            'known_ids': sorted(known), 'unknown_ids': sorted(all_ids - known),
            'conflict_ids': sorted(conflicts), 'non_exhaustive': True,
            'raw_categories': list(CATEGORY_LABELS[category]),
            'source_note': CATEGORY_NOTES[category],
            'coverage': {'scope_objects': len(all_ids), 'known_objects': len(known),
                         'matching_objects': len(selected), 'unknown_objects': len(all_ids - known),
                         'conflicting_objects': len(conflicts)}}

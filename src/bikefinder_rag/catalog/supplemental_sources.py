"""Exact, read-only supplemental source evidence; no cross-catalog overwrite.

Only two missing details are covered here. Returned values stay verbatim and
carry their own Bikez provenance. No model variant, country or equipment
fitment status is inferred from a nearby name or an abbreviation.
"""
import json
import re
from urllib.parse import urlsplit

from bikefinder_rag.catalog.category_evidence import identity_key, _valid_bikez_url
from bikefinder_rag.catalog.enriched import folded, _rows


CHARACTERISTICS = {'ground_clearance', 'cruise_control'}
_EQUIPMENT_LABELS = {'comments', 'features', 'electronics', 'electronic rider aids',
                     'cruise control', 'additional information'}
_YEAR_LABELS = {'year model', 'model year', 'year of manufacture', 'year'}
_NAME_LABELS = {'motorcycle name', 'model name', 'model', 'name'}


def _label(value):
    return re.sub(r'\s+', ' ', folded(value)).strip()


def _valid_identity(identity):
    return (isinstance(identity, dict)
            and all(isinstance(identity.get(key), str) and identity[key].strip()
                    for key in ('brand', 'model'))
            and isinstance(identity.get('year'), int)
            and not isinstance(identity['year'], bool))


def _raw_specs(row):
    raw = row.get('raw_specs', {})
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    return raw if isinstance(raw, dict) else None


def _source_identity_consistent(row, specs):
    """Reject source metadata contradicting its stored table identity."""
    path = urlsplit(row['url']).path
    if not path.startswith('/motorcycles/'):
        return False
    url_year = re.search(r'_(\d{4})\.php$', path)
    if url_year and int(url_year[1]) != row['year']:
        return False
    expected_name = identity_key(row['brand'], row['brand'] + ' ' + row['model'], row['year'])[1]
    for name, value in specs.items():
        if not isinstance(name, str):
            return False
        label = _label(name)
        if label in _YEAR_LABELS:
            if str(value).strip() != str(row['year']):
                return False
        if label in _NAME_LABELS:
            if not isinstance(value, str) or identity_key('', value, row['year'])[1] != expected_name:
                return False
    return True


def _characteristic_rows(specs, characteristic):
    rows = []
    for name, value in specs.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        label = _label(name)
        if characteristic == 'ground_clearance':
            if label != 'ground clearance':
                continue
            # A labeled blank/NC is not a measurement. No unit conversion or
            # numerical projection is performed; the complete row is quoted.
            if not re.match(r'^\s*\d+(?:[.,]\d+)?\s*(?:mm|cm|inches?|in)\b', folded(value)):
                continue
        else:
            if label not in _EQUIPMENT_LABELS:
                continue
            # ACC alone can mean different things. A source must spell out
            # cruise control / régulateur de vitesse on this exact source row.
            if label == 'cruise control':
                if _label(value) in {'', '-', 'nc', 'n.c.', 'n/a', 'unknown', 'not known', 'not provided'}:
                    continue
            elif not re.search(r'\bcruise[\s-]+control\b|\bregulateur de vitesse\b', folded(value)):
                continue
        rows.append({'label': name, 'value': value})
    return rows


def extract_supplemental_rows(identity, bikez_rows, characteristic):
    """Pure extraction from supplied rows, with an exact identity boundary.

    Unknown or conflicting evidence returns an empty list. A missing row on
    another identical source is unknown, not a contrary assertion. Different
    known raw values are conservatively treated as a conflict; no source is
    chosen arbitrarily. The caller decides whether primary evidence is missing.
    """
    if not isinstance(characteristic, str) or characteristic not in CHARACTERISTICS:
        raise ValueError('Unsupported supplemental characteristic')
    if not _valid_identity(identity) or not isinstance(bikez_rows, (list, tuple)):
        return []
    key = identity_key(identity['brand'], identity['model'], identity['year'])
    evidence = []
    for source in bikez_rows:
        if not _valid_identity(source) or not _valid_bikez_url(source.get('url')):
            continue
        if identity_key(source['brand'], source['model'], source['year']) != key:
            continue
        specs = _raw_specs(source)
        if specs is None or not _source_identity_consistent(source, specs):
            continue
        for spec in _characteristic_rows(specs, characteristic):
            item = {**spec, 'source': 'bikez', 'source_url': source['url'],
                    'source_identity': {name: source[name] for name in ('brand', 'model', 'year')},
                    'characteristic': characteristic,
                    'identity_match': 'same brand, model and year; typography only'}
            if characteristic == 'cruise_control':
                item['equipment_status'] = 'unknown'
                item['qualifier'] = 'Mention source explicite ; statut série/option et marché non établis.'
            evidence.append(item)
    known_values = {_label(item['value']) for item in evidence}
    if len(known_values) != 1:
        return []
    unique = {(item['source_url'], item['label'], item['value']): item for item in evidence}
    return [item for _, item in sorted(unique.items())]


def get_supplemental_rows(conn, identity, characteristic):
    """Read existing Bikez records only; no fetching, writing or inference."""
    if not isinstance(characteristic, str) or characteristic not in CHARACTERISTICS:
        raise ValueError('Unsupported supplemental characteristic')
    if not _valid_identity(identity):
        return []
    source_rows = _rows(conn, 'SELECT brand,model,year,url,raw_specs FROM motorcycles WHERE year=%s', [identity['year']])
    return extract_supplemental_rows(identity, source_rows, characteristic)

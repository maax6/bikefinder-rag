"""Literal equipment evidence for details, independent of derived projections.

No catalogue filters or persisted equipment statuses are changed here. A raw
mention can establish presence while leaving inclusion/option status unknown.
"""
import re

from bikefinder_rag.catalog.enriched import folded


ABS = re.compile(r'(?<![a-z0-9])a[.\s]*b[.\s]*s\.?(?![a-z0-9])')
OTHER_EQUIPMENT = re.compile(r'\b(?:shifter|dct|regulateur|controle\s+de\s+traction)\b')
STANDARD = re.compile(r'\b(?:de\s+serie|en\s+serie|standard|d[\x27’]origine)\b')
OPTION = re.compile(r'\b(?:en\s+option|optionnel(?:le)?|option)\b')
ABSENT = re.compile(r'\b(?:sans|absent(?:e)?|absence|pas\s+d[\x27’]?|non\s+(?:equipe|disponible|present))\b')
UNKNOWN = re.compile(r'(?:\b(?:inconnu|non\s+(?:communique|renseigne|defini|documente)|nc)\b|(?<!\w)n\.c\.?(?!\w))')


def _eligible(row):
    section = folded(str(row.get('section', ''))).strip()
    label = folded(str(row.get('label', ''))).strip()
    value = folded(str(row.get('value', ''))).strip()
    # An explicit equipment statement remains a statement even if the parser
    # placed it in another technical section. A bare model-name ABS is not.
    qualified_inline = bool(re.search(ABS.pattern + r'\s*(?::\s*)?(?:de\s+serie|en\s+serie|standard|en\s+option|optionnel(?:le)?|absent(?:e)?)\b', value))
    qualified_label = bool(ABS.fullmatch(label) and (STANDARD.search(value) or OPTION.search(value) or ABSENT.search(value)))
    return (section.startswith(('equipement', 'assistance'))
            or label in ('assistance au freinage', 'assistances au freinage')
            or qualified_inline or qualified_label
            or (section in ('train avant', 'train arriere', 'freinage')
                and label in ('freinage', 'assistance', 'abs', 'a.b.s.', 'a.b.s')))


def _states(row):
    """Classify only the ABS clause, without borrowing a shifter's option."""
    section = folded(str(row.get('section', '')))
    label = folded(str(row.get('label', '')))
    value = folded(str(row.get('value', '')))
    pieces = re.split(r'[;|]', value)
    clauses = [piece for piece in pieces if ABS.search(piece)]
    if not clauses and ABS.search(label):
        if not value.strip() or UNKNOWN.search(value) or value.strip() in ('-', 'n/a', 'non renseigne'):
            return set()
        clauses = pieces
    states = set()
    for clause in clauses:
        if UNKNOWN.search(clause):
            continue
        # A neighbouring equipment item has its own inclusion qualifier.
        match = OTHER_EQUIPMENT.search(clause)
        if match and ABS.search(clause) and match.start() > ABS.search(clause).start():
            clause = clause[:match.start()]
        absent = bool(ABSENT.search(clause)) or (ABS.search(label) and clause.strip() in ('non', 'absent', 'aucun'))
        optional, standard = bool(OPTION.search(clause)), bool(STANDARD.search(clause))
        if absent:
            states.add('explicitly_absent')
        if optional:
            states.add('optional')
        if standard:
            states.add('standard')
        if not (absent or optional or standard):
            # The source heading is itself an explicit inclusion statement.
            if 'de serie' in section:
                states.add('standard')
            elif 'option' in section:
                states.add('optional')
            else:
                states.add('present_unqualified')
    return states


def abs_source_answer(record):
    """Return a sourced ABS detail string, or None when no literal proof exists.

    Accept the raw technical record or a containing catalogue row. This helper
    is pure and intentionally has no connection, classifier or API argument.
    """
    if not isinstance(record, dict):
        return None
    if 'spec_rows' not in record and isinstance(record.get('record'), dict):
        record = record['record']
    proofs, states, seen = [], set(), set()
    for row in record.get('spec_rows', []):
        if not isinstance(row, dict) or not _eligible(row):
            continue
        if not ABS.search(folded(str(row.get('label', '')) + ' ' + str(row.get('value', '')))):
            continue
        key = tuple(str(row.get(name, '')) for name in ('section', 'label', 'value'))
        if key in seen:
            continue
        row_states = _states(row)
        if not row_states:
            continue
        seen.add(key)
        proofs.append(row)
        states.update(row_states)
    if not proofs:
        return None
    qualified = states - {'present_unqualified'}
    conflict = len(qualified) > 1 or ('explicitly_absent' in states and 'present_unqualified' in states)
    if conflict:
        status = 'ABS : mentions contradictoires ; présence et statut non tranchés.'
    elif 'explicitly_absent' in states:
        status = 'ABS : absence explicitement documentée.'
    elif 'optional' in states:
        status = 'ABS : en option selon la source ; sa présence sur un exemplaire n’est pas établie.'
    elif 'standard' in states:
        status = 'ABS : présence documentée, de série selon la mention ou la section source.'
    else:
        status = 'ABS : présence documentée ; statut série / option non précisé.'
    rendered = []
    for row in proofs:
        section, label, value = (str(row.get(name, '')).replace('\n', ' ') for name in ('section', 'label', 'value'))
        rendered.append(section + (' · ' + label if label else '') + ' : ' + value)
    return status + ' Preuve source : « ' + ' » ; « '.join(rendered) + ' ».'


def source_equipment_answer(record, equipment='ABS'):
    """Only ABS is supported; unrelated equipment must keep its own evidence."""
    return abs_source_answer(record) if isinstance(equipment, str) and ABS.fullmatch(folded(equipment).strip()) else None

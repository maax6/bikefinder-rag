"""Conservative, pure measurement normalization for the versioned pilot.

Only the preserved raw sheet is evidence. Legacy numeric columns never fill
an unknown value: their units and dry/wet conventions were not validated.
Values describe the source, not independently measured motorcycle performance.

Conversion references checked on 2026-10-10:
* BIPM SI prefixes: https://www.bipm.org/en/measurement-units/si-prefixes
* NIST SP811 B.9 and notes 22/23: https://www.nist.gov/pml/special-publication-811
* PS/cheval-vapeur: historical EU units table, CELEX 31971L0354;
  NIST B.9 separately distinguishes metric and mechanical horsepower.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any
import unicodedata


_BIPM_PREFIXES = "https://www.bipm.org/en/measurement-units/si-prefixes"
_NIST_FACTORS = (
    "https://www.nist.gov/pml/special-publication-811/"
    "nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b9"
)
_NIST_NOTES = "https://www.nist.gov/pml/special-publication-811/nist-guide-si-footnotes"
_METRIC_HORSEPOWER = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:31971L0354"

# Canonical unit, measurement nature, accepted original labels. Labels are
# deliberately finite; new aliases can be added under a new pilot version.
_FIELDS = {
    "displacement_ccm": ("cm³", "undocumented", ("displacement", "engine size", "cylindrée")),
    "weight_dry_kg": ("kg", "dry", ("dry weight", "poids à sec")),
    "weight_wet_kg": ("kg", "wet", (
        "weight incl. oil, gas, etc", "wet weight", "kerb weight", "curb weight",
        "poids tous pleins faits", "poids en ordre de marche",
    )),
    "weight_unspecified_kg": ("kg", "unspecified", ("weight", "poids")),
    "power_kw": ("kW", "undocumented", ("power output", "power", "output", "effect", "puissance")),
    "torque_nm": ("N·m", "undocumented", ("torque", "couple")),
    "seat_height_mm": ("mm", "undocumented", ("seat height", "hauteur de selle")),
    "top_speed_kmh": ("km/h", "undocumented", ("top speed", "maximum speed", "vitesse maximale")),
}

# Ordered preferences apply inside one source cell: the explicit canonical
# unit wins over a rounded parenthetical alternative. Multiple values in that
# preferred unit still conflict. No HP, bhp, or fiscal CV convention is inferred.
_MASS_UNITS = [
    (r"kg|kilograms?", "kg", 1.0, _BIPM_PREFIXES),
    (r"lbs?\.?|pounds?", "lb", 0.45359237, _NIST_NOTES),
]
_UNITS = {
    "displacement_ccm": [
        (r"ccm|cc|cm\s*(?:³|\^?3)", "cm³", 1.0, _BIPM_PREFIXES),
        (r"litres?|liters?|l", "L", 1000.0, _BIPM_PREFIXES),
        (r"cu\.?\s*in\.?|in\s*(?:³|\^?3)", "in³", 16.387064, _NIST_NOTES),
    ],
    "weight_dry_kg": _MASS_UNITS,
    "weight_wet_kg": _MASS_UNITS,
    "weight_unspecified_kg": _MASS_UNITS,
    "power_kw": [
        (r"kW|kilowatts?", "kW", 1.0, _BIPM_PREFIXES),
        (r"W|watts?", "W", 0.001, _BIPM_PREFIXES),
        (r"PS|ch|chevaux(?:[- ]vapeur)?|cheval[- ]vapeur", "PS", 0.73549875, _METRIC_HORSEPOWER),
    ],
    "torque_nm": [
        (r"N\s*[·.*]?\s*m|newton[- ]met(?:er|re)s?", "N·m", 1.0, _BIPM_PREFIXES),
        (r"lbf\s*[·.*-]?\s*ft|ft\s*[·.*-]?\s*lbf", "lbf·ft", 1.3558179483314, _NIST_NOTES),
    ],
    "seat_height_mm": [
        (r"mm|millimet(?:er|re)s?", "mm", 1.0, _BIPM_PREFIXES),
        (r"cm|centimet(?:er|re)s?", "cm", 10.0, _BIPM_PREFIXES),
        (r"inches|inch|in\.?", "in", 25.4, _NIST_FACTORS),
    ],
    "top_speed_kmh": [
        (r"km\s*/\s*h|kmh|kph", "km/h", 1.0, _BIPM_PREFIXES),
        (r"mph|mi\s*/\s*h", "mph", 1.609344, _NIST_FACTORS),
        (r"m\s*/\s*s", "m/s", 3.6, _NIST_FACTORS),
    ],
}

_NUMBER = r"(?<![\w.,+^\-])(?P<number>[+-]?\s*(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?)\s*"
_RANGE = re.compile(r"\d(?:[.,]\d+)?\s*(?:-|–|—|/|\bto\b|\bà\b)\s*\d", re.IGNORECASE)
_AMBIGUOUS_HP = re.compile(_NUMBER + r"(?P<unit>HP|bhp|CV)(?!\w)", re.IGNORECASE)
_PLACEHOLDERS = {"", "loading...", "unknown", "n/a", "na", "not available", "-"}
_DRY_QUALIFIER = re.compile(r"\b(?:dry|a sec)\b")
_WET_QUALIFIER = re.compile(r"\b(?:wet|kerb|curb|tous pleins|en ordre de marche)\b")
_CONFIGURATION_QUALIFIER = re.compile(
    r"\b(?:restricted|bridable|bride|bridee|optional|option|variant|version|configuration)\b"
    r"|\b(?:with|without|avec|sans) abs\b"
)


def _label(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


_LABEL_FIELDS = {_label(label): name for name, (_, _, labels) in _FIELDS.items() for label in labels}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _number(text: str) -> float | None:
    try:
        value = float(Decimal(re.sub(r"\s", "", text).replace(",", ".")))
    except (ValueError, InvalidOperation, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _display_rounding(text: str, factor: float) -> float:
    """Half a displayed final digit, solely for checking unit restatements.

    This is not a claimed physical measurement uncertainty. It avoids treating
    e.g. 236.0 kg and its rounded 520.3 lb restatement as contradictory.
    """
    decimal = Decimal(re.sub(r"\s", "", text).replace(",", "."))
    return float(Decimal("0.5") * Decimal(10) ** decimal.as_tuple().exponent) * factor


def _evidence(row: dict, label: str, raw: Any, value=None, unit=None, conversion=None) -> dict:
    return {
        "label": label, "raw_value": raw if isinstance(raw, str) else _text(raw),
        "source_url": _text(row.get("url")), "collected_at": _text(row.get("scraped_at")),
        "original_value": value, "original_unit": unit, "conversion": conversion,
    }


def _parse_cell(row: dict, label: str, raw: Any, field: str) -> tuple[list, list, list, bool]:
    evidence, candidates, warnings = [], [], []
    if raw is None:
        return [_evidence(row, label, raw)], [], ["Source value is unavailable."], False
    if not isinstance(raw, str):
        return [_evidence(row, label, raw)], [], ["Source value is not text; no unit was assumed."], True
    if raw.strip().casefold() in _PLACEHOLDERS:
        return [_evidence(row, label, raw)], [], ["Source value is unavailable."], False
    text = raw.replace("−", "-")
    qualifiers = _label(raw)
    contradicts_nature = (
        field == "weight_wet_kg" and bool(_DRY_QUALIFIER.search(qualifiers))
        or field == "weight_dry_kg" and bool(_WET_QUALIFIER.search(qualifiers))
    )
    scoped_configuration = bool(_CONFIGURATION_QUALIFIER.search(qualifiers))
    if contradicts_nature:
        warnings.append("Source qualifier contradicts the dry/wet label; no weight of that nature is selected.")
    if scoped_configuration:
        warnings.append(
            "Measurement is scoped to a configuration or variant; the pilot does not bind or generalize it."
        )
    is_range = bool(_RANGE.search(text))
    if is_range:
        warnings.append("Source contains a range or alternatives; no single value is selected.")
    valid_by_unit = []
    for rank, (pattern, unit, factor, reference) in enumerate(_UNITS[field]):
        values = []
        for match in re.finditer(_NUMBER + f"(?P<unit>{pattern})(?![\\w/^])", text, re.IGNORECASE):
            original = _number(match.group("number"))
            conversion = {"from_unit": unit, "to_unit": _FIELDS[field][0],
                          "factor": factor, "reference_url": reference}
            evidence.append(_evidence(row, label, raw, original, match.group("unit"), conversion))
            if original is None or original <= 0 or not math.isfinite(original * factor):
                warnings.append("Non-positive or non-finite source value was rejected.")
            else:
                values.append((original * factor, _display_rounding(match.group("number"), factor)))
        if values:
            valid_by_unit.append((rank, values))
    if field == "power_kw":
        for match in _AMBIGUOUS_HP.finditer(text):
            evidence.append(_evidence(row, label, raw, _number(match.group("number")), match.group("unit")))
            warnings.append("HP/bhp/CV has no documented convention; no horsepower conversion was applied.")
    if valid_by_unit and not is_range:
        preferred = valid_by_unit[0][1]
        candidates = [value for value, _ in preferred]
        if len(valid_by_unit) > 1:
            warnings.append("Explicit preferred unit used; alternative unit values retained as evidence.")
            for _, alternatives in valid_by_unit[1:]:
                for value, rounding in alternatives:
                    if not any(abs(value - primary) <= rounding + primary_rounding + 1e-9
                               for primary, primary_rounding in preferred):
                        candidates.append(value)
                        warnings.append("Unit alternatives disagree beyond their displayed rounding.")
    if not evidence:
        evidence.append(_evidence(row, label, raw))
        warnings.append("No supported explicit value and unit were found.")
    # A substantive alias that could not be parsed must not silently disappear
    # behind another alias's scalar. Explicit unavailable placeholders above
    # are the exception: they make no competing assertion.
    unresolved = is_range or contradicts_nature or scoped_configuration or not candidates
    return evidence, candidates, warnings, unresolved


def normalize_measurements(row: dict) -> dict:
    """Return eight independent, JSON-serializable measurements with proofs.

    A scalar requires explicit units and agreeing evidence. Ranges, weight
    nature contradictions, unresolved substantive aliases and configuration
    qualifiers cannot become a scalar. The pilot does not bind conditional
    values to variants, even when a separate variant label is present. RPM,
    adjustments and qualifiers remain in raw_value; no family/year information
    is borrowed.
    """
    result = {name: {"value": None, "unit": unit, "nature": nature,
                     "status": "unknown", "evidence": [], "warnings": []}
              for name, (unit, nature, _) in _FIELDS.items()}
    values = {name: [] for name in _FIELDS}
    unresolved = set()
    raw_specs = row.get("raw_specs")
    if not isinstance(raw_specs, dict):
        for measurement in result.values():
            measurement["warnings"].append("No preserved raw specification mapping is available.")
        return result
    for label, raw in raw_specs.items():
        if not isinstance(label, str) or (field := _LABEL_FIELDS.get(_label(label))) is None:
            continue
        proof, candidates, warnings, uncertain = _parse_cell(row, label, raw, field)
        measurement = result[field]
        measurement["evidence"].extend(proof)
        measurement["warnings"].extend(warnings)
        values[field].extend(candidates)
        if uncertain:
            unresolved.add(field)
        if measurement["nature"] == "undocumented" and isinstance(raw, str):
            if re.search(r"\b(claimed|announced|advertised|annoncee?)\b", _label(raw)):
                measurement["nature"] = "announced"
    for field, candidates in values.items():
        measurement = result[field]
        if candidates and any(not math.isclose(value, candidates[0], rel_tol=1e-9, abs_tol=1e-9)
                              for value in candidates[1:]):
            measurement["status"] = "conflict"
            measurement["warnings"].append("Conflicting documented values; no scalar value is selected.")
        elif candidates and field not in unresolved:
            measurement.update(value=candidates[0], status="documented")
        measurement["warnings"] = list(dict.fromkeys(measurement["warnings"]))
    return result

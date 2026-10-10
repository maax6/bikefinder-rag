"""Versioned identities for literal catalog names, never model families.

Only case, Unicode composition and whitespace are canonicalized for IDs.
Punctuation and every model number remain significant. Brand boundaries use
an exact, sourced vocabulary; variants and markets require explicit labels.
"""

from datetime import date, datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Iterable
import unicodedata


IDENTITY_VERSION = "identity-v1"
_VOCABULARY_PATH = Path(__file__).with_name("brands.json")
_EMPTY_VALUES = {"", "loading...", "unknown", "n/a", "not available", "not documented",
                 "not specified", "none", "-", "non documenté", "non documentée",
                 "inconnu", "inconnue"}


def _text(value) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(unicodedata.normalize("NFC", value).split()) or None


def _key(value: str) -> str:
    return unicodedata.normalize("NFC", _text(value).casefold())


@lru_cache(maxsize=1)
def _vocabulary() -> dict:
    return json.loads(_VOCABULARY_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def known_brands() -> tuple[str, ...]:
    """Names observed in the retained snapshot, plus explicitly sourced names."""
    return tuple(entry["name"] for entry in _vocabulary()["brands"])


@lru_cache(maxsize=16)
def _brand_prefixes(brands: tuple[str, ...]) -> tuple:
    labels = {_text(brand) for brand in brands} - {None}
    return tuple((brand, tuple(_key(word) for word in brand.split()))
                 for brand in sorted(labels, key=lambda brand: (-len(brand), brand)))


@lru_cache(maxsize=1)
def _brand_entries() -> dict:
    return {entry["name"]: entry for entry in _vocabulary()["brands"]}


def split_brand_model(name: str, brands: Iterable[str] | None = None) -> tuple[str | None, str]:
    """Prefer the longest exact brand prefix with a whitespace boundary.

    An unknown prefix returns (None, full_name): callers must surface the
    uncertainty rather than treating the first word as a verified brand.
    """
    name = _text(name) or ""
    words = name.split()
    word_keys = tuple(_key(word) for word in words)
    for brand, prefix in _brand_prefixes(tuple(brands) if brands is not None else known_brands()):
        if word_keys[:len(prefix)] == prefix:
            return brand, " ".join(words[len(prefix):])
    return None, name


def _stable_id(kind: str, *parts: str) -> str:
    serialized = json.dumps([IDENTITY_VERSION, kind, *parts], ensure_ascii=False,
                            separators=(",", ":"))
    return f"{IDENTITY_VERSION}:{kind}:{hashlib.sha256(serialized.encode()).hexdigest()}"


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def normalize_identity(row: dict) -> dict:
    """Normalize one DB-shaped record without modifying it or its raw values.

    Unknown brands retain literal provisional IDs and need review. A model
    suffix such as N, S, Sport or ABS remains part of the complete model name,
    and does not become a variant. Enfield is not aliased to Royal Enfield.
    """
    warnings = []
    evidence = {}
    raw_brand, raw_model, raw_year = (row.get(field) for field in ("brand", "model", "year"))
    brand, model = _text(raw_brand), _text(raw_model)
    full_name = " ".join(part for part in (brand, model) if part)
    matched_brand, matched_model = split_brand_model(full_name)
    if matched_brand and brand:
        brand, model = matched_brand, matched_model or None
        vocabulary = _vocabulary()
        entry = _brand_entries()[brand]
        evidence["brand"] = {
            "label": brand,
            "vocabulary_version": vocabulary["version"],
            "source": dict(vocabulary["sources"][entry["source"]]),
        }
        if _key(raw_brand) != _key(brand):
            warnings.append("brand_model_split_corrected")
    else:
        warnings.append("brand_not_in_vocabulary" if brand else "brand_missing")
    if not model:
        warnings.append("model_missing")

    year = raw_year if isinstance(raw_year, int) and not isinstance(raw_year, bool) and raw_year > 0 else None
    if year is None:
        warnings.append("model_year_invalid")
    specs = row.get("raw_specs") or {}
    if not isinstance(specs, dict):
        specs = {}
        warnings.append("raw_specs_invalid")

    def explicit(field: str) -> str | None:
        values = []
        for label, raw_value in specs.items():
            if isinstance(label, str) and label.strip().rstrip(":").casefold() == field:
                value = _text(raw_value)
                if value and value.casefold() not in _EMPTY_VALUES:
                    values.append((label, value, raw_value))
        if len({_key(value) for _, value, _ in values}) > 1:
            warnings.append(f"conflicting_{field}")
            evidence[field] = [{"label": label, "raw_value": raw} for label, _, raw in values]
            return None
        if values:
            label, value, raw = values[0]
            evidence[field] = {"label": label, "raw_value": raw}
            return value
        return None

    variant, market = explicit("variant"), explicit("market")
    for label, value in specs.items():
        if not isinstance(label, str):
            continue
        normalized_label = label.strip().rstrip(":").casefold()
        source_text = _text(value)
        if not source_text or source_text.casefold() in _EMPTY_VALUES:
            continue
        if normalized_label in {"model", "model name", "motorcycle name"}:
            evidence.setdefault("names", []).append({"label": label, "raw_value": value})
            if _key(source_text) != _key(full_name):
                warnings.append("source_name_conflict")
        if normalized_label in {"year", "model year", "year of manufacture"}:
            evidence.setdefault("years", []).append({"label": label, "raw_value": value})
            if year is not None and source_text.isdecimal() and int(source_text) != year:
                warnings.append("source_year_conflict")

    brand_id = _stable_id("brand", _key(brand)) if brand else None
    model_id = _stable_id("model", brand_id, _key(model)) if brand_id and model else None
    model_year_id = _stable_id("model-year", model_id, str(year)) if model_id and year else None
    variant_id = (_stable_id("variant", model_year_id, _key(variant), _key(market) if market else "")
                  if model_year_id and variant else None)
    warnings = list(dict.fromkeys(warnings))
    requires_review = any(warning != "brand_model_split_corrected" for warning in warnings)
    status = "needs_review" if requires_review else "corrected" if warnings else "normalized"
    return {
        "brand": brand, "model": model, "model_year": year,
        "variant": variant, "market": market,
        "brand_id": brand_id, "model_id": model_id,
        "model_year_id": model_year_id, "variant_id": variant_id,
        "raw_identity": {"brand": raw_brand, "model": raw_model, "year": raw_year},
        "source": {"url": row.get("url"), "collected_at": _json_value(row.get("scraped_at"))},
        "identity_evidence": evidence, "warnings": warnings, "status": status,
    }

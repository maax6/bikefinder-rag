"""Build a versioned migration candidate without changing the source record."""

from datetime import date, datetime
import hashlib
import json

from bikefinder_rag.catalog import NORMALIZATION_VERSION
from bikefinder_rag.catalog.identity import normalize_identity
from bikefinder_rag.catalog.measurements import normalize_measurements


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported catalog value: {type(value).__name__}")


def normalize_sheet(row: dict) -> dict:
    """Retain the complete raw record and expose independently sourced fields.

    IDs describe literal identities; they never transfer values across years.
    Legacy numeric columns remain in raw_record for audit only.
    """
    serialized = json.dumps(row, default=_json_default, ensure_ascii=False,
                            sort_keys=True, separators=(",", ":"), allow_nan=False)
    raw_record = json.loads(serialized)
    return {
        "normalization_version": NORMALIZATION_VERSION,
        "source_record_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
        "identity": normalize_identity(raw_record),
        "measurements": normalize_measurements(raw_record),
        "raw_record": raw_record,
    }

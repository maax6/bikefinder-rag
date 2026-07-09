"""Category inclusion rules decided during design.

- Scooter: excluded, UNLESS displacement >= 500cc (keeps big crossovers like
  the Honda X-ADV or Yamaha TMAX, which nobody thinks of as "scooters" even
  though bikez.com tags them that way; drops twist-and-go commuters).
- ATV: always excluded (not a motorcycle).
- Everything else (Minibike, Prototype/concept model, Speedway, Trial, ...)
  is kept.
"""

import re

SCOOTER_DISPLACEMENT_THRESHOLD_CCM = 500.0

ALWAYS_EXCLUDED = {"atv"}
CONDITIONALLY_EXCLUDED = {"scooter"}

_CCM_RE = re.compile(r"([\d.]+)\s*ccm", re.IGNORECASE)


def parse_displacement_ccm(engine_text: str) -> float | None:
    """Pull a ccm figure out of a free-text engine field, e.g. '745 ccm'."""
    match = _CCM_RE.search(engine_text or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def is_included(category: str, displacement_ccm: float | None) -> bool:
    normalized = (category or "").strip().lower()

    if normalized in ALWAYS_EXCLUDED:
        return False

    if normalized in CONDITIONALLY_EXCLUDED:
        if displacement_ccm is None:
            return False
        return displacement_ccm >= SCOOTER_DISPLACEMENT_THRESHOLD_CCM

    return True

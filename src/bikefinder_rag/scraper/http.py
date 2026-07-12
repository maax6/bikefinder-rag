"""Shared, polite HTTP client for scraping bikez.com.

One requests.Session, a real identifying User-Agent, and a fixed delay
between every request (SCRAPER_DELAY_SECONDS, default 1.5s) — see the
project README for why we scrape at all (robots.txt only disallows
functional endpoints like rating/submit forms, not the spec/discussion
pages) and why we stay slow on purpose.
"""

import os
import time

import requests

BASE_URL = "https://bikez.com"

USER_AGENT = (
    "bikefinder-rag-project/0.1 "
    "(learning/portfolio RAG project; polite scraper; "
    "https://github.com/maax6/Bikefinder)"
)

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})

_last_request_at: float = 0.0


def _delay_seconds() -> float:
    return float(os.environ.get("SCRAPER_DELAY_SECONDS", "1.5"))


# If the server signals stress (429/5xx), back off hard before one retry —
# this is what makes running with a low SCRAPER_DELAY_SECONDS responsible.
BACKOFF_SECONDS = 30.0
_BACKOFF_STATUSES = {429, 500, 502, 503, 504}


def get(path_or_url: str) -> requests.Response:
    """GET a bikez.com path (or full URL), enforcing a minimum delay since
    the previous request across the whole process."""
    global _last_request_at

    url = path_or_url if path_or_url.startswith("http") else f"{BASE_URL}/{path_or_url.lstrip('/')}"

    elapsed = time.monotonic() - _last_request_at
    wait = _delay_seconds() - elapsed
    if wait > 0:
        time.sleep(wait)

    response = _session.get(url, timeout=20)
    _last_request_at = time.monotonic()

    if response.status_code in _BACKOFF_STATUSES:
        time.sleep(BACKOFF_SECONDS)
        response = _session.get(url, timeout=20)
        _last_request_at = time.monotonic()

    response.raise_for_status()
    return response

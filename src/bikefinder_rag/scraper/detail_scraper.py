"""Scrape a single bikez.com motorcycle page: the spec table, plus (if
linked) its model-level discussion forum.

Page shape, reverse-engineered from https://bikez.com/motorcycles/*.php :
  - One or more <table class="Grid"> containing <tr><th>Section</th></tr>
    dividers and <tr><td><b>Label</b></td><td>Value</td></tr> spec rows.
  - A "Discuss this bike" link to /models/{brand}-{model}-discussions.php,
    shared by every model-year of that model (not year-specific).

Discussion page shape:
  - A list of thread links: /msgboard/msg.php?str_id=...&type=serie&id=...
  - Each thread page has one <table class="Grid"> per message: a title
    row, an "<b>Author</b> said YYYY-MM-DD ..." row, then the message text.
"""

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from bikefinder_rag.scraper import http

_SAID_RE = re.compile(r"^(?P<author>.+?)\s+said\s+(?P<date>\d{4}-\d{2}-\d{2}.*)$")

_NUMERIC_FIELD_PATTERNS: dict[str, re.Pattern] = {
    "displacement_ccm": re.compile(r"([\d.]+)\s*ccm", re.IGNORECASE),
    "weight_kg": re.compile(r"([\d.]+)\s*kg", re.IGNORECASE),
    "power_hp": re.compile(r"([\d.]+)\s*HP", re.IGNORECASE),
    "torque_nm": re.compile(r"([\d.]+)\s*Nm", re.IGNORECASE),
    "seat_height_mm": re.compile(r"([\d.]+)\s*mm", re.IGNORECASE),
}

_SPEC_LABEL_TO_FIELD = {
    "displacement": "displacement_ccm",
    "weight incl. oil, gas, etc": "weight_kg",
    "weight": "weight_kg",
    "power output": "power_hp",
    "torque": "torque_nm",
    "seat height": "seat_height_mm",
}


@dataclass
class Comment:
    author: str
    posted_at: str
    text: str


@dataclass
class MotorcycleDetail:
    raw_specs: dict[str, str] = field(default_factory=dict)
    typed_fields: dict[str, float] = field(default_factory=dict)
    discussion_url: str | None = None


def _extract_numeric(field_name: str, raw_value: str) -> float | None:
    pattern = _NUMERIC_FIELD_PATTERNS.get(field_name)
    if not pattern:
        return None
    match = pattern.search(raw_value)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_spec_page(html: bytes) -> MotorcycleDetail:
    soup = BeautifulSoup(html, "html.parser")
    detail = MotorcycleDetail()

    for table in soup.find_all("table", class_="Grid"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) != 2:
                continue
            label_tag = cells[0].find("b")
            if not label_tag:
                continue

            label = label_tag.get_text(" ", strip=True)
            value = cells[1].get_text(" ", strip=True)
            if not label or not value:
                continue

            detail.raw_specs[label] = value

            field_name = _SPEC_LABEL_TO_FIELD.get(label.lower())
            if field_name and field_name not in detail.typed_fields:
                numeric = _extract_numeric(field_name, value)
                if numeric is not None:
                    detail.typed_fields[field_name] = numeric

    discuss_link = soup.find("a", href=re.compile(r"-discussions\.php"))
    if discuss_link:
        href = discuss_link["href"].replace("../", "")
        detail.discussion_url = f"{http.BASE_URL}/{href.lstrip('/')}"

    return detail


def fetch_motorcycle_detail(url: str) -> MotorcycleDetail:
    response = http.get(url)
    return parse_spec_page(response.content)


def _thread_urls(discussion_html: bytes) -> list[str]:
    soup = BeautifulSoup(discussion_html, "html.parser")
    urls = []
    for a in soup.find_all("a", href=re.compile(r"msg\.php\?str_id=")):
        href = a["href"].replace("../", "")
        urls.append(f"{http.BASE_URL}/{href.lstrip('/')}")
    # De-duplicate while preserving order (topic list can repeat anchors).
    return list(dict.fromkeys(urls))


def _comments_from_thread(thread_html: bytes) -> list[Comment]:
    soup = BeautifulSoup(thread_html, "html.parser")
    comments: list[Comment] = []

    grid = soup.find("table", class_="Grid")
    if not grid:
        return comments

    rows = grid.find_all("tr")
    for i, row in enumerate(rows):
        text = row.get_text(" ", strip=True)
        match = _SAID_RE.match(text)
        if not match:
            continue

        # The body is usually the very next row, but ad rows and empty rows
        # sometimes sit in between — look a little further, stopping at
        # navigation ("<< Previous ...") or the next message header.
        body = ""
        for j in range(i + 1, min(i + 4, len(rows))):
            candidate_row = rows[j]
            if candidate_row.find(["script", "ins"]):
                continue
            candidate = candidate_row.get_text(" ", strip=True)
            if not candidate:
                continue
            if candidate.startswith("<< Previous") or _SAID_RE.match(candidate):
                break
            body = candidate
            break

        if body:
            comments.append(
                Comment(
                    author=match.group("author").strip(),
                    posted_at=match.group("date").strip(),
                    text=body,
                )
            )

    return comments


def list_thread_urls(discussion_url: str) -> list[str]:
    """Fetch a model family's discussion page and return its thread URLs,
    newest first — one request. Lets callers resume at thread granularity."""
    response = http.get(discussion_url)
    return _thread_urls(response.content)


def fetch_thread_comments(thread_url: str) -> list[Comment]:
    """Fetch one thread's comments — one request."""
    response = http.get(thread_url)
    return _comments_from_thread(response.content)


def fetch_discussion_comments(discussion_url: str, max_threads: int | None = None) -> list[Comment]:
    """Fetch every comment across every thread linked from a model's
    discussion page. Callers should cache by discussion_url since it's
    shared across all model-years of the same model. max_threads caps the
    crawl on very deep forums (hundreds of threads on Gold Wing-class
    models) — threads are listed newest-first, so the cap keeps the most
    recent discussion."""
    discussion_response = http.get(discussion_url)
    comments: list[Comment] = []

    thread_urls = _thread_urls(discussion_response.content)
    if max_threads is not None:
        thread_urls = thread_urls[:max_threads]

    for thread_url in thread_urls:
        thread_response = http.get(thread_url)
        comments.extend(_comments_from_thread(thread_response.content))

    return comments

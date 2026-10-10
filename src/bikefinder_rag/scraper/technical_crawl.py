"""A durable technical-only crawl, deliberately separate from the legacy DB.

SQLite is the canonical result/queue store. An interrupted write cannot leave
a URL marked successful without its data. Cached snapshots contain only the
technical DOM returned by the parser, never owner comments or full HTML.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import requests

BASE_URL = "https://www.motoplanete.com"
USER_AGENT = (
    "bikefinder-rag-project/0.2 "
    "(non-commercial local technical RAG; "
    "https://github.com/maax6/bikefinder-rag)"
)
MIN_DELAY_SECONDS = 10.0
SCHEMA_VERSION = "technical-source-v1"
PARSER_VERSION = "motoplanete-technical-v1"
FICHE_PATH = re.compile(r"^/[^/]+/\d+/[^/]+-(\d{4})/contact\.html$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def validate_url(url: str, *, fiche: bool = False) -> str:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc != "www.motoplanete.com"
            or parts.query or parts.fragment or parts.username):
        raise ValueError("Only canonical HTTPS Motoplanete URLs are supported")
    if fiche and not FICHE_PATH.fullmatch(parts.path):
        raise ValueError("Not a Motoplanete technical fiche URL")
    return url


class AccessRules:
    """The site's wildcard path rules, with longest match and Allow ties.

    Unlike urllib.robotparser, this handles '*' and trailing '$'. Source terms
    are reviewed independently; an allowed robots path is not a reuse licence.
    """

    def __init__(self, text: str):
        groups: list[tuple[list[str], list[tuple[str, str]]]] = []
        agents: list[str] = []
        directives: list[tuple[str, str]] = []
        for raw in text.splitlines() + ["User-agent: __end__"]:
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if directives:
                    groups.append((agents, directives))
                    agents, directives = [], []
                agents.append(value.lower())
            elif agents and key in {"allow", "disallow", "crawl-delay"}:
                directives.append((key, value))
        token = USER_AGENT.split("/", 1)[0].lower()
        specific = [(a, d) for a, d in groups if any(x != "*" and x in token for x in a)]
        matching = specific or [(a, d) for a, d in groups if "*" in a]
        if not matching:
            raise ValueError("No applicable robots group; access needs review")
        self.paths = []
        self.delay = MIN_DELAY_SECONDS
        for _, directives in matching:
            for key, value in directives:
                if key == "crawl-delay":
                    delay = float(value)
                    if not math.isfinite(delay) or delay < 0:
                        raise ValueError("Invalid crawl-delay")
                    self.delay = max(self.delay, delay)
                elif value:
                    anchored = value.endswith("$")
                    pattern = value[:-1] if anchored else value
                    regex = "^" + re.escape(pattern).replace(r"\*", ".*") + ("$" if anchored else "")
                    self.paths.append((re.compile(regex), len(pattern.replace("*", "")), key == "allow"))

    def allows(self, url: str) -> bool:
        path = urlsplit(url).path
        matches = [(length, allow) for regex, length, allow in self.paths if regex.search(path)]
        return max(matches, default=(0, True))[1]


class SourceBusy(RuntimeError):
    def __init__(self, status: int, retry_after: float):
        super().__init__(f"Source returned HTTP {status}; retry after {retry_after:g}s")
        self.status = status
        self.retry_after = retry_after


class SourceDenied(RuntimeError):
    pass


class HostAccessState:
    """Shared timing across output directories, protected by the CLI host lock."""

    def __init__(self, path: Path):
        self.path = path
        self.values = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(self.values, dict) or any(
                not isinstance(value, (float, int)) or not math.isfinite(value)
                for value in self.values.values()):
            raise SourceDenied("Invalid persisted host access state; inspect before resuming")

    def _save(self):
        atomic_text(self.path, json.dumps(self.values) + "\n")

    def touch_request(self):
        self.values["last_request"] = time.time()
        self._save()

    def request_wait(self, delay):
        delay = max(delay, self.values.get("required_delay", 0))
        return max(0.0, delay - (time.time() - self.values.get("last_request", 0)))

    def require_delay(self, delay):
        self.values["required_delay"] = delay
        self._save()

    def cooldown(self, seconds):
        self.values["cooldown_until"] = max(self.values.get("cooldown_until", 0), time.time()+seconds)
        self._save()

    def cooldown_remaining(self):
        return max(0.0, self.values.get("cooldown_until", 0) - time.time())


class PoliteClient:
    def __init__(self, delay: float = MIN_DELAY_SECONDS, *, session=None, sleep=time.sleep, clock=time.monotonic, store=None):
        if not math.isfinite(delay) or delay < MIN_DELAY_SECONDS:
            raise ValueError("Motoplanete delay must be finite and at least 10 seconds")
        self.delay = delay
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.sleep, self.clock = sleep, clock
        self.last_request = None
        self.rules: AccessRules | None = None
        self.store = store

    def _request(self, url: str):
        validate_url(url)
        wait = 0.0
        if self.last_request is not None:
            wait = max(wait, self.delay - (self.clock() - self.last_request))
        if self.store:
            cooldown = self.store.cooldown_remaining()
            if cooldown > 0:
                raise SourceBusy(429, cooldown)
            wait = max(wait, self.store.request_wait(self.delay))
        if wait > 0:
            self.sleep(wait)
        try:
            response = self.session.get(url, timeout=(10, 30), allow_redirects=False)
        finally:
            self.last_request = self.clock()
            if self.store:
                self.store.touch_request()
        if len(response.content) > 8 * 1024 * 1024:
            raise ValueError("Unexpected response larger than 8 MiB")
        if response.status_code == 429 or response.status_code >= 500:
            retry = 60.0
            value = response.headers.get("Retry-After", "")
            try:
                retry = max(retry, float(value))
            except ValueError:
                try:
                    retry = max(retry, parsedate_to_datetime(value).timestamp() - time.time())
                except (TypeError, ValueError, OverflowError):
                    pass
            if not math.isfinite(retry):
                retry = 60.0
            if self.store:
                self.store.cooldown(retry)
            raise SourceBusy(response.status_code, retry)
        return response

    def check_access(self, out_dir: Path) -> dict:
        response = self._request(BASE_URL + "/robots.txt")
        if response.status_code != 200 or "user-agent:" not in response.text.lower():
            raise SourceDenied("robots.txt unavailable or invalid; no fiche requests made")
        self.rules = AccessRules(response.text)
        self.delay = max(self.delay, self.rules.delay)
        if self.store and hasattr(self.store, "require_delay"):
            self.store.require_delay(self.delay)
        atomic_text(out_dir / "robots.txt", response.text)
        metadata = {
            "checked_at": utc_now(), "url": BASE_URL + "/robots.txt",
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "delay_seconds": self.delay, "user_agent": USER_AGENT,
            "terms_url": BASE_URL + "/article/41/Conditions-Generales-dUtilisation/page.html",
            "terms_reviewed_on": "2026-10-10",
            "use": "Non-commercial local POC; no dataset redistribution licence asserted",
        }
        atomic_text(out_dir / "access.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        return metadata

    def get(self, url: str):
        validate_url(url)
        if self.rules is None:
            raise SourceDenied("Check source access before requesting content")
        for _ in range(4):
            if not self.rules.allows(url):
                raise SourceDenied("Path excluded by the current robots.txt")
            response = self._request(url)
            if response.status_code not in {301, 302, 303, 307, 308}:
                if response.status_code in {401, 403}:
                    raise SourceDenied(f"HTTP {response.status_code}; no bypass attempted")
                return response, url
            url = validate_url(urljoin(url, response.headers.get("Location", "")))
        raise SourceDenied("Too many redirects")


def discover_fiches(client: PoliteClient) -> list[str]:
    """Only published fiche sitemaps, one sequential request per delay."""
    queue = [BASE_URL + "/sitemap_moto.php"]
    visited, fiches = set(), []
    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        if len(visited) >= 100:
            raise ValueError("Unexpected sitemap index size")
        visited.add(url)
        response, _ = client.get(url)
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        is_index = root.tag.rsplit("}", 1)[-1] == "sitemapindex"
        if root.tag.rsplit("}", 1)[-1] not in {"sitemapindex", "urlset"}:
            raise ValueError("Unexpected sitemap document")
        # Image sitemaps also contain image:loc descendants, often on other
        # hosts. Only direct sitemap/url entry locs are discovery resources.
        for entry in root:
            expected = "sitemap" if is_index else "url"
            if entry.tag.rsplit("}", 1)[-1] != expected:
                continue
            nodes = [node for node in entry if node.tag.rsplit("}", 1)[-1] == "loc"]
            if len(nodes) != 1 or not nodes[0].text:
                raise ValueError("Sitemap entry must have exactly one direct loc")
            loc = validate_url(nodes[0].text.strip())
            if is_index:
                if "sitemap" not in urlsplit(loc).path:
                    raise ValueError("Unexpected sitemap child")
                queue.append(loc)
            elif FICHE_PATH.fullmatch(urlsplit(loc).path):
                fiches.append(loc)
    if not fiches:
        raise ValueError("Empty fiche discovery; previous manifest retained")
    return list(dict.fromkeys(fiches))


class CrawlStore:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "snapshots").mkdir(exist_ok=True)
        self.conn = sqlite3.connect(out_dir / "crawl.sqlite3")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS pages (
            url TEXT PRIMARY KEY, ordinal INTEGER NOT NULL, year INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT, status INTEGER, error TEXT, retry_at REAL DEFAULT 0,
            parser_version TEXT, result TEXT)""")
        self.conn.execute("CREATE TABLE IF NOT EXISTS source_state(key TEXT PRIMARY KEY, value REAL NOT NULL)")
        self.conn.commit()

    def _state(self, key: str) -> float:
        row = self.conn.execute("SELECT value FROM source_state WHERE key=?", (key,)).fetchone()
        return row[0] if row else 0.0

    def _set_state(self, key: str, value: float) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO source_state(key,value) VALUES (?,?)", (key, value))

    def touch_request(self) -> None:
        self._set_state("last_request", time.time())

    def request_wait(self, delay: float) -> float:
        last = self._state("last_request")
        if not last:
            # Preserve spacing when opening a manifest created by the pilot.
            row = self.conn.execute("SELECT max(updated_at) FROM pages").fetchone()
            if row[0]:
                last = datetime.fromisoformat(row[0]).timestamp()
        return max(0.0, delay - (time.time() - last))

    def cooldown(self, seconds: float) -> None:
        self._set_state("cooldown_until", max(self._state("cooldown_until"), time.time()+seconds))

    def cooldown_remaining(self) -> float:
        return max(0.0, self._state("cooldown_until") - time.time())

    def seed(self, urls: list[str]) -> None:
        next_ordinal = self.conn.execute("SELECT coalesce(max(ordinal), -1)+1 FROM pages").fetchone()[0]
        with self.conn:
            for i, url in enumerate(dict.fromkeys(urls)):
                validate_url(url, fiche=True)
                year = int(FICHE_PATH.fullmatch(urlsplit(url).path).group(1))
                state = "quarantined" if year < 1800 or year > datetime.now().year + 2 else "pending"
                self.conn.execute("INSERT OR IGNORE INTO pages(url,ordinal,year,state) VALUES (?,?,?,?)",
                                  (url, next_ordinal+i, year, state))

    def todo(self) -> list[str]:
        return [row[0] for row in self.conn.execute(
            """SELECT url FROM pages WHERE state IN ('pending','retryable')
               AND retry_at <= ? ORDER BY ordinal""", (time.time(),))]

    def has_pages(self) -> bool:
        return self.conn.execute("SELECT 1 FROM pages LIMIT 1").fetchone() is not None

    def record_error(self, url: str, state: str, error: str, status=None, retry_after=0) -> None:
        with self.conn:
            self.conn.execute("""UPDATE pages SET state=?,attempts=attempts+1,updated_at=?,
                status=?,error=?,retry_at=? WHERE url=?""",
                (state, utc_now(), status, error[:1000], time.time()+retry_after, url))

    def record_success(self, url: str, row: dict, response, resolved_url: str) -> str:
        row = dict(row)
        identity = row.get("identity", {})
        original_parts = urlsplit(url).path.split("/")
        resolved_parts = urlsplit(resolved_url).path.split("/")
        original_year = int(FICHE_PATH.fullmatch(urlsplit(url).path).group(1))
        resolved_year = int(FICHE_PATH.fullmatch(urlsplit(resolved_url).path).group(1))
        review_reasons = []
        if original_parts[2] != resolved_parts[2] or original_year != resolved_year:
            review_reasons.append("redirect_changed_fiche_or_year")
        if identity.get("year") != resolved_year:
            review_reasons.append("documented_year_conflicts_with_url")
        state = "needs_review" if review_reasons else "success"
        snapshot = row.pop("technical_snapshot")
        path = Path("snapshots") / (hashlib.sha256(url.encode()).hexdigest() + ".html")
        atomic_text(self.out_dir / path, snapshot)
        row["collection"] = {
            "requested_url": url, "resolved_url": resolved_url, "collected_at": utc_now(),
            "http_status": response.status_code, "response_sha256": hashlib.sha256(response.content).hexdigest(),
            "technical_snapshot": str(path), "snapshot_sha256": hashlib.sha256(snapshot.encode()).hexdigest(),
            "schema_version": SCHEMA_VERSION, "parser_version": PARSER_VERSION,
            "identity_review_reasons": review_reasons,
        }
        serialized = json.dumps(row, ensure_ascii=False)
        with self.conn:
            self.conn.execute("""UPDATE pages SET state=?, attempts=attempts+1,
                updated_at=?,status=?,error=NULL,retry_at=0,parser_version=?,result=? WHERE url=?""",
                (state, row["collection"]["collected_at"], response.status_code, PARSER_VERSION, serialized, url))
        return state

    def report(self, *, running=False) -> dict:
        states = dict(self.conn.execute("SELECT state,count(*) FROM pages GROUP BY state"))
        year_rows = self.conn.execute("SELECT year,state,count(*) FROM pages GROUP BY year,state ORDER BY year")
        by_year = {}
        for year, state, count in year_rows:
            by_year.setdefault(str(year), {})[state] = count
        report = {
            "updated_at": utc_now(), "running": running, "source": "motoplanete",
            "parser_version": PARSER_VERSION, "states": states, "discovered": sum(states.values()),
            "by_year": by_year, "scope": "Published technical fiches, all brands/categories; source coverage only",
            "market": "Per-field evidence only; French price is not proof of every technical variant's market",
            "equipment": "Raw supporting text preserved; mention does not establish standard/optional/absent",
            "source_cooldown_until": self._state("cooldown_until") or None,
        }
        atomic_text(self.out_dir / "status.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return report

    def export(self) -> None:
        for name, state in (("records.jsonl", "success"), ("review_records.jsonl", "needs_review")):
            temporary = self.out_dir / (name + ".tmp")
            with temporary.open("w", encoding="utf-8") as out:
                for row in self.conn.execute("SELECT result FROM pages WHERE state=? ORDER BY ordinal", (state,)):
                    out.write(row[0] + "\n")
            temporary.replace(self.out_dir / name)

    def close(self) -> None:
        self.conn.close()


def crawl(store: CrawlStore, client: PoliteClient, parse, *, limit: int | None = 20) -> dict:
    if limit is not None and limit < 0:
        raise ValueError("Page limit must be non-negative")
    attempted = succeeded = consecutive_errors = 0
    halted = None
    try:
        store.report(running=True)
        cooldown = store.cooldown_remaining()
        if cooldown > 0:
            halted = f"Source cooldown still active for {cooldown:.0f}s"
        for url in [] if halted else store.todo():
            if limit is not None and attempted >= limit:
                break
            attempted += 1
            try:
                response, resolved_url = client.get(url)
                validate_url(resolved_url, fiche=True)
                if response.status_code in {404, 410}:
                    store.record_error(url, "terminal", f"HTTP {response.status_code}", response.status_code)
                    continue
                response.raise_for_status()
                row = parse(resolved_url, response.content)
                if not row.get("spec_rows") or not row.get("technical_snapshot"):
                    raise ValueError("Empty technical extraction")
                state = store.record_success(url, row, response, resolved_url)
                succeeded += state == "success"
                consecutive_errors = 0
                if succeeded % 25 == 0:
                    store.export()
            except SourceBusy as exc:
                store.cooldown(exc.retry_after)
                store.record_error(url, "retryable", str(exc), exc.status, exc.retry_after)
                halted = str(exc)
                break
            except SourceDenied as exc:
                store.record_error(url, "blocked", str(exc))
                halted = str(exc)
                break
            except (requests.RequestException, ValueError) as exc:
                store.record_error(url, "retryable", str(exc), retry_after=60)
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    halted = "Three consecutive network/extraction errors; inspect before resuming"
                    break
            report = store.report(running=True)
            print(json.dumps({"attempted": attempted, "succeeded": succeeded, "states": report["states"]}), flush=True)
    finally:
        store.export()
        report = store.report(running=False)
    report.update({"attempted_this_run": attempted, "succeeded_this_run": succeeded, "halted": halted})
    atomic_text(store.out_dir / "last_run.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report

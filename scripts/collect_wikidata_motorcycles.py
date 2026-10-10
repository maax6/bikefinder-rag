#!/usr/bin/env python3
"""Collect a bounded CC0 motorcycle identity inventory from Wikidata.

This discovers classified entities, not every motorcycle ever made. It does
not infer model years, equipment, markets, or specifications. Responses and
queries are cached so --resume does not refetch successful pages. Later pages
can observe a changed Wikidata graph; this is not a transactional snapshot.

    .venv/bin/python scripts/collect_wikidata_motorcycles.py --max-pages 20
    .venv/bin/python scripts/collect_wikidata_motorcycles.py --resume --max-pages 40

HTTP/API errors stop collection, retaining successful pages. Retry-After and
maxlag set a persisted earliest retry time; no automatic retry floods occur.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

import requests

ENDPOINT = "https://query.wikidata.org/sparql"
ROOTS = ("Q34493", "Q23866334")
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
METHOD_VERSION = "wikidata-motorcycle-inventory-v1"
LOCK_FILENAME = ".collector.lock"
USER_AGENT = (
    "BikefinderRAG-inventory/0.1 "
    "(non-commercial motorcycle catalogue research; "
    "https://github.com/maax6/bikefinder-rag)"
)
ENTITY_RE = re.compile(r"https?://www\.wikidata\.org/entity/(Q[1-9][0-9]*)\Z")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def qid(binding: dict, field: str) -> str:
    value = binding.get(field, {})
    match = ENTITY_RE.fullmatch(value.get("value", ""))
    if value.get("type") != "uri" or not match:
        raise ValueError(f"Invalid Wikidata entity binding: {field}")
    return match.group(1)


def bindings(payload: dict) -> list[dict]:
    if not isinstance(payload, dict) or "error" in payload:
        raise ValueError("Response contains an API error or is not an object")
    results = payload.get("results")
    rows = results.get("bindings") if isinstance(results, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Response has no valid SPARQL result bindings")
    return rows


def class_query(class_limit: int) -> str:
    roots = " ".join("wd:" + root for root in ROOTS)
    # One extra row identifies a truncated class discovery without COUNT joins.
    return (
        "SELECT DISTINCT ?class ?root WHERE { "
        f"VALUES ?root {{ {roots} }} ?class wdt:P279* ?root . "
        "} ORDER BY ?root ?class " + f"LIMIT {class_limit + 1}"
    )


def inventory_query(classes: list[str], page_size: int, offset: int) -> str:
    values = " ".join("wd:" + item for item in classes)
    return (
        "SELECT DISTINCT ?item ?class ?label_fr ?label_en WHERE { "
        f"VALUES ?class {{ {values} }} ?item wdt:P31 ?class . "
        "OPTIONAL { ?item rdfs:label ?label_fr . FILTER(LANG(?label_fr) = 'fr') } "
        "OPTIONAL { ?item rdfs:label ?label_en . FILTER(LANG(?label_en) = 'en') } "
        "} ORDER BY ?item ?class " + f"LIMIT {page_size} OFFSET {offset}"
    )


def retry_delay(header: str | None, now: datetime) -> float | None:
    if not header:
        return None
    try:
        seconds = float(header)
        return max(0, seconds) if math.isfinite(seconds) else None
    except ValueError:
        try:
            deadline = parsedate_to_datetime(header)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            return max(0, (deadline - now).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return None


class CollectionStopped(Exception):
    def __init__(self, message: str, capture: dict | None = None):
        super().__init__(message)
        self.capture = capture


class QueryClient:
    def __init__(self, out: Path, *, delay: float, timeout: float,
                 session=None, sleep=time.sleep, monotonic=time.monotonic):
        self.cache = out / "responses"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.blocked_path = out / "retry_after.json"
        self.delay, self.timeout = delay, timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT,
                                     "Accept": "application/sparql-results+json",
                                     "Accept-Encoding": "gzip,deflate"})
        self.sleep, self.monotonic = sleep, monotonic
        self.last_request_at: float | None = None
        self.network_requests = 0
        self.cache_hits = 0

    def check_retry_time(self) -> None:
        if self.blocked_path.exists():
            blocked = json.loads(self.blocked_path.read_text())
            deadline = datetime.fromisoformat(blocked["not_before_utc"])
            if datetime.now(timezone.utc) < deadline:
                raise CollectionStopped("Server backoff remains active", blocked)

    def stop(self, capture: dict, message: str, delay: float | None = None):
        capture["error"] = message
        if delay is not None:
            capture["retry_after_seconds"] = delay
            capture["not_before_utc"] = (
                datetime.now(timezone.utc) + timedelta(seconds=delay)
            ).isoformat()
            write_json(self.blocked_path, capture)
        failure_path = self.cache / (capture["query_sha256"] + ".failed.json")
        write_json(failure_path, capture)
        raise CollectionStopped(message, capture)

    def get(self, query: str) -> tuple[dict, dict]:
        query_sha = digest(query)
        cache_path = self.cache / (query_sha + ".json")
        if cache_path.exists():
            capture = json.loads(cache_path.read_text())
            if (capture.get("query") != query
                    or capture.get("query_sha256") != query_sha
                    or capture.get("http_status") != 200
                    or capture.get("response_sha256") != digest(capture.get("response_text", ""))):
                raise CollectionStopped("Invalid cached response integrity")
            try:
                payload = json.loads(capture["response_text"])
                bindings(payload)
            except (ValueError, TypeError, KeyError) as exc:
                raise CollectionStopped("Invalid cached SPARQL payload") from exc
            self.cache_hits += 1
            return payload, capture

        self.check_retry_time()
        if self.last_request_at is not None:
            remaining = self.delay - (self.monotonic() - self.last_request_at)
            if remaining > 0:
                self.sleep(remaining)
        capture = {"query": query, "query_sha256": query_sha,
                   "endpoint": ENDPOINT, "requested_at": utc_now()}
        self.network_requests += 1
        try:
            response = self.session.get(ENDPOINT, params={"query": query, "format": "json"},
                                        timeout=self.timeout)
        except requests.RequestException as exc:
            self.last_request_at = self.monotonic()
            self.stop(capture, f"Transport error: {type(exc).__name__}", 60)
        self.last_request_at = self.monotonic()
        capture.update({"received_at": utc_now(), "request_url": response.url,
                        "http_status": response.status_code,
                        "content_type": response.headers.get("Content-Type"),
                        "retry_after": response.headers.get("Retry-After"),
                        "response_text": response.text,
                        "response_sha256": digest(response.text)})
        delay = retry_delay(capture["retry_after"], datetime.now(timezone.utc))
        if response.status_code != 200:
            if response.status_code == 429 or response.status_code >= 500:
                delay = 60 if delay is None else delay
            self.stop(capture, f"HTTP {response.status_code}", delay)
        try:
            payload = response.json()
        except ValueError:
            self.stop(capture, "Response is not valid JSON", delay)
        if isinstance(payload, dict) and "error" in payload:
            error = payload["error"]
            code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
            if code == "maxlag":
                delay = 60 if delay is None else delay
            self.stop(capture, f"API error: {code}", delay)
        try:
            bindings(payload)
        except (ValueError, TypeError, AttributeError):
            self.stop(capture, "Response has invalid SPARQL bindings", delay)
        write_json(cache_path, capture)
        return payload, capture


def merge_page(inventory: dict[str, dict], rows: list[dict], capture: dict,
               classes: set[str]) -> None:
    # Validate a whole page before accepting any of it.
    validated = []
    for row in rows:
        item, observed_class = qid(row, "item"), qid(row, "class")
        if observed_class not in classes:
            raise ValueError("Result contains a class outside the query")
        labels = {}
        for language in ("fr", "en"):
            label = row.get("label_" + language)
            if label is not None:
                if (label.get("type") != "literal" or label.get("xml:lang") != language
                        or not isinstance(label.get("value"), str)):
                    raise ValueError("Invalid language label binding")
                labels[language] = label["value"]
        validated.append((item, observed_class, labels))
    evidence = {key: capture[key] for key in
                ("query_sha256", "received_at", "request_url", "response_sha256")}
    for item, observed_class, labels in validated:
        record = inventory.setdefault(item, {
            "qid": item, "source": "wikidata", "license": "CC0-1.0",
            "license_url": LICENSE_URL, "source_url": f"https://www.wikidata.org/wiki/{item}",
            "labels": {}, "observed_instance_of": [], "discovery_evidence": [],
            "record_kind": "classified_entity_identity", "method_version": METHOD_VERSION,
        })
        record["labels"].update(labels)
        if observed_class not in record["observed_instance_of"]:
            record["observed_instance_of"].append(observed_class)
            record["observed_instance_of"].sort()
        if evidence not in record["discovery_evidence"]:
            record["discovery_evidence"].append(evidence)


def export_inventory(path: Path, inventory: dict[str, dict]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        for item in sorted(inventory):
            stream.write(json.dumps(inventory[item], ensure_ascii=False) + "\n")
    temporary.replace(path)


def collect(out: Path, report_path: Path, *, resume: bool = False, page_size: int = 500,
            max_pages: int = 20, class_limit: int = 100, delay: float = 2,
            timeout: float = 30, session=None, sleep=time.sleep) -> dict:
    if not 1 <= page_size <= 1000 or max_pages < 1 or not 2 <= class_limit <= 1000:
        raise ValueError("page_size must be 1..1000, max_pages positive, class_limit 2..1000")
    if not math.isfinite(delay) or delay < 2 or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError("delay must be at least 2 seconds and timeout must be 0..60 seconds")
    out.mkdir(parents=True, exist_ok=True)
    # Keep the lock inode permanently. Unlinking after release could let another
    # process open a new inode while a waiting process still owns the old one.
    with (out / LOCK_FILENAME).open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another collector is already writing this output directory") from exc
        try:
            return _collect_locked(out, report_path, resume=resume, page_size=page_size,
                                   max_pages=max_pages, class_limit=class_limit, delay=delay,
                                   timeout=timeout, session=session, sleep=sleep)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _collect_locked(out: Path, report_path: Path, *, resume: bool, page_size: int,
                    max_pages: int, class_limit: int, delay: float,
                    timeout: float, session, sleep) -> dict:
    manifest_path = out / "manifest.json"
    method = {"method_version": METHOD_VERSION, "roots": list(ROOTS),
              "page_size": page_size, "class_limit": class_limit, "endpoint": ENDPOINT}
    if manifest_path.exists():
        if not resume:
            raise ValueError("Output already exists; use --resume or a new --out directory")
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("method") != method:
            raise ValueError("Resume method differs from cached discovery; use a new directory")
    else:
        if any(path.name != LOCK_FILENAME for path in out.iterdir()):
            raise ValueError("Output directory contains data without a compatible manifest")
        manifest = {"created_at": utc_now(), "method": method}
        write_json(manifest_path, manifest)
    client = QueryClient(out, delay=delay, timeout=timeout, session=session, sleep=sleep)
    inventory: dict[str, dict] = {}
    inventory_path = out / "inventory.jsonl"
    if resume and inventory_path.exists():
        for line in inventory_path.read_text().splitlines():
            record = json.loads(line)
            if (not isinstance(record, dict) or record.get("method_version") != METHOD_VERSION
                    or not re.fullmatch(r"Q[1-9][0-9]*", record.get("qid", ""))):
                raise ValueError("Existing inventory has an incompatible record")
            inventory[record["qid"]] = record
    previous_entities = set(inventory)
    seen_this_run: set[str] = set()
    report = {"started_at": utc_now(), "collection_started_at": manifest["created_at"],
              "collector_source_sha256": digest(Path(__file__).read_text()),
              "method": method, "status": "running", "exhaustive_world_catalogue": False,
              "coverage_note": "Only entities classified under the queried Wikidata classes are discovered; "
              "the entity query uses direct P31 matches, so models described only through P279 can be absent. "
              "Generic vehicle types can also be present. Missing classifications, models and aliases remain "
              "possible. No model year, equipment, "
              "market or technical specification is inferred. Cached pages and later live pages can observe "
              "different graph revisions; pagination is not a transactional snapshot.",
              "classes": [], "class_discovery_truncated": False,
              "pages": [], "inventory_path": str(out / "inventory.jsonl"),
              "license": "CC0-1.0", "license_url": LICENSE_URL}
    total_rows = 0
    try:
        payload, capture = client.get(class_query(class_limit))
        class_rows = bindings(payload)
        discovered = []
        for row in class_rows:
            if qid(row, "root") not in ROOTS:
                raise ValueError("Unexpected root in class discovery")
            discovered.append(qid(row, "class"))
        report["class_discovery_truncated"] = len(class_rows) > class_limit
        # Explicit roots remain included even if bounded subclass discovery is truncated.
        classes = sorted(set(ROOTS).union(discovered[:class_limit]))
        report["classes"] = classes
        report["class_discovery_query_sha256"] = capture["query_sha256"]
        for page in range(max_pages):
            query = inventory_query(classes, page_size, page * page_size)
            payload, capture = client.get(query)
            rows = bindings(payload)
            merge_page(inventory, rows, capture, set(classes))
            seen_this_run.update(qid(row, "item") for row in rows)
            total_rows += len(rows)
            report["pages"].append({"index": page, "offset": page * page_size,
                                    "rows": len(rows), "query_sha256": capture["query_sha256"],
                                    "received_at": capture["received_at"], "http_status": capture["http_status"]})
            export_inventory(out / "inventory.jsonl", inventory)
            print(f"page {page + 1}: {len(rows)} bindings; {len(inventory)} unique entities", file=sys.stderr)
            if len(rows) < page_size:
                report["status"] = "classified_query_complete"
                break
        else:
            report["status"] = "page_limit_reached"
    except CollectionStopped as exc:
        report["status"] = "stopped_on_source_error"
        report["error"] = str(exc)
        if exc.capture:
            report["failed_request"] = {key: value for key, value in exc.capture.items()
                                        if key not in ("response_text", "query")}
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        report["status"] = "stopped_on_validation_error"
        report["error"] = str(exc)
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        report["error"] = "Interrupted by operator; successful pages remain cached"
    finally:
        report.update({"finished_at": utc_now(), "bindings_collected": total_rows,
                       "unique_entities": len(inventory),
                       "previous_inventory_entities": len(previous_entities),
                       "new_entities_this_run": len(set(inventory) - previous_entities),
                       "unique_entities_seen_this_run": len(seen_this_run),
                       "duplicate_bindings_merged": total_rows - len(seen_this_run),
                       "network_requests_this_run": client.network_requests, "cache_hits_this_run": client.cache_hits,
                       "successful_responses_cached": sum(
                           not path.name.endswith(".failed.json") for path in client.cache.glob("*.json")),
                       "entities_with_fr_label": sum("fr" in row["labels"] for row in inventory.values()),
                       "entities_with_en_label": sum("en" in row["labels"] for row in inventory.values())})
        # Preserve an earlier complete inventory if a resumed run fails before accepting its first page.
        if inventory or not (out / "inventory.jsonl").exists():
            export_inventory(out / "inventory.jsonl", inventory)
        write_json(report_path, report)
        if hasattr(client.session, "close"):
            client.session.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/technical/wikidata"))
    parser.add_argument("--report", type=Path, default=Path("eval_results/technical/wikidata_inventory_20261010.json"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--class-limit", type=int, default=100)
    parser.add_argument("--delay", type=float, default=2)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    try:
        report = collect(args.out, args.report, resume=args.resume, page_size=args.page_size,
                         max_pages=args.max_pages, class_limit=args.class_limit,
                         delay=args.delay, timeout=args.timeout)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({key: report[key] for key in ("status", "unique_entities", "network_requests_this_run")},
                     ensure_ascii=False))
    if report["status"] == "interrupted":
        return 130
    return 2 if report["status"].startswith("stopped") else 0


if __name__ == "__main__":
    raise SystemExit(main())

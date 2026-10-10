"""Collector contract tests use synthetic SPARQL responses, without network."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
import requests


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "collect_wikidata_motorcycles.py"
SPEC = importlib.util.spec_from_file_location("collect_wikidata_motorcycles", MODULE_PATH)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def entity(value):
    return {"type": "uri", "value": f"http://www.wikidata.org/entity/{value}"}


def label(value, language):
    return {"type": "literal", "xml:lang": language, "value": value}


def results(rows):
    return {"head": {"vars": []}, "results": {"bindings": rows}}


def classes():
    return results([{"root": entity(root), "class": entity(root)} for root in collector.ROOTS])


def bike(item="Q796523", class_id="Q23866334", name="BMW K 100 RS"):
    return {"item": entity(item), "class": entity(class_id), "label_en": label(name, "en")}


def response(payload, status=200, headers=None, raw=None):
    body = json.dumps(payload) if raw is None else raw
    return SimpleNamespace(status_code=status, text=body, headers=headers or {},
                           url="https://query.wikidata.org/sparql?query=test",
                           json=lambda: json.loads(body))


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected network request")
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def close(self):
        pass


def run(tmp_path, responses, **kwargs):
    session = Session(responses)
    report = collector.collect(tmp_path / "out", tmp_path / "report.json",
                               session=session, sleep=lambda seconds: None, **kwargs)
    return report, session


def records(tmp_path):
    return [json.loads(line) for line in (tmp_path / "out" / "inventory.jsonl").read_text().splitlines()]


def test_deduplicates_across_pages_and_retains_provenance_without_year_or_abs(tmp_path):
    first = bike(name="BMW 1991 ABS")
    second = bike(class_id="Q34493")
    second["label_fr"] = label("BMW K 100 RS", "fr")
    report, session = run(tmp_path, [response(classes()), response(results([first])),
                                   response(results([second])), response(results([]))],
                          page_size=1, max_pages=3)

    record, = records(tmp_path)
    assert report["status"] == "classified_query_complete"
    assert report["unique_entities"] == 1 and report["duplicate_bindings_merged"] == 1
    assert record["observed_instance_of"] == ["Q23866334", "Q34493"]
    assert record["labels"]["fr"] == "BMW K 100 RS"
    assert record["license"] == "CC0-1.0"
    assert record["source_url"] == "https://www.wikidata.org/wiki/Q796523"
    assert len(record["discovery_evidence"]) == 2
    assert all(len(evidence["query_sha256"]) == 64 and evidence["received_at"]
               for evidence in record["discovery_evidence"])
    assert "year" not in record and "abs" not in record and "equipment" not in record
    assert len(session.calls) == 4 and not report["exhaustive_world_catalogue"]


def test_resume_reuses_verified_cache_and_fetches_only_new_pages(tmp_path):
    first, _ = run(tmp_path, [response(classes()), response(results([bike()]))],
                   page_size=1, max_pages=1)
    second, session = run(tmp_path, [response(results([bike("Q2", name="Other")]))],
                          resume=True, page_size=1, max_pages=2)

    assert first["status"] == second["status"] == "page_limit_reached"
    assert second["unique_entities"] == 2 and second["new_entities_this_run"] == 1
    assert second["cache_hits_this_run"] == 2 and len(session.calls) == 1
    assert "OFFSET 1" in session.calls[0][1]["params"]["query"]


def test_cache_body_corruption_stops_without_network_or_losing_existing_inventory(tmp_path):
    run(tmp_path, [response(classes()), response(results([bike()]))], page_size=1, max_pages=1)
    path = next(path for path in (tmp_path / "out" / "responses").glob("*.json")
                if "SELECT DISTINCT ?class" in json.loads(path.read_text())["query"])
    cached = json.loads(path.read_text())
    cached["response_text"] += " "
    path.write_text(json.dumps(cached))
    report, session = run(tmp_path, [], resume=True, page_size=1, max_pages=2)

    assert report["status"] == "stopped_on_source_error"
    assert report["error"] == "Invalid cached response integrity"
    assert report["unique_entities"] == 1 and len(records(tmp_path)) == 1
    assert not session.calls


def test_http_429_persists_retry_after_and_partial_result(tmp_path):
    report, _ = run(tmp_path, [response(classes()), response(results([bike()])),
                             response({"error": "busy"}, 429, {"Retry-After": "3600"})],
                    page_size=1, max_pages=2)

    assert report["status"] == "stopped_on_source_error" and report["unique_entities"] == 1
    assert report["failed_request"]["http_status"] == 429
    assert report["failed_request"]["retry_after_seconds"] == 3600
    assert "response_text" not in report["failed_request"]
    assert (tmp_path / "out" / "retry_after.json").exists()
    resumed, session = run(tmp_path, [], resume=True, page_size=1, max_pages=2)
    assert resumed["status"] == "stopped_on_source_error"
    assert resumed["error"] == "Server backoff remains active"
    assert resumed["unique_entities"] == 1 and not session.calls


@pytest.mark.parametrize("payload,expected", [
    ({"error": {"code": "maxlag"}}, "API error: maxlag"),
    ({"results": []}, "Response has invalid SPARQL bindings"),
    (["unexpected"], "Response has invalid SPARQL bindings"),
])
def test_http_200_requires_successful_sparql_payload(tmp_path, payload, expected):
    report, session = run(tmp_path, [response(payload)])
    assert report["status"] == "stopped_on_source_error" and report["error"] == expected
    assert report["unique_entities"] == 0 and len(session.calls) == 1
    assert not list((tmp_path / "out" / "responses").glob("[!.]*.json.tmp"))
    if expected == "API error: maxlag":
        assert report["failed_request"]["retry_after_seconds"] == 60


def test_timeout_is_saved_as_failure_not_success(tmp_path):
    report, _ = run(tmp_path, [requests.Timeout("timeout")])
    assert report["status"] == "stopped_on_source_error"
    assert report["failed_request"]["error"] == "Transport error: Timeout"
    assert list((tmp_path / "out" / "responses").glob("*.failed.json"))


def test_invalid_json_stops_and_preserves_raw_response_for_diagnosis(tmp_path):
    report, _ = run(tmp_path, [response(None, raw="<html>temporary server failure</html>")])
    assert report["status"] == "stopped_on_source_error"
    assert report["error"] == "Response is not valid JSON"
    failure, = (tmp_path / "out" / "responses").glob("*.failed.json")
    assert json.loads(failure.read_text())["response_text"].startswith("<html>")


def test_operator_interruption_retains_successful_pages_and_visible_status(tmp_path):
    report, _ = run(tmp_path, [response(classes()), response(results([bike()])), KeyboardInterrupt()],
                    page_size=1, max_pages=2)
    assert report["status"] == "interrupted"
    assert report["unique_entities"] == 1 and len(records(tmp_path)) == 1


def test_missing_labels_remain_missing_not_copied_from_qid(tmp_path):
    row = {"item": entity("Q2"), "class": entity("Q34493")}
    report, _ = run(tmp_path, [response(classes()), response(results([row]))])
    record, = records(tmp_path)
    assert record["labels"] == {}
    assert report["entities_with_fr_label"] == report["entities_with_en_label"] == 0


def test_subclasses_are_queried_and_truncation_remains_visible(tmp_path):
    subclass_rows = [{"root": entity("Q34493"), "class": entity(item)}
                     for item in ("Q10", "Q11", "Q12")]
    report, session = run(tmp_path, [response(results(subclass_rows)), response(results([bike(class_id="Q10")]))],
                          class_limit=2)
    assert report["class_discovery_truncated"]
    assert report["classes"] == ["Q10", "Q11", "Q23866334", "Q34493"]
    query = session.calls[1][1]["params"]["query"]
    assert "wd:Q10" in query and "wd:Q11" in query and "wd:Q12" not in query
    assert not report["exhaustive_world_catalogue"]


@pytest.mark.parametrize("bad", [
    {"item": {"type": "uri", "value": "https://example.org/entity/Q2"}, "class": entity("Q34493")},
    bike(class_id="Q99"),
    {**bike(), "label_fr": label("Wrong language", "en")},
])
def test_invalid_page_cannot_partially_add_records(tmp_path, bad):
    report, _ = run(tmp_path, [response(classes()), response(results([bike(), bad]))])
    assert report["status"] == "stopped_on_validation_error" and records(tmp_path) == []


def test_refuses_overwrite_and_incompatible_resume(tmp_path):
    run(tmp_path, [response(classes()), response(results([]))])
    with pytest.raises(ValueError, match="use --resume"):
        run(tmp_path, [])
    with pytest.raises(ValueError, match="Resume method differs"):
        run(tmp_path, [], resume=True, page_size=10)


@pytest.mark.parametrize("arguments", [
    {"delay": 1.9}, {"delay": float("nan")}, {"timeout": 61},
    {"timeout": 0}, {"page_size": 1001}, {"max_pages": 0},
])
def test_invalid_resource_bounds_fail_before_requests(tmp_path, arguments):
    with pytest.raises(ValueError):
        run(tmp_path, [], **arguments)


def test_polite_request_spacing_and_bounded_timeout(tmp_path):
    sleeps = []
    session = Session([response(classes()), response(results([]))])
    clock_values = iter([10, 10.25, 12.25])
    client = collector.QueryClient(tmp_path, delay=2, timeout=30, session=session,
                                   sleep=sleeps.append, monotonic=lambda: next(clock_values))
    client.get("classes")
    client.get("inventory")
    assert sleeps == [1.75]
    assert [call[1]["timeout"] for call in session.calls] == [30, 30]
    assert "BikefinderRAG" in session.headers["User-Agent"]


def test_retry_after_accepts_seconds_or_http_date():
    now = collector.datetime(2026, 10, 10, 10, 0, tzinfo=collector.timezone.utc)
    assert collector.retry_delay("5", now) == 5
    assert collector.retry_delay("Sat, 10 Oct 2026 10:01:00 GMT", now) == 60
    assert collector.retry_delay("not-a-date", now) is None


def test_second_process_cannot_replace_inventory_while_first_is_publishing(tmp_path):
    """Exercise a real cross-process race during the owner's final export."""
    owner_code = r'''
import importlib.util, json, sys, time
from pathlib import Path
from types import SimpleNamespace
spec = importlib.util.spec_from_file_location("collector", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
out, report, ready, release = map(Path, sys.argv[2:])
def entity(qid):
    return {"type": "uri", "value": "http://www.wikidata.org/entity/" + qid}
payloads = iter([
    {"results": {"bindings": [{"root": entity(root), "class": entity(root)} for root in module.ROOTS]}},
    {"results": {"bindings": [{"item": entity("Q2"), "class": entity("Q34493")}]}}
])
class Session:
    headers = {}
    def get(self, *args, **kwargs):
        payload = next(payloads)
        return SimpleNamespace(status_code=200, headers={}, text=json.dumps(payload),
                               url="https://query.wikidata.org/sparql?fixture", json=lambda: payload)
    def close(self):
        pass
original_export = module.export_inventory
exports = 0
def held_final_export(path, inventory):
    global exports
    exports += 1
    if exports == 2:
        ready.write_text("final publication paused")
        deadline = time.monotonic() + 10
        while not release.exists():
            if time.monotonic() > deadline:
                raise RuntimeError("Test owner was not released")
            time.sleep(0.01)
    return original_export(path, inventory)
module.export_inventory = held_final_export
result = module.collect(out, report, page_size=2, session=Session(), sleep=lambda value: None)
assert result["status"] == "classified_query_complete"
'''
    out = tmp_path / "out"
    report_path = tmp_path / "report.json"
    ready, release = tmp_path / "ready", tmp_path / "release"
    owner = subprocess.Popen([sys.executable, "-c", owner_code, str(MODULE_PATH),
                              str(out), str(report_path), str(ready), str(release)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and owner.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "Owner did not reach its final export"
        previous_inventory = (out / "inventory.jsonl").read_bytes()
        competitor = Session([response(classes()), response(results([bike("Q9")]))])
        with pytest.raises(ValueError, match="already writing this output directory"):
            collector.collect(out, report_path, resume=True, page_size=2,
                              session=competitor, sleep=lambda value: None)
        assert competitor.calls == []
        assert (out / "inventory.jsonl").read_bytes() == previous_inventory
        assert not report_path.exists()
    finally:
        release.write_text("continue")
        stdout, stderr = owner.communicate(timeout=10)
    assert owner.returncode == 0, stdout + stderr
    assert [record["qid"] for record in records(tmp_path)] == ["Q2"]
    assert json.loads(report_path.read_text())["unique_entities"] == 1
    # The owner's exit releases the OS lock; a later normal resume can proceed.
    resumed, session = run(tmp_path, [], resume=True, page_size=2)
    assert resumed["status"] == "classified_query_complete" and not session.calls


def test_method_validation_failure_releases_output_lock(tmp_path):
    run(tmp_path, [response(classes()), response(results([]))])
    with pytest.raises(ValueError, match="Resume method differs"):
        run(tmp_path, [], resume=True, page_size=10)
    report, session = run(tmp_path, [], resume=True)
    assert report["status"] == "classified_query_complete" and not session.calls

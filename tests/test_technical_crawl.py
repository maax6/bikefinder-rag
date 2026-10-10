import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from bikefinder_rag.scraper.technical_crawl import (
    AccessRules, BASE_URL, CrawlStore, HostAccessState, PoliteClient, SourceBusy, SourceDenied,
    crawl, discover_fiches, validate_url,
)

URL = BASE_URL + "/honda/885/ST-1100-PAN-EUROPEAN-2000/contact.html"
URL2 = BASE_URL + "/yamaha/10900/MT-07-700-2025/contact.html"


def response(status=200, body=b"technical", headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = body
    result.headers.update(headers or {})
    result.url = URL
    return result


def parsed(url, html):
    return {"source": "motoplanete", "url": url,
            "identity": {"year": 2000, "market": None},
            "spec_rows": [{"section": "Equipment", "label": "ABS", "value": "optional"}],
            "technical_snapshot": "<dl><dt>ABS</dt><dd>optional</dd></dl>"}


def test_robots_wildcards_longest_match_and_allow_ties():
    rules = AccessRules("""User-agent: *
Crawl-delay: 12
Allow: /
Disallow: /forums/
Disallow: */central.php
Disallow: /blocked*
Allow: /blocked/allowed$
""")
    assert rules.delay == 12
    assert rules.allows(URL)
    assert not rules.allows(BASE_URL + "/forums/topic")
    assert not rules.allows(BASE_URL + "/honda/central.php")
    assert rules.allows(BASE_URL + "/blocked/allowed")
    assert not rules.allows(BASE_URL + "/blocked/allowed/child")


@pytest.mark.parametrize("delay", [0, 2, 9.9, float("nan"), float("inf")])
def test_cannot_lower_source_delay(delay):
    with pytest.raises(ValueError):
        PoliteClient(delay)


@pytest.mark.parametrize("url", ["http://www.motoplanete.com/honda/885/X-2000/contact.html",
                                 "https://example.org/honda/885/X-2000/contact.html",
                                 URL + "?x=1", URL + "#fragment", BASE_URL + "/forums/x"])
def test_only_canonical_technical_fiches_are_seeded(tmp_path, url):
    store = CrawlStore(tmp_path)
    try:
        with pytest.raises(ValueError):
            store.seed([url])
        assert store.report()["discovered"] == 0
    finally:
        store.close()


def test_request_delay_applies_to_errors_and_redirects(tmp_path):
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    session = Mock()
    session.headers = {}
    session.get.side_effect = [response(body=b"User-agent: *\nCrawl-delay: 10\nAllow: /"),
                               response(302, headers={"Location": URL2}), response()]
    client = PoliteClient(session=session, sleep=sleep, clock=lambda: now[0])
    client.check_access(tmp_path)
    result, resolved = client.get(URL)
    assert result.status_code == 200 and resolved == URL2
    assert sleeps == [10, 10]
    assert all(call.kwargs["allow_redirects"] is False for call in session.get.call_args_list)


def test_disallowed_redirect_is_never_requested(tmp_path):
    session = Mock()
    session.headers = {}
    session.get.side_effect = [response(body=b"User-agent: *\nDisallow: /forums/"),
                               response(302, headers={"Location": BASE_URL + "/forums/topic"})]
    client = PoliteClient(session=session, sleep=lambda seconds: None)
    client.check_access(tmp_path)
    with pytest.raises(SourceDenied):
        client.get(URL)
    assert session.get.call_count == 2


def test_cross_host_redirect_is_never_requested(tmp_path):
    session = Mock()
    session.headers = {}
    session.get.side_effect = [response(body=b"User-agent: *\nAllow: /"),
                               response(302, headers={"Location": "https://example.org/"})]
    client = PoliteClient(session=session, sleep=lambda seconds: None)
    client.check_access(tmp_path)
    with pytest.raises(ValueError):
        client.get(URL)
    assert session.get.call_count == 2


def test_success_resume_is_idempotent_and_keeps_provenance(tmp_path):
    store = CrawlStore(tmp_path)
    client = SimpleNamespace(get=Mock(return_value=(response(), URL)))
    try:
        store.seed([URL, URL])
        report = crawl(store, client, parsed)
        assert report["states"] == {"success": 1}
        row = json.loads((tmp_path / "records.jsonl").read_text())
        assert row["collection"]["response_sha256"] == hashlib.sha256(b"technical").hexdigest()
        assert row["collection"]["requested_url"] == URL
        assert row["identity"]["market"] is None
        snapshot = tmp_path / row["collection"]["technical_snapshot"]
        assert snapshot.read_text().startswith("<dl>")
        store.close()
        store = CrawlStore(tmp_path)
        store.seed([URL])
        assert crawl(store, client, parsed)["attempted_this_run"] == 0
        assert client.get.call_count == 1
        assert len((tmp_path / "records.jsonl").read_text().splitlines()) == 1
    finally:
        store.close()


@pytest.mark.parametrize("failure", [requests.ReadTimeout("timeout"), ValueError("empty page")])
def test_network_or_extraction_failure_remains_retryable(tmp_path, failure):
    store = CrawlStore(tmp_path)
    client = SimpleNamespace(get=Mock(side_effect=failure))
    try:
        store.seed([URL])
        assert crawl(store, client, parsed)["states"] == {"retryable": 1}
        assert not (tmp_path / "records.jsonl").read_text()
        store.conn.execute("UPDATE pages SET retry_at=0")
        store.conn.commit()
        client.get.side_effect = None
        client.get.return_value = (response(), URL)
        assert crawl(store, client, parsed)["states"] == {"success": 1}
    finally:
        store.close()


def test_empty_extraction_is_not_marked_done(tmp_path):
    store = CrawlStore(tmp_path)
    client = SimpleNamespace(get=Mock(return_value=(response(), URL)))
    try:
        store.seed([URL])
        report = crawl(store, client, lambda url, html: {"spec_rows": []})
        assert report["states"] == {"retryable": 1}
    finally:
        store.close()


def test_429_halts_the_source_without_marking_done(tmp_path):
    store = CrawlStore(tmp_path)
    client = SimpleNamespace(get=Mock(side_effect=SourceBusy(429, 120)))
    try:
        store.seed([URL, URL2])
        report = crawl(store, client, parsed)
        assert report["states"] == {"pending": 1, "retryable": 1}
        assert report["halted"]
        assert client.get.call_count == 1
        store.close()
        store = CrawlStore(tmp_path)
        client.get.reset_mock()
        assert crawl(store, client, parsed)["attempted_this_run"] == 0
        client.get.assert_not_called()
    finally:
        store.close()


def test_source_cooldown_applies_before_robots_in_a_new_client(tmp_path):
    store = CrawlStore(tmp_path)
    session = Mock()
    session.headers = {}
    try:
        store.cooldown(120)
        client = PoliteClient(session=session, store=store)
        with pytest.raises(SourceBusy):
            client.check_access(tmp_path)
        session.get.assert_not_called()
    finally:
        store.close()


def test_request_spacing_is_persisted_between_processes(tmp_path, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("bikefinder_rag.scraper.technical_crawl.time.time", lambda: now[0])
    store = CrawlStore(tmp_path)
    try:
        store.touch_request()
        store.close()
        store = CrawlStore(tmp_path)
        now[0] += 2
        assert store.request_wait(10) == 8
    finally:
        store.close()


def test_host_cooldown_and_delay_survive_output_directory_changes(tmp_path, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("bikefinder_rag.scraper.technical_crawl.time.time", lambda: now[0])
    shared = tmp_path / "host.json"
    first = HostAccessState(shared)
    first.require_delay(20)
    first.touch_request()
    first.cooldown(120)
    second = HostAccessState(shared)
    now[0] += 2
    assert second.request_wait(10) == 18
    assert second.cooldown_remaining() == 118
    session = Mock()
    session.headers = {}
    with pytest.raises(SourceBusy):
        PoliteClient(session=session, store=second).check_access(tmp_path)
    session.get.assert_not_called()


def test_redirected_fiche_is_preserved_for_review_not_counted_for_original_year(tmp_path):
    store = CrawlStore(tmp_path)
    client = SimpleNamespace(get=Mock(return_value=(response(), URL2)))
    try:
        store.seed([URL])
        def changed(url, html):
            row = parsed(url, html)
            row["identity"]["year"] = 2025
            return row
        report = crawl(store, client, changed)
        assert report["states"] == {"needs_review": 1}
        assert report["by_year"]["2000"] == {"needs_review": 1}
        assert not (tmp_path / "records.jsonl").read_text()
        reviewed = json.loads((tmp_path / "review_records.jsonl").read_text())
        assert reviewed["identity"]["year"] == 2025
        assert reviewed["collection"]["identity_review_reasons"] == ["redirect_changed_fiche_or_year"]
    finally:
        store.close()


def test_404_is_a_visible_terminal_error_not_a_success(tmp_path):
    store = CrawlStore(tmp_path)
    client = SimpleNamespace(get=Mock(return_value=(response(404), URL)))
    try:
        store.seed([URL])
        assert crawl(store, client, parsed)["states"] == {"terminal": 1}
        assert not (tmp_path / "records.jsonl").read_text()
    finally:
        store.close()


def test_early_stop_preserves_previous_success_and_pending_page(tmp_path):
    store = CrawlStore(tmp_path)
    client = SimpleNamespace(get=Mock(side_effect=[(response(), URL), KeyboardInterrupt()]))
    try:
        store.seed([URL, URL2])
        with pytest.raises(KeyboardInterrupt):
            crawl(store, client, parsed)
        assert store.report()["states"] == {"pending": 1, "success": 1}
        assert len((tmp_path / "records.jsonl").read_text().splitlines()) == 1
        assert json.loads((tmp_path / "status.json").read_text())["running"] is False
    finally:
        store.close()


def test_far_future_is_quarantined_without_calling_it_fiction(tmp_path):
    store = CrawlStore(tmp_path)
    try:
        store.seed([BASE_URL + "/yaiba/8635/Kusanagi-CT-3X-2078/contact.html", URL2])
        assert store.report()["states"] == {"pending": 1, "quarantined": 1}
        assert store.todo() == [URL2]
    finally:
        store.close()


def test_sitemap_children_are_sequential_and_deduplicated():
    index = b"<sitemapindex><sitemap><loc>https://www.motoplanete.com/sitemap_moto_1.php</loc></sitemap></sitemapindex>"
    body = f"<urlset><url><loc>{URL}</loc></url><url><loc>{URL}</loc></url></urlset>".encode()
    client = SimpleNamespace(get=Mock(side_effect=[(response(body=index), BASE_URL + "/sitemap_moto.php"),
                                                  (response(body=body), BASE_URL + "/sitemap_moto_1.php")]))
    assert discover_fiches(client) == [URL]
    assert client.get.call_count == 2


def test_image_sitemap_locations_are_not_discovery_or_download_targets():
    body = (f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            f'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
            f'<url><loc>{URL}</loc><image:image><image:loc>https://farm5.staticflickr.com/photo.jpg</image:loc>'
            '</image:image></url></urlset>').encode()
    client = SimpleNamespace(get=Mock(return_value=(response(body=body), BASE_URL + "/sitemap_moto.php")))
    assert discover_fiches(client) == [URL]
    assert client.get.call_count == 1


def test_invalid_source_rules_fail_closed_without_fiche_request(tmp_path):
    session = Mock()
    session.headers = {}
    session.get.return_value = response(body=b"<html>Human verification</html>")
    client = PoliteClient(session=session)
    with pytest.raises(SourceDenied):
        client.check_access(tmp_path)
    assert session.get.call_count == 1
    with pytest.raises(SourceDenied):
        client.get(URL)

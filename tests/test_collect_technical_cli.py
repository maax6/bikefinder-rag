import importlib.util
from pathlib import Path
import sys
from unittest.mock import Mock

from bikefinder_rag.scraper.technical_crawl import CrawlStore


def test_resume_uses_durable_queue_without_refetching_failed_sitemaps(tmp_path, monkeypatch):
    path = Path(__file__).parents[1] / "scripts" / "collect_technical_data.py"
    spec = importlib.util.spec_from_file_location("collect_technical_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = tmp_path / "collection"
    store = CrawlStore(out)
    store.seed(["https://www.motoplanete.com/honda/885/ST-1100-PAN-EUROPEAN-2000/contact.html"])
    store.close()
    # A prior discovery failed: the queue remains, but no final sitemap cache exists.
    assert not (out / "fiche_urls.txt").exists()
    monkeypatch.setattr(module, "HOST_LOCK", tmp_path / "host.lock")
    monkeypatch.setattr(module, "HOST_STATE", tmp_path / "host.json")
    monkeypatch.setattr(sys, "argv", ["collect", "--out", str(out), "--limit", "0"])
    client = Mock()
    monkeypatch.setattr(module, "PoliteClient", Mock(return_value=client))
    discovery = Mock(side_effect=AssertionError("Resume must not depend on discovery"))
    monkeypatch.setattr(module, "discover_fiches", discovery)
    module.main()
    discovery.assert_not_called()
    client.get.assert_not_called()
    assert (out / "records.jsonl").read_text() == ""
    store = CrawlStore(out)
    try:
        assert store.report()["states"] == {"pending": 1}
    finally:
        store.close()

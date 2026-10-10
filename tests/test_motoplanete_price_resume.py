import importlib.util
from pathlib import Path
import sys

import pytest
import requests


def module():
    path = Path(__file__).parents[1] / "scripts" / "scrape_motoplanete_prices.py"
    spec = importlib.util.spec_from_file_location("motoplanete_price_resume", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.mark.parametrize("delay", ["2", "nan", "inf"])
def test_legacy_price_crawl_cannot_violate_source_delay(monkeypatch, delay):
    loaded = module()
    monkeypatch.setattr(sys, "argv", ["prices", "--delay", delay])
    monkeypatch.setattr(loaded, "get", lambda url: pytest.fail("Unexpected network request"))
    with pytest.raises(SystemExit) as caught:
        loaded.main()
    assert caught.value.code == 2


@pytest.mark.parametrize("status", [429, 500, 403])
def test_legacy_transient_or_blocked_page_is_never_marked_done(tmp_path, monkeypatch, status):
    loaded = module()
    url = "https://www.motoplanete.com/honda/885/ST-1100-PAN-EUROPEAN-2000/contact.html"
    monkeypatch.setattr(sys, "argv", ["prices", "--out", str(tmp_path), "--limit", "1"])
    monkeypatch.setattr(loaded, "fiche_urls", lambda path: [url])
    response = requests.Response()
    response.status_code = status
    def failed(url):
        raise requests.HTTPError("Source unavailable", response=response)
    monkeypatch.setattr(loaded, "get", failed)
    loaded.main()
    assert (tmp_path / "urls_done.txt").read_text() == ""
    assert (tmp_path / "prices.jsonl").read_text() == ""

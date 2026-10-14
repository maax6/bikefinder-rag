import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import requests

from bikefinder_rag.scraper.motoplanete_compare import crawl_batched
from bikefinder_rag.scraper.motoplanete_technical import parse_technical_page
from bikefinder_rag.scraper.technical_crawl import BASE_URL, CrawlStore, SourceBusy


URL = BASE_URL + "/bmw/3599/1000-K1-1988/contact.html"
COMPARE_URL = BASE_URL + "/vos-comparos/?ids[]=3599"


def response(url, body):
    result = requests.Response()
    result.status_code = 200
    result.url = url
    result._content = body.encode()
    return result


def comparator(with_autonomy=True):
    performance = """<tr class='technique-title'><th>Performances</th></tr>
      <tr><td><ul><li>Autonomie estimée : 367 km</li></ul></td></tr>""" if with_autonomy else ""
    return response(COMPARE_URL, f"""<main><table><thead>
      <tr class='name'><th><a href='{URL}'>BMW 1000 K1 1988</a></th></tr>
      </thead><tbody><tr class='title'><th>Châssis</th></tr>
      <tr class='technique-title'><th>Réservoir</th></tr><tr><td>22 litres</td></tr>
      <tr class='title'><th>Infos pratiques</th></tr>{performance}
      </tbody></table></main>""")


def fiche():
    return response(URL, """<h1><span class='brand'>BMW</span> 1000 K1
      <span class='year' itemprop='modelDate'>1988</span></h1>
      <dl id='tech-1'><dt>Châssis</dt><dd>Réservoir : 22 litres</dd></dl>
      <div class='performances'><ul><li>Consommation moyenne : 6 l/100km</li>
      <li>Autonomie estimée : 367 km <span class='tooltiptext'>Autonomie jusqu'à la
      panne sèche, calculée mais non vérifiée.</span></li></ul></div>""")


def test_batch_completes_autonomy_from_fiche_without_losing_qualification(tmp_path):
    client = SimpleNamespace(get_compare=Mock(return_value=(comparator(), COMPARE_URL)),
                             get=Mock(return_value=(fiche(), URL)))
    store = CrawlStore(tmp_path)
    try:
        store.seed([URL])
        report = crawl_batched(store, client, parse_technical_page, on_progress=None)
        row = json.loads(store.conn.execute('SELECT result FROM pages').fetchone()[0])
        autonomy = [r for r in row['spec_rows'] if r['label'] == 'Autonomie estimée']
        assert len(autonomy) == 1
        assert autonomy[0]['value'] == "367 km Autonomie jusqu'à la panne sèche, calculée mais non vérifiée."
        client.get.assert_called_once_with(URL)
        assert report['fiche_fallbacks_this_run'] == 1
        assert report['succeeded_this_run'] == 1
        snapshot = (tmp_path / row['collection']['technical_snapshot']).read_text()
        assert 'calculée mais non vérifiée' in snapshot
        assert row['collection']['response_sha256'] == hashlib.sha256(fiche().content).hexdigest()
    finally:
        store.close()


def test_no_autonomy_keeps_batch_without_extra_fiche_request(tmp_path):
    client = SimpleNamespace(get_compare=Mock(return_value=(comparator(False), COMPARE_URL)),
                             get=Mock(side_effect=AssertionError('Unexpected HTTP')))
    store = CrawlStore(tmp_path)
    try:
        store.seed([URL])
        report = crawl_batched(store, client, parse_technical_page, on_progress=None)
        assert report['succeeded_this_run'] == 1
        assert report['fiche_fallbacks_this_run'] == 0
        client.get.assert_not_called()
    finally:
        store.close()


def test_failed_autonomy_completion_does_not_save_incomplete_success(tmp_path):
    client = SimpleNamespace(get_compare=Mock(return_value=(comparator(), COMPARE_URL)),
                             get=Mock(side_effect=SourceBusy(500, 60)))
    store = CrawlStore(tmp_path)
    try:
        store.seed([URL])
        report = crawl_batched(store, client, parse_technical_page, on_progress=None)
        assert report['states'] == {'retryable': 1}
        assert report['succeeded_this_run'] == 0
        assert report['halted']
        assert store.conn.execute('SELECT result FROM pages').fetchone()[0] is None
    finally:
        store.close()


def test_missing_autonomy_on_individual_page_requires_review_before_success(tmp_path):
    incomplete = response(URL, "<dl id='tech-1'><dt>Châssis</dt><dd>Réservoir : 22 litres</dd></dl>")
    client = SimpleNamespace(get_compare=Mock(return_value=(comparator(), COMPARE_URL)),
                             get=Mock(return_value=(incomplete, URL)))
    store = CrawlStore(tmp_path)
    try:
        store.seed([URL])
        report = crawl_batched(store, client, parse_technical_page, on_progress=None)
        assert report['states'] == {'retryable': 1}
        assert store.conn.execute('SELECT result FROM pages').fetchone()[0] is None
    finally:
        store.close()

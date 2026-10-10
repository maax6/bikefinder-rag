from dataclasses import asdict
from types import SimpleNamespace

from bikefinder_rag.scraper import list_scraper


def listings(monkeypatch, names, options=""):
    rows = "".join(f"<tr><td><a href='../motorcycles/bike-{index}.php'>{name}</a></td>"
                   "<td>2000</td><td>Naked bike</td><td>500 ccm</td></tr>"
                   for index, name in enumerate(names))
    page = (f"<select id='CompBrand'>{options}</select><table><tr><td>Navigation</td></tr></table>"
            f"<table><tr><th>Motorcycles</th></tr>{rows}</table>")
    monkeypatch.setattr(list_scraper.http, "get", lambda url: SimpleNamespace(content=page.encode()))
    return list_scraper.list_motorcycles_for_year(2000)


def test_lists_preserve_full_compound_brands_and_numeric_models(monkeypatch):
    rows = listings(monkeypatch, ["MV Agusta Brutale 800", "Moto Guzzi V7", "Royal Enfield Classic 350", "BSA Motors 500"])

    assert [(row.brand, row.model) for row in rows] == [
        ("MV Agusta", "Brutale 800"), ("Moto Guzzi", "V7"),
        ("Royal Enfield", "Classic 350"), ("BSA Motors", "500"),
    ]
    assert all(row.identity_status == "normalized" and not row.identity_warnings for row in rows)
    assert all(row.year == 2000 and row.url.startswith("https://bikez.com/motorcycles/") for row in rows)


def test_source_options_extend_brand_vocabulary_with_longest_exact_prefix(monkeypatch):
    options = "<option value='1'>Future Works</option><option value='2'>Future Works Racing</option>"
    row, = listings(monkeypatch, ["Future Works Racing 125 Sport"], options)

    assert (row.brand, row.model) == ("Future Works Racing", "125 Sport")
    assert row.raw_name == "Future Works Racing 125 Sport"
    assert row.identity_status == "normalized"


def test_unknown_listing_keeps_raw_name_and_visible_boundary_warning(monkeypatch):
    row, = listings(monkeypatch, ["Unlisted Maker 500 Sport"])

    assert (row.brand, row.model) == ("Unlisted", "Maker 500 Sport")
    assert row.raw_name == "Unlisted Maker 500 Sport"
    assert row.identity_status == "needs_review"
    assert asdict(row)["identity_warnings"] == ["brand_not_in_vocabulary"]


def test_unknown_brand_is_not_hidden_by_empty_select_option(monkeypatch):
    row, = listings(monkeypatch, ["Choose Maker 500"], "<option value=''>Choose Maker</option>")

    assert row.identity_status == "needs_review"

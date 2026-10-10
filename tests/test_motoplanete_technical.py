import json

import pytest
from bs4 import BeautifulSoup

from bikefinder_rag.scraper.motoplanete_technical import parse_technical_page


URL = "https://www.motoplanete.com/honda/885/ST-1100-PAN-EUROPEAN-2000/contact.html"


def page(technical=None, extra="", brand="Honda", model="ST 1100 PAN EUROPEAN", year="2000", title_year="2000"):
    technical = technical if technical is not None else """
        <dl id="tech-1"><dt><span>Châssis</span></dt>
          <dd>Poids à sec : 287&nbsp;kg</dd>
          <dd>Poids tous pleins faits : 310 kg</dd></dl>
        <dl id="tech-2"><dt>Train avant</dt><dd>Freinage 2 disques Ø 316 mm</dd></dl>
        <dl id="tech-3"><dt>Train arrière</dt><dd>Freinage 1 disque Ø 316 mm</dd></dl>
        <dl id="tech-6" class="equipments"><dt>Équipement de série</dt>
          <dd>Assistance au freinage : Dual CBS - ABS - TCS en option</dd></dl>
    """
    return (f"<html><head><title>{brand} {model} {title_year} - Fiche moto, prix, avis</title></head>"
            f"<body><h1><span class='h'>Fiche moto</span><span class='brand'>{brand}</span> "
            f"{model} <span class='year' itemprop='modelDate'>{year}</span>"
            "<span class='titre'>Un slogan éditorial</span></h1>"
            f"{technical}{extra}</body></html>").encode()


def test_real_source_shapes_preserve_optional_equipment_and_brake_sections():
    result = parse_technical_page(URL, page())

    assert result["source"] == "motoplanete"
    assert result["identity"]["raw_name"] == "Honda ST 1100 PAN EUROPEAN 2000"
    assert result["identity"]["model"] == "ST 1100 PAN EUROPEAN"
    assert result["identity"]["year"] == 2000
    assert result["identity"]["market"] is None
    brakes = [row for row in result["spec_rows"] if row["label"] == "Freinage"]
    assert brakes == [
        {"section": "Train avant", "label": "Freinage", "value": "2 disques Ø 316 mm"},
        {"section": "Train arrière", "label": "Freinage", "value": "1 disque Ø 316 mm"},
    ]
    abs_evidence, = [item for item in result["equipment_evidence"] if item["term"] == "ABS"]
    assert abs_evidence["section"] == "Équipement de série"
    assert "en option" in abs_evidence["text"]
    assert abs_evidence["status"] == "unclassified"
    json.dumps(result, ensure_ascii=False)


def test_repeated_labels_keep_all_rows_and_all_compatibility_values():
    technical = """<dl id='tech-6'><dt>Équipement</dt>
        <dd>Assistance : ABS en option</dd><dd>Assistance : CBS de série</dd>
        <dd>Assistance : TCS non disponible</dd></dl>"""
    result = parse_technical_page(URL, page(technical))

    assert len(result["spec_rows"]) == 3
    assert list(result["raw_specs"].values()) == ["ABS en option", "CBS de série", "TCS non disponible"]
    assert len(result["raw_specs"]) == 3


def test_subsections_inside_one_definition_list_keep_their_source_headings():
    technical = """<dl id='tech-6'><dt>Équipement de série</dt><dd>Bluetooth</dd>
      <dt>Équipement en option</dt><dd>ABS</dd></dl>"""
    result = parse_technical_page(URL, page(technical))
    assert [row["section"] for row in result["spec_rows"]] == ["Équipement de série", "Équipement en option"]
    assert [item["section"] for item in result["equipment_evidence"]] == ["Équipement de série", "Équipement en option"]


def test_owner_reviews_article_faq_competitors_and_advertising_never_enter_snapshot():
    extras = """
      <div id='description'>Essai : ABS de série. Auteur Testeur.</div>
      <div id='avis'><h2>Avis</h2><div itemprop='reviewBody'>Avis ABS : propriétaire Alice.</div>
        <dl id='tech-77'><dt>Équipement</dt><dd>ABS : de série selon Bob</dd></dl>
        <div class='performances'><li>ABS dans un avis</li></div></div>
      <dl class='faq'><dt>ABS ?</dt><dd>Oui selon Jean.</dd></dl>
      <div id='concurrence'>Concurrente ABS 2001</div>
      <script>alert('ABS')</script><iframe src='https://ads.example/'></iframe>
    """
    technical = """<dl id='tech-1'><dt>Châssis</dt><dd>Réservoir : 28 litres
      <a rel='sponsored' href='https://ads.example/'>Acheter une moto chez Annonceur</a>
      <span class='pub'>ABS offre de publicité</span><script>secret</script>
      <img alt='Photo Alice'/><!-- nom propriétaire --></dd></dl>"""
    result = parse_technical_page(URL, page(technical, extras))

    assert result["equipment_evidence"] == []
    all_output = json.dumps(result, ensure_ascii=False)
    for excluded in ["Alice", "Bob", "Jean", "Testeur", "Annonceur", "propriétaire", "secret", "publicité", "Concurrente"]:
        assert excluded not in all_output
    snapshot = BeautifulSoup(result["technical_snapshot"], "html.parser")
    assert not snapshot.find(["script", "img", "iframe", "a", "style"])
    assert "Réservoir" in snapshot.get_text()
    assert "28 litres" in snapshot.get_text()


def test_negative_equipment_text_stays_unclassified_and_missing_is_not_false():
    present = parse_technical_page(URL, page("<dl id='tech-6'><dt>Équipement</dt><dd>Freinage : sans ABS</dd></dl>"))
    absent = parse_technical_page(URL, page("<dl id='tech-1'><dt>Châssis</dt><dd>Poids : 287 kg</dd></dl>"))

    assert present["equipment_evidence"][0]["text"] == "Freinage : sans ABS"
    assert present["equipment_evidence"][0]["status"] == "unclassified"
    assert absent["equipment_evidence"] == []
    assert "abs" not in absent
    assert "ABS" not in absent["raw_specs"]


def test_unrecognized_equipment_and_shifter_in_transmission_are_retained():
    technical = """<dl id='tech-5'><dt>Transmission</dt><dd>boîte à 6 rapports, shifter en option</dd></dl>
      <dl id='tech-6'><dt>Équipement de série</dt><dd>Jantes aluminium</dd></dl>"""
    result = parse_technical_page(URL, page(technical))

    assert {item["term"] for item in result["equipment_evidence"]} == {"shifter", "Jantes aluminium"}
    assert all(item["status"] == "unclassified" for item in result["equipment_evidence"])


def test_sponsored_shopping_row_does_not_leave_an_equipment_candidate():
    technical = """<dl id='tech-6'><dt>Équipement</dt><dd>Bluetooth</dd>
        <dd>🛒 <a data-trk-external-link='tech-equipements'>Commander un équipement ABS</a></dd></dl>"""
    result = parse_technical_page(URL, page(technical))
    assert len(result["spec_rows"]) == 1
    assert [item["term"] for item in result["equipment_evidence"]] == ["Bluetooth"]
    assert "🛒" not in result["technical_snapshot"]


def test_colors_only_current_year_text_captions_are_retained():
    colors = """<div id='millesimes'>
      <div class='millesime'><p class='annee'>2001</p><img alt='Photo de profil en couleur vert'/></div>
      <div class='millesime'><p class='annee current'>2000</p>
        <img src='photo.jpg' alt='Photo de profil de la ST 1100 PAN EUROPEAN 2000 en couleur rouge'/>
        <img alt='Photo de profil de la ST 1100 PAN EUROPEAN 2000 en couleur rouge'/>
        <img alt='Photo de profil de la ST 1100 PAN EUROPEAN 2000 en couleur non défini'/></div>
    </div>"""
    result = parse_technical_page(URL, page(extra=colors))

    assert [row["value"] for row in result["spec_rows"] if row["section"] == "Coloris"] == ["rouge", "non défini"]
    assert "vert" not in result["technical_snapshot"]
    assert "photo.jpg" not in json.dumps(result)
    assert "<img" not in result["technical_snapshot"]


def test_tariffs_are_country_and_variant_scoped_without_inventing_model_market():
    tariff = """<div class='tarif'><h3>Tarifs</h3><table>
      <thead><tr><th></th><th>Version de base</th><th>Avec ABS</th></tr></thead>
      <tr><td><img alt='France'/>France</td><td>11 259 € *</td><td>12 000 €</td></tr>
      <tr><td>Autriche</td><td>11 500 €</td><td>12 300 €</td></tr></table>
      <div class='cote'>Occasions de 900 à 1000 €, vendeur Michel.</div></div>"""
    result = parse_technical_page(URL, page(extra=tariff))

    tariff_rows = [row for row in result["spec_rows"] if row["section"] == "Tarifs"]
    assert tariff_rows[0] == {"section": "Tarifs", "label": "France — Version de base", "value": "11 259 € *"}
    assert tariff_rows[1]["label"] == "France — Avec ABS"
    assert result["price_markets"] == ["France", "Autriche"]
    assert result["identity"]["market"] is None
    assert "Michel" not in json.dumps(result)


def test_performance_qualifiers_and_calculated_nature_are_preserved():
    performance = """<div class='performances'><h3>Performances</h3><ul>
      <li><a>Vitesse max</a> : supérieur à 210 km/h</li>
      <li>Autonomie estimée : 400 km <span class='tooltiptext'>calculée mais non vérifiée</span></li>
    </ul></div>"""
    result = parse_technical_page(URL, page(extra=performance))

    assert any(row["value"] == "supérieur à 210 km/h" for row in result["spec_rows"])
    assert "calculée mais non vérifiée" in result["technical_snapshot"]


def test_explicit_market_is_retained_only_from_a_source_label():
    result = parse_technical_page(URL, page("<dl id='tech-1'><dt>Châssis</dt><dd>Marché : Japon</dd></dl>"))
    assert result["identity"]["market"] == "Japon"


def test_conflicting_markets_are_unknown_with_both_source_rows_retained():
    technical = """<dl id='tech-1'><dt>Châssis</dt>
      <dd>Marché : Japon</dd><dd>Marché : France</dd><dd>Marché : Japon</dd></dl>"""
    result = parse_technical_page(URL, page(technical))
    assert result["identity"]["market"] is None
    assert "conflicting_explicit_markets" in result["identity"]["warnings"]
    assert len(result["spec_rows"]) == 3


def test_practical_license_rows_require_the_technical_container():
    extra = """<div class='bloc-tech'><dl><dt>Infos pratiques</dt>
      <dd>Véhicule accessible au permis A2 ou bridable à 47.5ch / 35 Kw</dd>
      <dd>La moto est accessible aux permis : A, A2</dd></dl></div>
      <div class='faq'><dl><dt>Infos pratiques</dt><dd>Question de Camille sur A2</dd></dl></div>"""
    result = parse_technical_page(URL, page(extra=extra))
    practical = [row for row in result["spec_rows"] if row["section"] == "Infos pratiques"]
    assert len(practical) == 2
    assert "47.5ch / 35 Kw" in practical[0]["value"]
    assert "Camille" not in json.dumps(result)


def test_repeated_section_titles_do_not_multiply_snapshot_rows():
    technical = """<dl id='tech-1'><dt>Équipement</dt><dd>ABS en option</dd></dl>
      <dl id='tech-2'><dt>Moteur</dt><dd>1000 cc</dd></dl>
      <dl id='tech-6'><dt>Équipement</dt><dd>TCS en option</dd></dl>"""
    result = parse_technical_page(URL, page(technical))
    snapshot = BeautifulSoup(result["technical_snapshot"], "html.parser")
    assert len(snapshot.find_all("dd")) == len(result["spec_rows"]) == 3


def test_heading_and_document_title_year_conflicts_are_visible():
    result = parse_technical_page(URL, page(year="2001", title_year="2002"))

    assert result["identity"]["year"] == 2001
    assert result["identity"]["url_year"] == 2000
    assert "heading_year_conflicts_with_url" in result["identity"]["warnings"]
    assert "title_year_conflicts_with_url" in result["identity"]["warnings"]


@pytest.mark.parametrize("model", ["VTX 1800", "Vulcan 2000", "500 Classic"])
def test_model_numbers_are_not_mistaken_for_model_year(model):
    url = f"https://www.motoplanete.com/honda/42/{model.replace(' ', '-')}-2001/contact.html"
    result = parse_technical_page(url, page(model=model, year="2001", title_year="2001"))
    assert result["identity"]["model"] == model
    assert result["identity"]["year"] == 2001


def test_url_fallback_marks_uncertain_identity_without_losing_numeric_model():
    url = "https://www.motoplanete.com/kawasaki/42/Vulcan-2000-2000/contact.html"
    result = parse_technical_page(url, b"<dl id='tech-1'><dt>Moteur</dt><dd>2000 cc</dd></dl>")
    assert result["identity"]["model"] == "Vulcan 2000"
    assert result["identity"]["year"] == 2000
    assert set(result["identity"]["warnings"]) == {"heading_missing", "brand_from_url_slug", "model_from_url_slug", "year_from_url"}


@pytest.mark.parametrize("url", [
    "https://motoplanete.com.evil.example/honda/885/ST-2000/contact.html",
    "https://evil.example/honda/885/ST-2000/contact.html",
    "http://www.motoplanete.com/honda/885/ST-2000/contact.html",
    "https://alice@www.motoplanete.com/honda/885/ST-2000/contact.html",
    "https://www.motoplanete.com:443/honda/885/ST-2000/contact.html",
    "https://www.motoplanete.com/honda/885/ST-2000/contact.html?other=1",
    "https://www.motoplanete.com/honda/885/ST-2000/contact.html#avis",
    "https://www.motoplanete.com/honda/885/ST-2000/avis.html",
    "https://www.motoplanete.com/honda/885/ST%2F2000-2000/contact.html",
    "https://www.motoplanete.com/honda/885/ST-1600/contact.html",
])
def test_only_expected_fiche_urls_are_accepted(url):
    with pytest.raises(ValueError):
        parse_technical_page(url, page())


@pytest.mark.parametrize("content", [
    b"<html><p>Maintenance / human check</p></html>",
    page(technical="", extra="<div id='avis'>ABS en option</div>"),
    page(technical="", extra="<div class='tarif'><table><tr><td>France</td><td>1000 euros</td></tr></table></div>"),
    page(technical="<dl id='tech-1'><dt>Châssis</dt><dd></dd></dl>"),
])
def test_empty_technical_extraction_is_an_error(content):
    with pytest.raises(ValueError, match="No technical specification rows"):
        parse_technical_page(URL, content)


def test_snapshot_escapes_source_text_and_never_copies_attributes():
    technical = "<dl id='tech-1'><dt>Châssis</dt><dd data-secret='private'>Cadre : &lt;script&gt; &amp; acier</dd></dl>"
    result = parse_technical_page(URL, page(technical))
    assert "&lt;script&gt; &amp; acier" in result["technical_snapshot"]
    assert "data-secret" not in result["technical_snapshot"]
    assert "private" not in result["technical_snapshot"]


def test_no_www_host_is_valid_and_parsing_is_deterministic():
    url = URL.replace("www.", "")
    assert parse_technical_page(url, page()) == parse_technical_page(url, page())

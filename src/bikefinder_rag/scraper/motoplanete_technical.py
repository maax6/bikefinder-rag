"""Extract only the technical blocks of a Motoplanete motorcycle fiche.

This parser makes no requests.  Its rows retain source wording and duplicates;
equipment matches are evidence candidates, never assertions of standard fitment.
The generated snapshot contains extracted text, not a copy of the source page.
"""

from __future__ import annotations

import html as html_lib
from itertools import groupby
import re
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, Comment, Tag

PARSER_VERSION = "motoplanete-technical-v1"
_FICHE_PATH = re.compile(r"^/([^/]+)/([0-9]+)/([^/]+)-([0-9]{4})/contact\.html$")
_TECH_ID = re.compile(r"^tech-[0-9]+$")
_LABEL = re.compile(r"^([A-Za-zÀ-ÖØ-öø-ÿ][^:()]{0,64}?)\s*:\s*(.+)$", re.S)
_BLOCKED_SELECTOR = (
    "script, style, iframe, noscript, img, picture, source, svg, form, button, "
    "[hidden], [aria-hidden='true'], [itemprop~='review'], [itemprop~='reviewBody'], "
    "[itemprop~='author'], [itemtype*='/Review'], .avis, .reviews, .review, "
    ".pub, .advertisement, .advert, .pneu, [rel~='sponsored'], [data-trk-external-link]"
)
_EQUIPMENT_TERMS = (
    ("ABS", r"\bABS\b"),
    ("CBS", r"\bCBS\b"),
    ("TCS", r"\bTCS\b"),
    ("contrôle de traction", r"\b(?:contr[oô]le (?:de|de la) traction|traction control)\b"),
    ("régulateur de vitesse", r"\b(?:r[eé]gulateur (?:de )?vitesse|cruise control)\b"),
    ("shifter", r"\b(?:quick\s*shifter|shifter)\b"),
    ("TFT", r"\bTFT\b"),
    ("Bluetooth", r"\bBluetooth\b"),
    ("airbag", r"\bairbag\b"),
    ("poignées chauffantes", r"\b(?:poign[eé]es chauffantes|heated grips)\b"),
    ("marche arrière", r"\b(?:marche arri[eè]re|reverse gear)\b"),
    ("TPMS", r"\b(?:TPMS|surveillance (?:de la )?pression des pneus)\b"),
    ("IMU", r"\b(?:IMU|centrale inertielle)\b"),
    ("modes de conduite", r"\b(?:modes? de conduite|riding modes?)\b"),
    ("ride by wire", r"\b(?:ride[- ]by[- ]wire|acc[eé]l[eé]rateur [eé]lectronique)\b"),
    ("anti-dribble", r"\b(?:anti[- ]dribble|slipper clutch)\b"),
)


def _space(text: str) -> str:
    return " ".join(text.split())


def _validate_url(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {"motoplanete.com", "www.motoplanete.com"}
            or parsed.username is not None or parsed.password is not None or parsed.port is not None
            or parsed.query or parsed.fragment):
        raise ValueError("Expected an HTTPS Motoplanete motorcycle fiche URL")
    path = unquote(parsed.path)
    match = _FICHE_PATH.fullmatch(path)
    if not match or any(part in {".", ".."} for part in path.split("/")):
        raise ValueError("Expected a Motoplanete /brand/id/model-year/contact.html fiche URL")
    brand_slug, _, model_slug, year_text = match.groups()
    year = int(year_text)
    if not 1800 <= year <= 2199:
        raise ValueError("The fiche URL must contain a plausible explicit model year")
    return brand_slug, model_slug, year


def _text(node: Tag) -> str:
    """Discard nontechnical descendants without changing the caller's DOM."""
    clone = BeautifulSoup(str(node), "html.parser")
    for child in list(clone.select(_BLOCKED_SELECTOR)):
        if child.parent is not None:
            child.decompose()
    for child in list(clone.find_all(style=True)):
        if re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", child["style"], re.I):
            child.decompose()
    for comment in clone.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
    text = _space(clone.get_text(" ", strip=True))
    # Shopping icons can remain after the sponsored link is discarded.
    return text if any(character.isalnum() for character in text) else ""


def _in_review(node: Tag) -> bool:
    for ancestor in [node, *node.parents]:
        if not isinstance(ancestor, Tag):
            continue
        attrs = " ".join(str(ancestor.get(key, "")) for key in ("id", "class", "itemprop", "itemtype"))
        if re.search(r"\b(?:avis|review|reviews|reviewBody|commentaires|comments|author)\b|/Review\b", attrs, re.I):
            return True
    return False


def _identity(soup: BeautifulSoup, brand_slug: str, model_slug: str, url_year: int) -> dict:
    warnings: list[str] = []
    heading = soup.find("h1")
    brand: str | None = None
    model: str | None = None
    heading_year: int | None = None
    raw_name: str | None = None
    if heading is not None:
        clone = BeautifulSoup(str(heading), "html.parser").find("h1")
        brand_tag = clone.select_one(".brand")
        year_tag = clone.select_one(".year, [itemprop='modelDate']")
        brand = _text(brand_tag) if brand_tag else None
        if year_tag:
            year_text = _text(year_tag)
            if re.fullmatch(r"[0-9]{4}", year_text) and 1800 <= int(year_text) <= 2199:
                heading_year = int(year_text)
            else:
                warnings.append("heading_year_unparseable")
        for tag in list(clone.select(".h, .titre, .subtitle, .slogan")):
            tag.decompose()
        raw_name = _text(clone)
        for tag in list(clone.select(".brand, .year, [itemprop='modelDate']")):
            tag.decompose()
        model = _text(clone) or None
        if not brand:
            # The slug is retained as an unverified boundary, not a canonical brand.
            warnings.append("brand_from_url_slug")
            brand = brand_slug.replace("-", " ")
            if model and model.casefold().startswith(brand.casefold() + " "):
                model = model[len(brand):].strip()
        if year_tag is None:
            # Only trim a trailing URL year when the remaining model matches
            # the URL model.  VTX 1800 and Vulcan 2000 stay literal model names.
            candidate = re.sub(rf"\s+{url_year}$", "", model or "")
            literal = lambda value: re.sub(r"[^\w]", "", value.casefold())
            if model and candidate != model and literal(candidate) == literal(model_slug):
                model = candidate
    else:
        warnings.append("heading_missing")
    if not brand:
        brand = brand_slug.replace("-", " ")
        warnings.append("brand_from_url_slug")
    if not model:
        model = model_slug.replace("-", " ")
        warnings.append("model_from_url_slug")
    if heading_year is None:
        warnings.append("year_from_url")
    elif heading_year != url_year:
        warnings.append("heading_year_conflicts_with_url")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    title_year_match = re.search(r"\b([0-9]{4})\s+-\s+Fiche moto\b", title, re.I)
    if title_year_match and int(title_year_match.group(1)) != url_year:
        warnings.append("title_year_conflicts_with_url")
    return {
        "raw_name": raw_name or f"{brand} {model} {url_year}",
        "brand": brand,
        "model": model,
        "year": heading_year if heading_year is not None else url_year,
        "url_year": url_year,
        "market": None,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _split_row(text: str) -> tuple[str, str]:
    if match := _LABEL.fullmatch(text):
        return _space(match.group(1)), _space(match.group(2))
    if text.startswith("Freinage "):
        return "Freinage", text.removeprefix("Freinage ")
    return "", text


def _definition_sections(block: Tag) -> list[tuple[str, list[tuple[str, str]]]]:
    """Retain a new subsection heading when one dl contains several dt groups."""
    groups: list[tuple[str, list[tuple[str, str]]]] = []
    active: list[tuple[str, str]] | None = None
    for child in block.children:
        if not isinstance(child, Tag) or _in_review(child):
            continue
        if child.name == "dt":
            heading = _text(child)
            active = [] if heading else None
            if heading:
                groups.append((heading, active))
        elif child.name == "dd" and active is not None:
            active.append(_split_row(_text(child)))
    return groups


def _snapshot(identity: dict, rows: list[dict]) -> str:
    esc = html_lib.escape
    chunks = ['<article data-source="motoplanete">', f'<h1>{esc(identity["raw_name"])}</h1>']
    # Every attribute and element is supplied here. Source markup never passes through.
    for section, group in groupby(rows, key=lambda row: row["section"]):
        chunks.append(f'<section><h2>{esc(section)}</h2><dl>')
        for row in group:
            chunks.append(f'<dt>{esc(row["label"])}</dt><dd>{esc(row["value"])}</dd>')
        chunks.append("</dl></section>")
    chunks.append("</article>")
    return "".join(chunks)


def parse_technical_page(url: str, html: bytes) -> dict:
    """Return technical text and unclassified evidence; reject an empty fiche.

    A price country applies to its tariff row. It does not establish the market
    of every specification. The compatibility dictionary keeps repeated keys
    using section/suffix qualifiers; ``spec_rows`` is the complete source list.
    """
    brand_slug, model_slug, url_year = _validate_url(url)
    soup = BeautifulSoup(html, "html.parser")
    identity = _identity(soup, brand_slug, model_slug, url_year)
    rows: list[dict] = []
    sections: list[dict] = []
    price_markets: list[str] = []

    def add_section(section: str, values: list[tuple[str, str]]) -> None:
        clean = [(label, value) for label, value in values if value]
        if not clean:
            return
        rows.extend({"section": section, "label": label, "value": value} for label, value in clean)
        sections.append({"section": section, "text": "; ".join(f"{label} : {value}" if label else value for label, value in clean)})

    # The source's technical map consists of numbered dl blocks. We deliberately
    # don't traverse the review text, general article, FAQ or competing models.
    for block in soup.find_all("dl", id=_TECH_ID):
        if _in_review(block):
            continue
        section_tag = block.find("dt", recursive=False)
        section = _text(section_tag) if section_tag else ""
        if not section:
            identity["warnings"].append("technical_section_heading_missing")
            continue
        for heading, values in _definition_sections(block):
            add_section(heading, values)

    for block in soup.select(".bloc-tech > dl"):
        if _TECH_ID.fullmatch(block.get("id", "")) or _in_review(block):
            continue
        heading = block.find("dt", recursive=False)
        if heading and _text(heading) == "Infos pratiques":
            for section, values in _definition_sections(block):
                add_section(section, values)

    for block in soup.select(".performances"):
        if not _in_review(block):
            add_section("Performances", [_split_row(_text(item)) for item in block.select("li") if not _in_review(item)])

    for block in soup.select(".tarif"):
        if _in_review(block):
            continue
        values = []
        for table in block.find_all("table"):
            headings = [_text(cell) for cell in table.select("thead th")]
            for row in table.find_all("tr"):
                cells = row.find_all("td", recursive=False)
                if len(cells) < 2 or _in_review(row):
                    continue
                country = _text(cells[0])
                if country and country not in price_markets:
                    price_markets.append(country)
                for index, cell in enumerate(cells[1:], 1):
                    variant = headings[index] if index < len(headings) else ""
                    label = " — ".join(part for part in (country, variant) if part)
                    values.append((label, _text(cell)))
        add_section("Tarifs", values)

    # Current-year color captions are textual evidence. Images and photo URLs
    # are discarded, as are captions belonging to another year in the timeline.
    for timeline in soup.select("#millesimes .millesime"):
        year_tag = timeline.select_one(".annee")
        if not year_tag or _text(year_tag) != str(identity["year"]) or _in_review(timeline):
            continue
        colors = []
        for image in timeline.find_all("img", alt=True):
            match = re.search(r"\ben couleur\s+(.+)$", image["alt"], re.I)
            if match:
                color = _space(match.group(1))
                if color and color not in colors:
                    colors.append(color)
        add_section("Coloris", [("Coloris", color) for color in colors])

    if not any(row["section"] not in {"Tarifs", "Coloris"} for row in rows):
        raise ValueError("No technical specification rows found in Motoplanete fiche")

    raw_specs: dict[str, str] = {}
    evidence: list[dict] = []
    explicit_markets: list[str] = []
    for row in rows:
        label, value, section = row["label"], row["value"], row["section"]
        key = label or section
        if key in raw_specs:
            key = f"{section} / {label}" if label else section
        base, suffix = key, 2
        while key in raw_specs:
            key, suffix = f"{base} [{suffix}]", suffix + 1
        raw_specs[key] = value
        if label.casefold() in {"marché", "marche", "market"}:
            if value not in explicit_markets:
                explicit_markets.append(value)
        text = f"{label} : {value}" if label else value
        terms = [term for term, pattern in _EQUIPMENT_TERMS if re.search(pattern, text, re.I)]
        if not terms and re.search(r"[eé]quipement|equipment", section, re.I):
            terms = [label or value]
        for term in terms:
            evidence.append({"term": term, "label": label, "section": section, "text": text, "status": "unclassified"})
    if len(explicit_markets) == 1:
        identity["market"] = explicit_markets[0]
    elif len(explicit_markets) > 1:
        identity["warnings"].append("conflicting_explicit_markets")
    identity["warnings"] = list(dict.fromkeys(identity["warnings"]))
    return {
        "source": "motoplanete", "url": url, "parser_version": PARSER_VERSION,
        "identity": identity, "spec_rows": rows, "technical_sections": sections,
        "raw_specs": raw_specs, "equipment_evidence": evidence,
        "price_markets": price_markets,
        "technical_snapshot": _snapshot(identity, rows),
    }

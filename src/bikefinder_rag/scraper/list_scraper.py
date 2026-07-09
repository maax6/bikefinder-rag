"""List motorcycles for a given year, applying the category filter.

Adapted from the original github.com/maax6/Bikefinder `scrapeUrlByYear.py`
(same table-scraping approach) — now filters out excluded categories at
listing time instead of collecting everything.
"""

from dataclasses import dataclass

from bs4 import BeautifulSoup

from bikefinder_rag.scraper import http
from bikefinder_rag.scraper.categories import is_included, parse_displacement_ccm

MIN_YEAR = 1894
MAX_YEAR = 2025


@dataclass
class MotorcycleListing:
    brand: str
    model: str
    year: int
    category: str
    engine_text: str
    displacement_ccm: float | None
    url: str


def list_motorcycles_for_year(year: int) -> list[MotorcycleListing]:
    if not (MIN_YEAR <= year <= MAX_YEAR):
        raise ValueError(f"year must be between {MIN_YEAR} and {MAX_YEAR}")

    response = http.get(f"/year/{year}-motorcycle-models.php")
    soup = BeautifulSoup(response.content, "html.parser")

    tables = soup.find_all("table")
    if len(tables) < 2:
        return []

    rows = tables[1].find_all("tr")[1:]
    listings: list[MotorcycleListing] = []

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue

        link_tag = cols[0].find("a")
        if not link_tag:
            continue

        name = link_tag.text.strip()
        relative_url = link_tag.get("href", "").replace("../", "")
        full_url = f"{http.BASE_URL}/{relative_url.lstrip('/')}"

        category = cols[2].text.strip()
        engine_text = cols[3].text.strip()
        displacement_ccm = parse_displacement_ccm(engine_text)

        if not is_included(category, displacement_ccm):
            continue

        brand, _, model = name.partition(" ")

        listings.append(
            MotorcycleListing(
                brand=brand,
                model=model,
                year=year,
                category=category,
                engine_text=engine_text,
                displacement_ccm=displacement_ccm,
                url=full_url,
            )
        )

    return listings

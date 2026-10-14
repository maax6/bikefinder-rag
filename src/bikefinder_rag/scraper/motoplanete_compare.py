"""Collect up to four Motoplanete fiches per request through the public comparator.

The site's own comparator (``/vos-comparos/?ids[]=..``, allowed by robots.txt,
limit 4 bikes enforced by the site UI) renders technical blocks in separate
columns, but omits some source qualifications. Fetching it keeps
exactly the same pacing (robots.txt Crawl-delay, one sequential request at a
time, Retry-After/cooldown, shared host lock). Records with autonomy are fetched
individually to retain the complete source text; the actual speedup depends on
the number of these additional requests.

No pacing is relaxed here: every request goes through ``PoliteClient`` timing.
Records keep the ``parse_technical_page`` shape so ``CrawlStore`` and the
exports are unchanged; the parser version says where they came from.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .motoplanete_technical import _EQUIPMENT_TERMS, _definition_sections, _snapshot, _space, _split_row, _text
from .technical_crawl import BASE_URL, FICHE_PATH, PoliteClient, SourceDenied, validate_url

PARSER_VERSION = "motoplanete-compare-v1"
COMPARE_PATH = "/vos-comparos/"
MAX_PER_REQUEST = 4  # "Vous avez déjà sélectionné 4 motos." (site UI limit)
_SKIP_SECTIONS = {"presentation", "présentation", "comparer", "concurrentes"}
_EMPTY = {"", "-"}


def fiche_id(url: str) -> str:
    return urlsplit(url).path.split("/")[2]


def compare_url(ids: list[str]) -> str:
    if not 1 <= len(ids) <= MAX_PER_REQUEST or not all(i.isdigit() for i in ids):
        raise ValueError("Comparator takes 1 to 4 numeric fiche ids")
    return BASE_URL + COMPARE_PATH + "?" + "&".join(f"ids[]={i}" for i in ids)


class CompareClient(PoliteClient):
    """PoliteClient that may also request the comparator URL (with a query)."""

    def _request(self, url: str):
        parts = urlsplit(url)
        if parts.path == COMPARE_PATH and parts.netloc == "www.motoplanete.com" and parts.scheme == "https":
            if not re.fullmatch(r"ids\[\]=\d+(?:&ids\[\]=\d+){0,3}", parts.query):
                raise ValueError("Unexpected comparator query")
            # Reuse the parent's pacing/backoff by validating a canonical stand-in.
            import bikefinder_rag.scraper.technical_crawl as tc
            original = tc.validate_url
            tc.validate_url = lambda u, **k: u
            try:
                return super()._request(url)
            finally:
                tc.validate_url = original
        return super()._request(url)

    def get_compare(self, ids: list[str]):
        url = compare_url(ids)
        if self.rules is None:
            raise SourceDenied("Check source access before requesting content")
        if not self.rules.allows(url):
            raise SourceDenied("Comparator excluded by the current robots.txt")
        response = self._request(url)
        if response.status_code in {401, 403}:
            raise SourceDenied(f"HTTP {response.status_code}; no bypass attempted")
        return response, url


def _identity(name: str, url: str) -> dict:
    brand_slug, _, model_slug_year = urlsplit(url).path.split("/")[1:4]
    url_year = int(FICHE_PATH.fullmatch(urlsplit(url).path).group(1))
    warnings = []
    year = url_year
    m = re.search(r"\s([0-9]{4})$", name)
    if m:
        year = int(m.group(1))
        if year != url_year:
            warnings.append("heading_year_conflicts_with_url")
        rest = name[: m.start()].strip()
    else:
        warnings.append("year_from_url")
        rest = name
    letters = lambda s: re.sub(r"[^a-z0-9]", "", s.casefold())
    tokens, brand = rest.split(), None
    for n in range(1, min(4, len(tokens)) + 1):
        if letters(" ".join(tokens[:n])) == letters(brand_slug):
            brand, model = " ".join(tokens[:n]), " ".join(tokens[n:])
            break
    if brand is None:
        warnings.append("brand_from_url_slug")
        brand, model = brand_slug.replace("-", " "), rest
    return {"raw_name": name, "brand": brand, "model": model or model_slug_year, "year": year,
            "url_year": url_year, "market": None, "warnings": warnings}


def _finish(url: str, identity: dict, rows: list[dict], price_markets: list[str]) -> dict:
    sections, raw_specs, evidence, markets = [], {}, [], []
    for row in rows:
        if not sections or sections[-1]["section"] != row["section"]:
            sections.append({"section": row["section"], "parts": []})
        sections[-1]["parts"].append(f'{row["label"]} : {row["value"]}' if row["label"] else row["value"])
        label, value, section = row["label"], row["value"], row["section"]
        key = label or section
        if key in raw_specs:
            key = f"{section} / {label}" if label else section
        base, suffix = key, 2
        while key in raw_specs:
            key, suffix = f"{base} [{suffix}]", suffix + 1
        raw_specs[key] = value
        if label.casefold() in {"marché", "marche", "market"} and value not in markets:
            markets.append(value)
        text = f"{label} : {value}" if label else value
        terms = [t for t, p in _EQUIPMENT_TERMS if re.search(p, text, re.I)]
        if not terms and re.search(r"[eé]quipement|equipment", section, re.I):
            terms = [label or value]
        evidence += [{"term": t, "label": label, "section": section, "text": text, "status": "unclassified"} for t in terms]
    if len(markets) == 1:
        identity["market"] = markets[0]
    elif len(markets) > 1:
        identity["warnings"].append("conflicting_explicit_markets")
    return {
        "source": "motoplanete", "url": url, "parser_version": PARSER_VERSION,
        "identity": identity, "spec_rows": rows,
        "technical_sections": [{"section": s["section"], "text": "; ".join(s["parts"])} for s in sections],
        "raw_specs": raw_specs, "equipment_evidence": evidence, "price_markets": price_markets,
        "technical_snapshot": _snapshot(identity, rows),
    }


def parse_compare_page(html: bytes) -> dict[str, dict]:
    """Return {canonical fiche URL: record} for every column of the comparator."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    table = main.find("table") if main else None
    if table is None or table.find("thead") is None:
        raise ValueError("Comparator table missing")
    head = table.find("thead").find("tr", class_="name")
    columns = []
    for th in head.find_all("th", recursive=False):
        a = th.find("a", href=True)
        url = validate_url(urljoin(BASE_URL + "/", a["href"]), fiche=True)
        columns.append({"url": url, "name": _space(a.get_text(" ", strip=True)),
                        "rows": [], "markets": []})
    section, label = "", ""

    def add(col, sec, lab, value):
        value = _space(value)
        if value in _EMPTY:
            return
        inner_label, inner_value = _split_row(value)
        if inner_label:
            lab, value = inner_label, inner_value
        if value in _EMPTY:
            return
        col["rows"].append({"section": sec, "label": lab, "value": value})

    for tr in table.find("tbody").find_all("tr", recursive=False):
        classes = set(tr.get("class") or [])
        if "title" in classes:
            section, label = _text(tr), ""
            continue
        if "technique-title" in classes:
            label = _text(tr)
            continue
        if section.casefold() in _SKIP_SECTIONS or classes & {"plus", "moins", "texte", "concu"}:
            continue
        cells = tr.find_all("td", recursive=False)
        if len(cells) != len(columns):
            continue
        for col, cell in zip(columns, cells):
            if "millesimes" in classes:
                year = str(_identity(col["name"], col["url"])["year"])
                colors = []
                for timeline in cell.select(".millesime"):
                    year_tag = timeline.select_one(".annee")
                    if not year_tag or _text(year_tag) != year:
                        continue
                    for img in timeline.find_all("img", alt=True):
                        m = re.search(r"\ben couleur\s+(.+)$", img["alt"], re.I)
                        if m and _space(m.group(1)) not in colors:
                            colors.append(_space(m.group(1)))
                for c in colors:
                    col["rows"].append({"section": "Coloris", "label": "Coloris", "value": c})
                continue
            if label == "Prix" or cell.find("table", class_="prices"):
                for t in cell.find_all("table"):
                    heads = [_text(c) for c in t.select("thead th")]
                    for r in t.find_all("tr"):
                        tds = r.find_all("td", recursive=False)
                        if len(tds) < 2:
                            continue
                        country = _text(tds[0])
                        if country and country not in col["markets"]:
                            col["markets"].append(country)
                        for i, td in enumerate(tds[1:], 1):
                            variant = heads[i] if i < len(heads) else ""
                            v = _text(td)
                            if v:
                                col["rows"].append({"section": "Tarifs", "label": " — ".join(p for p in (country, variant) if p), "value": v})
                continue
            if cell.find("dl"):
                for dl in cell.find_all("dl"):
                    for heading, values in _definition_sections(dl):
                        col["rows"].extend({"section": heading, "label": l, "value": v} for l, v in values if v)
                continue
            items = cell.find_all("li")
            sec = "Performances" if label == "Performances" else section
            if items:
                for li in items:
                    add(col, sec, label, _text(li))
            else:
                add(col, sec, label, _text(cell))
    # The "Comparer" criteria list carries a few fields absent from the table
    # (CO2, weight ratios). Values are matched to columns by the full bike name.
    by_name = {col["name"]: col for col in columns}
    criteria = main.select_one("#comparer .liste")
    wanted = {"emission co²": "Emission CO²", "rapport poids / puissance": "Rapport poids / puissance",
              "rapport poids / couple": "Rapport poids / couple"}
    current = None
    for child in criteria.children if criteria else []:
        if getattr(child, "name", None) == "h3":
            current = wanted.get(_space(child.get_text(" ", strip=True)).casefold())
        elif getattr(child, "name", None) == "div" and current:
            span = child.select_one("span.name")
            text = _space(span.get_text(" ", strip=True)) if span else ""
            name, sep, value = text.rpartition(" : ")
            if sep and name in by_name and value not in _EMPTY:
                by_name[name]["rows"].append({"section": "Moteur", "label": current, "value": value})
    out = {}
    for col in columns:
        if not any(r["section"] not in {"Tarifs", "Coloris"} for r in col["rows"]):
            continue  # caller falls back to the individual fiche
        order = list(dict.fromkeys(r["section"] for r in col["rows"]))
        col["rows"].sort(key=lambda r: order.index(r["section"]))  # stable: keeps row order
        out[col["url"]] = _finish(col["url"], _identity(col["name"], col["url"]), col["rows"], col["markets"])
    return out


def crawl_batched(store, client: CompareClient, parse_fiche, *, limit: int | None = 20, on_progress=print) -> dict:
    """Same contract as technical_crawl.crawl, four fiches per paced request.

    A missing column or a record with autonomy falls back to the individual
    fiche, through the same pacing. Autonomy qualifications must come from the
    source, never an inferred or fabricated disclaimer. Errors halt as in crawl.
    """
    import json
    import requests
    from .technical_crawl import SourceBusy, atomic_text

    todo = store.todo()
    if limit is not None:
        todo = todo[:limit]
    attempted = succeeded = fallbacks = consecutive_errors = 0
    halted = None
    try:
        store.report(running=True)
        if (cooldown := store.cooldown_remaining()) > 0:
            todo, halted = [], f"Source cooldown still active for {cooldown:.0f}s"
        for start in range(0, len(todo), MAX_PER_REQUEST):
            batch = todo[start:start + MAX_PER_REQUEST]
            try:
                response, _ = client.get_compare([fiche_id(u) for u in batch])
                response.raise_for_status()
                by_id = {fiche_id(u): (u, rec) for u, rec in parse_compare_page(response.content).items()}
                consecutive_errors = 0
            except SourceBusy as exc:
                store.cooldown(exc.retry_after)
                for u in batch:
                    store.record_error(u, "retryable", str(exc), exc.status, exc.retry_after)
                halted = str(exc)
                break
            except SourceDenied as exc:
                halted = str(exc)
                break
            except (requests.RequestException, ValueError) as exc:
                consecutive_errors += 1
                for u in batch:
                    store.record_error(u, "retryable", f"compare: {exc}", retry_after=60)
                if consecutive_errors >= 3:
                    halted = "Three consecutive network/extraction errors; inspect before resuming"
                    break
                continue
            for url in batch:
                attempted += 1
                hit = by_id.get(fiche_id(url))
                try:
                    # The comparator supplies kilometres but omits the source's
                    # "calculée mais non vérifiée" tooltip. Use the complete
                    # fiche rather than saving a less qualified partial record.
                    has_autonomy = hit and any(
                        "autonomie" in r["label"].casefold() for r in hit[1]["spec_rows"]
                    )
                    if hit and not has_autonomy:
                        canonical, row = hit
                        state = store.record_success(url, row, response, canonical)
                    else:
                        fallbacks += 1
                        fresp, resolved = client.get(url)
                        validate_url(resolved, fiche=True)
                        if fresp.status_code in {404, 410}:
                            store.record_error(url, "terminal", f"HTTP {fresp.status_code}", fresp.status_code)
                            continue
                        fresp.raise_for_status()
                        row = parse_fiche(resolved, fresp.content)
                        if not row.get("spec_rows") or not row.get("technical_snapshot"):
                            raise ValueError("Empty technical extraction")
                        if has_autonomy and not any(
                            "autonomie" in r["label"].casefold() for r in row["spec_rows"]
                        ):
                            raise ValueError("Comparator autonomy missing from individual fiche; inspect source")
                        state = store.record_success(url, row, fresp, resolved)
                    succeeded += state == "success"
                except SourceBusy as exc:
                    store.cooldown(exc.retry_after)
                    store.record_error(url, "retryable", str(exc), exc.status, exc.retry_after)
                    halted = str(exc)
                    break
                except SourceDenied as exc:
                    store.record_error(url, "blocked", str(exc))
                    halted = str(exc)
                    break
                except (requests.RequestException, ValueError) as exc:
                    store.record_error(url, "retryable", str(exc), retry_after=60)
            if halted:
                break
            if succeeded and succeeded % 100 < MAX_PER_REQUEST:
                store.export()
            report = store.report(running=True)
            if on_progress:
                on_progress(json.dumps({"attempted": attempted, "succeeded": succeeded,
                                        "fallbacks": fallbacks, "states": report["states"]}))
    finally:
        store.export()
        report = store.report(running=False)
    report.update({"attempted_this_run": attempted, "succeeded_this_run": succeeded,
                   "fiche_fallbacks_this_run": fallbacks, "halted": halted})
    atomic_text(store.out_dir / "last_run.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report

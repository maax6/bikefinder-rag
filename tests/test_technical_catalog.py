"""Technical evidence contracts without a live DB, service, or model.

HTTP responses and catalog rows are synthetic. The final text is a fixture:
these tests validate tool execution and evidence transport, not LLM quality.
"""

import ast
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bikefinder_rag.agent import tools


LOOP_PATH = Path(__file__).resolve().parents[1] / "src/bikefinder_rag/agent/loop.py"
FIXTURE_ANSWER = "Réponse finale simulée ; aucune génération réelle évaluée."


def catalog_entry(brand="Honda", model="CB 500", year=2000, **changes):
    row = {
        "brand": brand, "model": model, "year": year,
        "category": "Naked bike", "category_fr": None,
        "displacement_ccm": 499.0, "weight_kg": 173.0,
        "power_hp": 58.0, "torque_nm": None, "seat_height_mm": 775.0,
        "url": f"https://catalog.example/{brand.lower()}-{model.replace(' ', '-')}-{year}",
        "scraped_at": datetime(2026, 10, 10, tzinfo=timezone.utc),
        "family_id": 10,
        "raw_specs": {
            "Power": "58.0 HP (42.3 kW) @ 9500 RPM",
            "Dry weight": "173.0 kg (381.4 pounds)",
            "Torque": "Loading...", "Color options": "Red/Black, Blue",
            "Rating": "Rate this motorcycle", "Insurance costs": "Get a quote",
        },
    }
    row.update(changes)
    return row


class CatalogConnection:
    """A small DB-API cursor double over catalog records only.

    It returns tuples and named column descriptions, binds the model/year
    predicates, and respects LIMIT. Accessing another table fails immediately.
    """

    def __init__(self, rows=()):
        self.rows = deepcopy(list(rows))
        self.queries = []
        self.cursor_calls = 0

    def cursor(self):
        self.cursor_calls += 1
        return CatalogCursor(self)


class CatalogCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        sql = " ".join(sql.split())
        self.connection.queries.append((sql, list(params)))
        assert "FROM motorcycles" in sql, "Technical lookup reached another table"
        rows = deepcopy(self.connection.rows)

        def bound(match):
            return params[sql[:match.start()].count("%s")]

        for match in re.finditer(r"\(brand \|\| ' ' \|\| model\) ILIKE %s", sql):
            word = bound(match).strip("%").lower()
            rows = [row for row in rows if word in f"{row['brand']} {row['model']}".lower()]
        for match in re.finditer(r"regexp_replace\(lower\(brand\).*?LIKE %s", sql):
            name = bound(match).strip("%")
            rows = [row for row in rows if name in re.sub(r"[^a-z0-9]", "", row["brand"].lower())]
        for match in re.finditer(r"\byear (>=|<=|=) %s", sql):
            year = bound(match)
            op = match.group(1)
            rows = [row for row in rows if (
                row["year"] >= year if op == ">=" else
                row["year"] <= year if op == "<=" else row["year"] == year
            )]

        if sql.startswith("SELECT count(*)"):
            self.description = [SimpleNamespace(name="count")]
            self.result = [(len(rows),)]
            return
        limit = re.search(r"LIMIT (%s|\d+)", sql)
        if limit:
            rows = rows[:bound(limit) if limit.group(1) == "%s" else int(limit.group(1))]
        selected = sql.removeprefix("SELECT ").split(" FROM ", 1)[0].split(",")
        columns = [name.strip() for name in selected]
        if rows:
            assert all(name in rows[0] for name in columns)
        self.description = [SimpleNamespace(name=name) for name in columns]
        self.result = [tuple(row[name] for name in columns) for row in rows]

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0] if self.result else None


@pytest.fixture
def loop(monkeypatch):
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "300")
    monkeypatch.setenv("OLLAMA_TURN_TIMEOUT_SECONDS", "180")
    spec = importlib.util.spec_from_file_location("technical_catalog_loop", LOOP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tool_calls(*calls):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": name, "arguments": arguments}}
        for name, arguments in calls
    ]}


def simulate_chat(monkeypatch, loop, *responses):
    messages = iter([*responses, {"role": "assistant", "content": FIXTURE_ANSWER}])
    requests = []

    def post(url, *, json, timeout):
        requests.append(deepcopy(json))
        response = Mock()
        response.json.return_value = {"message": next(messages)}
        return response

    monkeypatch.setattr(loop.requests, "post", post)
    return requests


def evidence(history):
    return [ast.literal_eval(message["content"]) for message in history if message["role"] == "tool"]


def assert_technical_transport(requests):
    for request in requests:
        schemas = {item["function"]["name"]: item["function"]["parameters"]
                   for item in request["tools"]}
        assert set(schemas) == {"filter_specs", "get_bike_details", "filter_catalog", "get_catalog_details", "search_technical"}
        assert set(schemas["get_catalog_details"]["required"]) == {"model", "year"}
        assert set(schemas["search_technical"]["required"]) == {"query", "model", "year"}
        assert set(schemas["get_bike_details"]["required"]) == {"model", "year"}
        assert all(schema["additionalProperties"] is False for schema in schemas.values())
        assert schemas["filter_specs"]["properties"]["limit"]["maximum"] == 20


def test_specific_year_sheet_reaches_agent_with_original_measures_and_source(loop, monkeypatch):
    conn = CatalogConnection([
        catalog_entry(year=1999, power_hp=99.0),
        catalog_entry(), catalog_entry(year=2001, power_hp=101.0),
    ])
    family = Mock(side_effect=AssertionError("Family context must stay disabled"))
    reviews = Mock(side_effect=AssertionError("Reviews must stay disabled"))
    monkeypatch.setattr(tools, "_family_context", family)
    monkeypatch.setattr(tools, "search_reviews", reviews)
    requests = simulate_chat(monkeypatch, loop, tool_calls((
        "get_bike_details", {"brand": "Honda", "model": "CB 500", "year": 2000},
    )))

    answer, history = loop.run_agent(conn, None, "Fiche technique de la Honda CB 500 de 2000 ?", provider="ollama")

    row, = evidence(history)[0]
    assert (row["brand"], row["model"], row["year"]) == ("Honda", "CB 500", 2000)
    assert row["power_hp"] == 58.0
    assert row["torque_nm"] is None
    assert row["specs"]["Power"] == "58.0 HP (42.3 kW) @ 9500 RPM"
    assert row["specs"]["Dry weight"] == "173.0 kg (381.4 pounds)"
    assert row["specs"]["Color options"] == "Red/Black, Blue"
    assert "Torque" not in row["specs"]
    assert "Rating" not in row["specs"] and "Insurance costs" not in row["specs"]
    assert row["url"] == catalog_entry()["url"]
    assert row["scraped_at"].startswith("2026-10-10")
    assert "year = %s" in conn.queries[0][0] and 2000 in conn.queries[0][1]
    assert len(conn.queries) == 1
    assert requests[1]["messages"][-1] == next(message for message in history if message["role"] == "tool")
    assert_technical_transport(requests)
    family.assert_not_called()
    reviews.assert_not_called()
    assert answer == FIXTURE_ANSWER


def test_same_year_comparison_keeps_sources_missing_values_and_weight_qualifiers(loop, monkeypatch):
    other = catalog_entry(
        brand="Kawasaki", model="ER-5", weight_kg=196.0, power_hp=50.0,
        raw_specs={"Power": "50.0 HP (36.5 kW)", "Weight incl. oil, gas, etc": "196.0 kg"},
    )
    conn = CatalogConnection([catalog_entry(), other, catalog_entry(year=2001, power_hp=101.0)])
    requests = simulate_chat(monkeypatch, loop, tool_calls(
        ("get_bike_details", {"brand": "Honda", "model": "CB 500", "year": 2000}),
        ("get_bike_details", {"brand": "Kawasaki", "model": "ER-5", "year": 2000}),
    ))

    answer, history = loop.run_agent(
        conn, None, "Compare puissance, couple et poids de la CB 500 et de l'ER-5 en 2000.", provider="ollama",
    )

    first, second = [rows[0] for rows in evidence(history)]
    assert [row["model"] for row in (first, second)] == ["CB 500", "ER-5"]
    assert {first["year"], second["year"]} == {2000}
    assert [row["power_hp"] for row in (first, second)] == [58.0, 50.0]
    assert first["torque_nm"] is None and second["torque_nm"] is None
    assert first["specs"]["Dry weight"] == "173.0 kg (381.4 pounds)"
    assert second["specs"]["Weight incl. oil, gas, etc"] == "196.0 kg"
    assert first["url"] != second["url"]
    assert len(conn.queries) == 2
    assert all("year = %s" in sql and 2000 in params for sql, params in conn.queries)
    transported = [message for message in requests[-1]["messages"] if message["role"] == "tool"]
    assert [ast.literal_eval(message["content"])[0] for message in transported] == [first, second]
    assert_technical_transport(requests)
    assert answer == FIXTURE_ANSWER


def test_year_filter_is_bounded_but_count_keeps_every_matching_catalog_entry(loop, monkeypatch):
    conn = CatalogConnection([
        *[catalog_entry(model=f"Fixture {index}") for index in range(29)],
        catalog_entry(year=1999), catalog_entry(year=2001),
    ])
    requests = simulate_chat(monkeypatch, loop,
        tool_calls(("filter_specs", {"min_year": 2000, "max_year": 2000, "limit": 20})),
        tool_calls(("filter_specs", {"min_year": 2000, "max_year": 2000, "count_only": True})),
    )

    _, history = loop.run_agent(conn, None, "Motos du millésime 2000 et combien de fiches ?", provider="ollama")

    listed, counted = evidence(history)
    assert len(listed) == 20
    assert {row["year"] for row in listed} == {2000}
    assert all(row["url"] and row["specs"]["Power"] and row["specs"]["Dry weight"] for row in listed)
    assert counted == [{"matching_motorcycles": 29}]
    assert "year >= %s" in conn.queries[0][0] and "year <= %s" in conn.queries[0][0]
    assert conn.queries[0][1] == [2000, 2000, 20]
    assert conn.queries[1][1] == [2000, 2000]
    assert_technical_transport(requests)


def test_hallucinated_review_call_is_blocked_before_search_or_sql(loop, monkeypatch):
    conn = CatalogConnection()
    reviews = Mock(side_effect=AssertionError("Review retrieval was executed"))
    monkeypatch.setattr(tools, "search_reviews", reviews)
    requests = simulate_chat(monkeypatch, loop, tool_calls((
        "search_reviews", {"query": "CB 500 specifications", "model": "CB 500"},
    )))

    answer, history = loop.run_agent(conn, None, "Fiche CB 500 2000", provider="ollama")

    result, = evidence(history)[0]
    assert "error" in result and "disabled" in result["error"].lower()
    assert conn.cursor_calls == 0
    reviews.assert_not_called()
    assert_technical_transport(requests)
    assert answer == FIXTURE_ANSWER


def test_prior_review_evidence_is_not_reinjected_into_technical_turn(loop, monkeypatch):
    history = [
        {"role": "user", "content": "Anciens avis sur la CB 500 ?"},
        tool_calls(("search_reviews", {"query": "CB 500 owner opinions"})),
        {"role": "tool", "content": "[{'comment_text': 'UNTRUSTED_OWNER_OPINION'}]"},
        {"role": "assistant", "content": "UNTRUSTED_OWNER_SUMMARY"},
    ]
    original = deepcopy(history)
    requests = simulate_chat(monkeypatch, loop)

    answer, _ = loop.run_agent(
        CatalogConnection(), None, "Maintenant la fiche technique CB 500 2000.", history, provider="ollama",
    )

    transported = repr(requests[0]["messages"])
    assert "search_reviews" not in transported
    assert "UNTRUSTED_OWNER_OPINION" not in transported
    assert "UNTRUSTED_OWNER_SUMMARY" not in transported
    assert history == original
    assert answer == FIXTURE_ANSWER


@pytest.mark.parametrize("name,arguments", [
    ("filter_specs", {"abs": True}),
    ("filter_specs", {"a2_only": True}),
    ("filter_specs", {"min_year": True}),
    ("filter_specs", {"max_year": "2000"}),
    ("filter_specs", {"min_year": -1}),
    ("filter_specs", {"min_year": 2001, "max_year": 2000}),
    ("filter_specs", {"min_weight_kg": 200, "max_weight_kg": 150}),
    ("filter_specs", {"min_torque_nm": 50, "max_torque_nm": 40}),
    ("filter_specs", {"min_displacement_ccm": -1}),
    ("filter_specs", {"max_power_hp": float("nan")}),
    ("filter_specs", {"max_power_hp": float("inf")}),
    ("filter_specs", {"max_power_hp": 10 ** 1000}),
    ("filter_specs", {"count_only": "true"}),
    ("filter_specs", {"brand": []}),
    ("filter_specs", {"limit": 0}),
    ("filter_specs", {"limit": 21}),
    ("filter_specs", {"limit": 1.5}),
    ("filter_specs", {"order_by": "maximum_speed"}),
    ("filter_specs", {"order_by": "power_hp; DROP TABLE motorcycles"}),
    ("filter_specs", {"order_by": "--year"}),
    ("filter_specs", []),
    ("get_bike_details", {"model": "CB 500"}),
    ("get_bike_details", {"year": 2000}),
    ("get_bike_details", {"model": "", "year": 2000}),
    ("get_bike_details", {"model": "CB 500", "year": True}),
    ("get_bike_details", {"model": "CB 500", "year": "2000"}),
    ("get_bike_details", {"models": ["CB 500", "ER-5"], "year": 2000}),
    ("get_bike_details", {"model": "CB 500", "year": 2000, "include_family_context": True}),
    ("compare_bikes", {"year": 2000}),
])
def test_invalid_technical_arguments_return_error_without_opening_a_cursor(name, arguments):
    conn = CatalogConnection()

    results = tools.execute_tool(conn, name, arguments)

    assert len(results) == 1
    assert isinstance(results[0].get("error"), str)
    assert conn.cursor_calls == 0


def test_safe_alias_is_reported_without_dropping_the_requested_year():
    conn = CatalogConnection([catalog_entry(), catalog_entry(year=2001)])

    notes, row = tools.execute_tool(conn, "get_bike_details", {"models": "CB 500", "year": 2000})

    assert "models" in repr(notes["notes"]) and "model" in repr(notes["notes"])
    assert row["year"] == 2000 and row["model"] == "CB 500"
    assert "year = %s" in conn.queries[0][0] and 2000 in conn.queries[0][1]


def test_precise_variant_name_selects_n_without_using_s_specs():
    n_variant = catalog_entry(
        brand="Suzuki", model="GSF 1200 N Bandit", power_hp=60.0,
        raw_specs={"Power": "60.0 HP", "Dry weight": "200.0 kg"},
    )
    s_variant = catalog_entry(
        brand="Suzuki", model="GSF 1200 S Bandit", power_hp=61.0,
        raw_specs={"Power": "61.0 HP", "Dry weight": "210.0 kg"},
    )
    # Loose matching of 'N' also finds the letter in 'Bandit' on the S row.
    conn = CatalogConnection([s_variant, n_variant])

    row, = tools.execute_tool(conn, "get_bike_details", {
        "model": "GSF 1200 N Bandit", "brand": "Suzuki", "year": 2000,
    })

    assert row["model"] == "GSF 1200 N Bandit"
    assert row["power_hp"] == 60.0
    assert row["specs"] == {"Power": "60.0 HP", "Dry weight": "200.0 kg"}
    assert row["url"] == n_variant["url"]


def test_missing_requested_year_returns_no_sheet_without_falling_back():
    conn = CatalogConnection([catalog_entry(year=1999), catalog_entry(year=2001)])

    results = tools.execute_tool(conn, "get_bike_details", {"model": "CB 500", "year": 2000})

    assert results == []
    assert len(conn.queries) == 1
    assert "year = %s" in conn.queries[0][0] and 2000 in conn.queries[0][1]


def test_ambiguous_short_name_keeps_variants_separate_and_reports_truncation():
    variants = [catalog_entry(
        brand="Suzuki", model=f"GSF 1200 {suffix} Bandit", power_hp=60.0 + index,
        raw_specs={"Power": f"{60 + index}.0 HP"},
    ) for index, suffix in enumerate(("N", "S", "N ABS", "S ABS", "Special"))]
    conn = CatalogConnection(variants)

    results = tools.execute_tool(conn, "get_bike_details", {
        "model": "GSF 1200", "brand": "Suzuki", "year": 2000,
    })

    rows, notice = results[:-1], results[-1]
    assert len(rows) == 3
    assert len({row["model"] for row in rows}) == 3
    assert len({row["url"] for row in rows}) == 3
    assert all(row["specs"]["Power"] == f"{row['power_hp']:.1f} HP" for row in rows)
    assert notice["truncated"] is True
    assert "variant" in notice["info"].lower()


def test_legacy_reviews_require_explicit_opt_in(monkeypatch):
    rows = [{"model_family": "CB 500", "comment_text": "Synthetic owner opinion."}]
    reviews = Mock(return_value=rows)
    monkeypatch.setattr(tools, "search_reviews", reviews)

    blocked = tools.execute_tool(None, "search_reviews", {"query": "reliability"})
    reviews.assert_not_called()
    enabled = tools.execute_tool(None, "search_reviews", {"query": "reliability"}, allow_reviews=True)

    assert "error" in blocked[0]
    assert enabled == rows
    reviews.assert_called_once_with(None, query="reliability")


def test_legacy_family_context_requires_explicit_opt_in(monkeypatch):
    context = {"known_us_recalls_total": 2, "used_price_estimate": {"price_median_eur": 1500}}
    family = Mock(return_value=context)
    monkeypatch.setattr(tools, "_family_context", family)
    conn = CatalogConnection([catalog_entry()])

    technical = tools.get_bike_details(conn, "CB 500", year=2000)
    family.assert_not_called()
    legacy = tools.get_bike_details(conn, "CB 500", year=2000, include_family_context=True)

    assert len(technical) == 1
    assert legacy == [*technical, context]
    family.assert_called_once_with(conn, [10])

"""Exercise catalog coverage and fresh numeric values on an in-memory SQL fixture."""
import json
import sqlite3

import pytest

from bikefinder_rag.catalog import enriched
from bikefinder_rag.catalog.measures import FIELDS, filtered


@pytest.fixture
def catalog(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE technical_fiches (
            id TEXT PRIMARY KEY, brand TEXT, model TEXT, year INTEGER,
            source_url TEXT, record TEXT, source_sha256 TEXT
        );
        CREATE TABLE technical_equipment (
            object_id TEXT, equipment TEXT, status TEXT
        );
    """)
    numeric_columns = ", ".join(f"{field} REAL" for field in FIELDS)
    conn.execute(f"""CREATE TABLE technical_measures (
        object_id TEXT PRIMARY KEY, {numeric_columns}, proof TEXT,
        version TEXT, source_sha256 TEXT
    )""")
    fiches = [
        ("current", "Fixture", "Current", 2024, "https://example.test/current", "{}", "current-source"),
        ("stale", "Fixture", "Stale", 2024, "https://example.test/stale", "{}", "updated-source"),
        ("missing", "Fixture", "Missing", 2024, "https://example.test/missing", "{}", "missing-source"),
        ("other-year", "Fixture", "Other", 2023, "https://example.test/other", "{}", "other-source"),
    ]
    conn.executemany("INSERT INTO technical_fiches VALUES (?, ?, ?, ?, ?, ?, ?)", fiches)
    conn.executemany("INSERT INTO technical_equipment VALUES (?, 'ABS', 'standard')",
                     [(row[0],) for row in fiches])
    conn.executemany("INSERT INTO technical_equipment VALUES (?, 'shifter', ?)", [
        ("current", "standard"), ("stale", "optional"), ("other-year", "unknown"),
    ])
    conn.executemany("""INSERT INTO technical_measures
        (object_id, price_eur, power_ch, proof, version, source_sha256)
        VALUES (?, ?, ?, ?, 'fixture', ?)""", [
            ("current", 7000, 60, json.dumps({"price_eur": [{"value": "7000 €"}]}), "current-source"),
            ("stale", 2000, 120, json.dumps({"price_eur": [{"value": "2000 €"}]}), "old-source"),
            ("other-year", 3000, 80, "{}", "other-source"),
        ])

    def sql_rows(db, sql, params):
        # Only adapt placeholders; the selection and join logic executes as SQL.
        output = [dict(row) for row in db.execute(sql.replace("%s", "?"), params)]
        for row in output:
            for key in ("record", "proof"):
                if isinstance(row.get(key), str):
                    row[key] = json.loads(row[key])
        return output

    monkeypatch.setattr(enriched, "_rows", sql_rows)
    yield conn
    conn.close()


@pytest.mark.parametrize("equipment", [None, "ABS"])
def test_identity_or_equipment_counts_include_unprojected_fiches(catalog, equipment):
    assert filtered(catalog, [], identity={"year": 2024}, equipment=equipment, count=True) == 3


def test_unprojected_rows_keep_identity_without_stale_numbers_or_proof(catalog):
    rows = filtered(catalog, [], identity={"year": 2024}, equipment="ABS")
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {"current", "stale", "missing"}
    assert by_id["current"]["price_eur"] == 7000
    assert by_id["current"]["proof"]["price_eur"]
    for key in ("stale", "missing"):
        assert all(by_id[key][field] is None for field in FIELDS)
        assert by_id[key]["proof"] == {}
        assert by_id[key]["source_url"] == f"https://example.test/{key}"


def test_numeric_filter_counts_and_lists_require_current_projection(catalog):
    conditions = [{"field": "price_eur", "op": ">=", "value": 1000}]
    kwargs = {"identity": {"year": 2024}, "equipment": "ABS"}
    assert filtered(catalog, conditions, **kwargs, count=True) == 1
    assert [row["id"] for row in filtered(catalog, conditions, **kwargs)] == ["current"]
    assert filtered(catalog, [{"field": "price_eur", "op": "<", "value": 5000}],
                    **kwargs, count=True) == 0


def test_numeric_ranking_counts_and_lists_require_current_projection(catalog):
    kwargs = {"identity": {"year": 2024}, "order_by": "-power_ch"}
    assert filtered(catalog, [], **kwargs, count=True) == 1
    assert [row["id"] for row in filtered(catalog, [], **kwargs)] == ["current"]


@pytest.mark.parametrize(("status", "expected"), [
    ("standard", {"current"}),
    ("optional", {"stale"}),
    ("present", {"current", "stale"}),
    ("unknown", {"missing"}),
    ("explicitly_absent", set()),
])
def test_equipment_intersection_preserves_each_status_and_unknown_policy(catalog, status, expected):
    kwargs = {"identity": {"year": 2024}, "equipment_filters": [
        {"equipment": "ABS", "status": "standard"},
        {"equipment": "shifter", "status": status},
    ]}
    assert filtered(catalog, [], **kwargs, count=True) == len(expected)
    assert {row["id"] for row in filtered(catalog, [], **kwargs)} == expected


def test_legacy_equipment_and_new_filters_are_additive(catalog):
    rows = filtered(catalog, [], identity={"year": 2024}, equipment="ABS",
                    equipment_filters=[{"equipment": "shifter", "status": "optional"}])
    assert [row["id"] for row in rows] == ["stale"]
    assert rows[0]["proof"] == {}


def test_equipment_name_remains_a_bound_sql_value(catalog):
    name = "ABS'); DROP TABLE technical_fiches; --"
    assert filtered(catalog, [], identity={"year": 2024}, equipment_filters=[
        {"equipment": name, "status": "standard"}], count=True) == 0
    assert filtered(catalog, [], identity={"year": 2024}, count=True) == 3


@pytest.mark.parametrize("equipment_filters", [
    "ABS", [None], [{}], [{"equipment": "", "status": "standard"}],
    [{"equipment": "ABS", "status": "available"}],
    [{"equipment": "ABS", "status": ["standard"]}],
    [{"equipment": ["ABS"], "status": "standard"}],
    [{"equipment": "ABS", "status": "standard"}] * 5,
])
def test_invalid_equipment_filters_fail_before_sql(catalog, monkeypatch, equipment_filters):
    def unexpected_query(*args):
        raise AssertionError("Invalid filters reached SQL")

    monkeypatch.setattr(enriched, "_rows", unexpected_query)
    with pytest.raises(ValueError):
        filtered(catalog, [], equipment_filters=equipment_filters)


def test_total_equipment_limit_includes_legacy_filter(catalog):
    with pytest.raises(ValueError):
        filtered(catalog, [], equipment="ABS", equipment_filters=[
            {"equipment": "shifter", "status": "standard"}] * 4)

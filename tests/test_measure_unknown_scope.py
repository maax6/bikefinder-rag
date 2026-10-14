"""Unknown numeric evidence is opt-in; other bounds and freshness stay strict."""
import json
import re
import sqlite3

import pytest

from bikefinder_rag.catalog import enriched
from bikefinder_rag.catalog.measures import FIELDS, filtered


@pytest.fixture
def catalog(monkeypatch):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE technical_fiches(id TEXT PRIMARY KEY,brand TEXT,model TEXT,
            year INTEGER,source_url TEXT,record TEXT,source_sha256 TEXT);
        CREATE TABLE technical_equipment(object_id TEXT,equipment TEXT,status TEXT);
    ''')
    numeric = ','.join(field + ' REAL' for field in FIELDS)
    conn.execute('CREATE TABLE technical_measures(object_id TEXT PRIMARY KEY,' + numeric +
                 ',proof TEXT,version TEXT,source_sha256 TEXT)')
    # id, price, seat, power, projection freshness
    rows = [('known', 7000, 780, 60, 'fresh'), ('price-null', None, 780, 60, 'fresh'),
            ('seat-null', 7500, None, 60, 'fresh'), ('both-null', None, None, 60, 'fresh'),
            ('expensive', 9500, None, 60, 'fresh'), ('power-null', None, None, None, 'fresh'),
            ('stale', None, None, 60, 'old'), ('unprojected', None, None, None, None)]
    for identity, price, seat, power, projection in rows:
        conn.execute('INSERT INTO technical_fiches VALUES(?,?,?,?,?,?,?)',
                     (identity, 'Fixture', identity, 2024, 'https://example.test/' + identity, '{}', 'fresh'))
        if projection:
            proof = {'price_eur': [{'value': str(price) + ' €'}]} if price is not None else {}
            conn.execute('''INSERT INTO technical_measures
                (object_id,price_eur,seat_height_mm,power_ch,proof,version,source_sha256)
                VALUES(?,?,?,?,?,'fixture',?)''', (identity, price, seat, power, json.dumps(proof), projection))

    def sql_rows(db, query, params):
        if 'f.id = ANY(%s)' in query:
            # Real SQL selection with one bound array-equivalent JSON value.
            before = query[:query.index('f.id = ANY(%s)')].count('%s')
            params = list(params)
            params[before] = json.dumps(params[before])
            query = query.replace('f.id = ANY(%s)', 'f.id IN (SELECT value FROM json_each(%s))')
        result = [dict(row) for row in db.execute(query.replace('%s', '?'), params)]
        for row in result:
            for key in ('record', 'proof'):
                if isinstance(row.get(key), str):
                    row[key] = json.loads(row[key])
        return result

    monkeypatch.setattr(enriched, '_rows', sql_rows)
    yield conn
    conn.close()


BOUNDS = [{'field': 'price_eur', 'op': '<', 'value': 9000},
          {'field': 'seat_height_mm', 'op': '<=', 'value': 800},
          {'field': 'power_ch', 'op': '>=', 'value': 50}]


def test_default_bounds_still_exclude_every_missing_or_stale_value(catalog):
    assert [row['id'] for row in filtered(catalog, BOUNDS)] == ['known']
    assert filtered(catalog, BOUNDS, count=True) == 1


def test_unknown_fields_are_explicit_and_other_bounds_stay_strict(catalog):
    result = filtered(catalog, BOUNDS, unknown_fields=['price_eur'])
    assert {row['id'] for row in result} == {'known', 'price-null'}
    result = filtered(catalog, BOUNDS, unknown_fields=['price_eur', 'seat_height_mm'])
    assert {row['id'] for row in result} == {'known', 'price-null', 'seat-null', 'both-null'}
    # Price=9500 still violates the price bound; power NULL still violates its
    # separate strict bound. Old/missing projection is not current unknown data.
    assert not {'expensive', 'power-null', 'stale', 'unprojected'} & {row['id'] for row in result}
    assert filtered(catalog, BOUNDS, unknown_fields=['price_eur', 'seat_height_mm'], count=True) == 4


def test_missing_bucket_is_disjoint_from_complete_answers(catalog):
    result = filtered(catalog, BOUNDS, unknown_fields=['price_eur', 'seat_height_mm'], missing_only=True)
    assert {row['id'] for row in result} == {'price-null', 'seat-null', 'both-null'}
    assert filtered(catalog, BOUNDS, unknown_fields=['price_eur', 'seat_height_mm'], missing_only=True, count=True) == 3
    by_id = {row['id']: row for row in result}
    assert by_id['price-null']['price_eur'] is None and by_id['price-null']['proof'] == {}
    assert by_id['seat-null']['price_eur'] == 7500 and by_id['seat-null']['proof']['price_eur']


def test_missing_only_without_bounded_field_uses_current_projection(catalog):
    result = filtered(catalog, [], unknown_fields=['price_eur'], missing_only=True)
    assert {row['id'] for row in result} == {'price-null', 'both-null', 'power-null'}
    assert not {'stale', 'unprojected'} & {row['id'] for row in result}


def test_id_scope_intersects_before_count_and_limit(catalog):
    ids = ['price-null', 'known', 'expensive', 'known']
    result = filtered(catalog, BOUNDS, object_ids=ids, unknown_fields=['price_eur'])
    assert [row['id'] for row in result] == ['known', 'price-null']
    assert filtered(catalog, BOUNDS, object_ids=ids, unknown_fields=['price_eur'], count=True) == 2
    assert len(filtered(catalog, BOUNDS, object_ids=ids, unknown_fields=['price_eur'], limit=1)) == 1
    assert filtered(catalog, [], object_ids=[], count=True) == 0


def test_ids_remain_sql_parameters(catalog):
    value = "known'); DROP TABLE technical_fiches; --"
    assert filtered(catalog, [], object_ids=[value], count=True) == 0
    assert filtered(catalog, [], count=True) == 8


def test_ranking_keeps_existing_null_policy(catalog):
    result = filtered(catalog, BOUNDS, unknown_fields=['price_eur', 'seat_height_mm'], order_by='price_eur')
    assert [row['id'] for row in result] == ['known', 'seat-null']
    assert all(row['price_eur'] is not None for row in result)


@pytest.mark.parametrize('kwargs', [
    {'object_ids': 'known'}, {'object_ids': [1]}, {'object_ids': ['']},
    {'unknown_fields': 'price_eur'}, {'unknown_fields': ['year']},
    {'unknown_fields': ['price_eur; DROP TABLE technical_fiches']},
    {'unknown_fields': [None]}, {'missing_only': True}, {'missing_only': 'yes'},
])
def test_invalid_scope_flags_fail_before_sql(monkeypatch, kwargs):
    monkeypatch.setattr(enriched, '_rows', lambda *args: pytest.fail('Invalid filter reached SQL'))
    with pytest.raises(ValueError):
        filtered(None, [], **kwargs)

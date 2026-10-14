"""The progress view must describe the live collector without changing its queue."""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shlex
import sqlite3
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/monitor_technical_collection.py"
spec = importlib.util.spec_from_file_location("collection_monitor", SCRIPT)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def create_collection(tmp_path, pages):
    out = tmp_path / "collection"
    out.mkdir()
    with sqlite3.connect(out / "crawl.sqlite3") as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""CREATE TABLE pages (
            url TEXT PRIMARY KEY, ordinal INTEGER NOT NULL, year INTEGER NOT NULL,
            state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT, status INTEGER, error TEXT, retry_at REAL DEFAULT 0,
            parser_version TEXT, result TEXT)""")
        connection.execute("CREATE TABLE source_state(key TEXT PRIMARY KEY, value REAL NOT NULL)")
        for index, (state, updated_at) in enumerate(pages):
            record = {"identity": {"brand": "Honda", "model": f"Example {index}", "year": 2000},
                      "collection": {"collected_at": updated_at}, "spec_rows": []}
            connection.execute("""INSERT INTO pages
                (url,ordinal,year,state,updated_at,status,result,attempts) VALUES (?,?,?,?,?,?,?,?)""",
                (f"https://www.motoplanete.com/honda/{index}/Example-2000/contact.html",
                 index, 2000, state, updated_at, 200 if state == "success" else None,
                 json.dumps(record) if state in {"success", "needs_review"} else None,
                 1 if updated_at else 0))
    (out / "pid.txt").write_text("12345\n")
    (out / "status.json").write_text(json.dumps({
        "running": True, "updated_at": NOW.isoformat(),
        "states": {"success": 9999}, "discovered": 9999,
    }))
    return out


def stamp(seconds):
    return (NOW - timedelta(seconds=seconds)).isoformat()


def test_obsolete_running_flag_cannot_make_a_dead_collector_active(tmp_path):
    out = create_collection(tmp_path, [("success", stamp(10)), ("pending", None)])

    progress = monitor.read_progress(out, now=NOW, process_checker=lambda pid, path: False)

    assert progress["process"] == {"pid": 12345, "alive": False}
    assert progress["activity"]["kind"] not in {"running", "active", "collecting"}
    assert progress["eta_seconds"] is None
    assert progress["success"] == 1
    assert progress["total"] == 2


def test_last_success_uses_identity_and_survives_a_newer_failed_attempt(tmp_path):
    out = create_collection(tmp_path, [('success', stamp(30)), ('retryable', stamp(5))])
    result = monitor.read_progress(out, now=NOW, process_checker=lambda *args: True)
    assert result['last_success']['state'] == 'success'
    assert result['last_success']['name'] == 'Honda Example 0 2000'
    assert result['last_success']['updated_at'] == stamp(30)
    assert result['last_records'][0]['state'] == 'retryable'


def test_recent_rate_ignores_the_older_pilot_and_estimates_remaining_work(tmp_path):
    pages = [("success", stamp(4 * 3600))]
    pages += [("success", stamp(seconds)) for seconds in (50, 40, 30, 20, 10)]
    pages += [("pending", None)] * 100
    out = create_collection(tmp_path, pages)

    progress = monitor.read_progress(out, now=NOW, process_checker=lambda pid, path: True)

    assert progress["rate_per_hour"] == pytest.approx(360)
    assert progress["eta_seconds"] == pytest.approx(1000)
    assert progress["minimum_remaining_seconds"] == 1000
    assert progress["success"] == 6


def test_remaining_and_success_do_not_include_rejected_or_review_records(tmp_path):
    pages = [("success", stamp(seconds)) for seconds in (40, 30, 20, 10)]
    pages += [("pending", None)] * 2
    pages += [("retryable", stamp(100)), ("quarantined", None),
              ("terminal", stamp(90)), ("needs_review", stamp(80))]
    out = create_collection(tmp_path, pages)

    progress = monitor.read_progress(out, now=NOW, process_checker=lambda pid, path: True)

    assert progress["remaining"] == 3
    assert progress["total"] == 10
    assert progress["success"] == 4
    assert progress["progress_percent"] == pytest.approx(40)
    assert progress["counts"]["quarantined"] == 1
    assert progress["counts"]["needs_review"] == 1
    assert progress["minimum_remaining_seconds"] == 30


def test_a_live_process_without_recent_data_has_no_live_eta(tmp_path):
    out = create_collection(tmp_path, [
        ("success", stamp(3600 + index * 10)) for index in range(5)
    ] + [("pending", None)] * 20)

    progress = monitor.read_progress(out, now=NOW, process_checker=lambda pid, path: True)

    assert progress["process"]["alive"] is True
    assert progress["eta_seconds"] is None
    assert progress["activity"]["kind"] not in {"running", "active", "collecting"}


@pytest.mark.parametrize("mode,expected", [
    ("unrelated", False), ("other_collection", False), ("expected_collection", True),
])
def test_pid_presence_requires_the_expected_collector_and_output(tmp_path, monkeypatch, mode, expected):
    out = tmp_path / "collection"
    script = "scripts/unrelated.py" if mode == "unrelated" else "scripts/collect_technical_data.py"
    target = tmp_path / "other" if mode == "other_collection" else out
    command = shlex.join(["python3", script, "--out", str(target), "--all"])
    monkeypatch.setattr(monitor.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=command + "\n", stderr="",
    ))

    assert monitor.collector_process_alive(12345, out) is expected


def test_monitor_reads_committed_wal_data_through_a_readonly_connection(tmp_path, monkeypatch):
    out = create_collection(tmp_path, [("pending", None)])
    writer = sqlite3.connect(out / "crawl.sqlite3")
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("UPDATE pages SET state='success',updated_at=?", (stamp(10),))
    writer.commit()
    real_connect = sqlite3.connect
    queries = []
    connect_args = []

    class ObservedConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            queries.append(sql)
            assert sql.lstrip().split()[0].upper() not in {
                "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "REPLACE", "VACUUM",
            }
            return super().execute(sql, *args, **kwargs)

    def observed_connect(database, *args, **kwargs):
        connect_args.append((database, kwargs.copy()))
        kwargs["factory"] = ObservedConnection
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(monitor.sqlite3, "connect", observed_connect)
    try:
        progress = monitor.read_progress(out, now=NOW, process_checker=lambda pid, path: True)
        assert progress["success"] == 1
        assert progress["remaining"] == 0
        assert connect_args and all("mode=ro" in str(database) and options.get("uri")
                                    for database, options in connect_args)
        assert any("query_only" in query.lower() for query in queries)
        assert writer.execute("SELECT state FROM pages").fetchone()[0] == "success"
    finally:
        writer.close()

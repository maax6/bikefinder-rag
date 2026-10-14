#!/usr/bin/env python3
"""Local, read-only live view of the technical collection.

Run: .venv/bin/python scripts/monitor_technical_collection.py --port 7861
The collector continues independently of this monitor.
"""

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shlex
import sqlite3
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data/technical/motoplanete"
HTML = Path(__file__).with_name("collection_monitor.html")


def collector_process_alive(pid: int, out_dir: Path) -> bool | None:
    """Check the command as well as the PID, which may have been reused."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None if result.stderr.strip() else False
    try:
        args = shlex.split(result.stdout.strip())
        script = any(Path(arg).name == "collect_technical_data.py" for arg in args)
        if not script:
            return False
        target = Path(args[args.index("--out") + 1]) if "--out" in args else DEFAULT_OUT
        if not target.is_absolute():
            target = ROOT / target
        return target.resolve() == out_dir.resolve()
    except (ValueError, IndexError):
        return None


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def _progress_record(row):
    parsed = json.loads(row["result"]) if row["result"] else {}
    identity = parsed.get("identity", {})
    name = identity.get("raw_name") or " ".join(
        str(identity[key]) for key in ("brand", "model", "year") if identity.get(key) is not None
    ) or "Fiche sans identité"
    return {
        "name": str(name)[:300], "year": row["year"], "url": row["url"],
        "state": row["state"], "updated_at": row["updated_at"],
        "error": row["error"], "http_status": row["status"],
    }


def read_progress(out_dir: Path, *, now=None, process_checker=collector_process_alive) -> dict:
    now = now or datetime.now(timezone.utc)
    database = out_dir.resolve() / "crawl.sqlite3"
    # A short WAL read transaction never calls the collector's writable store.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        counts = dict(conn.execute("SELECT state,count(*) FROM pages GROUP BY state"))
        updated_at = conn.execute("SELECT max(updated_at) FROM pages").fetchone()[0]
        recent = list(conn.execute(
            "SELECT url,year,state,updated_at,status,error,result FROM pages "
            "WHERE attempts>0 ORDER BY updated_at DESC LIMIT 8"
        ))
        last_success = conn.execute(
            "SELECT url,year,state,updated_at,status,error,result FROM pages "
            "WHERE state='success' ORDER BY updated_at DESC,ordinal DESC LIMIT 1"
        ).fetchone()
        cutoff = (now - timedelta(minutes=20)).isoformat()
        times = [row[0] for row in conn.execute(
            "SELECT updated_at FROM pages WHERE state IN ('success','needs_review') "
            "AND updated_at>=? ORDER BY updated_at DESC LIMIT 120", (cutoff,)
        )]
        years = [dict(row) for row in conn.execute(
            "SELECT year,count(*) AS total,sum(state='success') AS success "
            "FROM pages WHERE state!='quarantined' GROUP BY year ORDER BY year"
        )]
        conn.rollback()
    pid = None
    try:
        pid = int((out_dir / "pid.txt").read_text().strip())
        if pid <= 0:
            pid = None
    except (OSError, ValueError):
        pass
    alive = process_checker(pid, out_dir) if pid else False
    remaining = counts.get("pending", 0) + counts.get("retryable", 0)
    total = sum(counts.values())
    success = counts.get("success", 0)
    last = _timestamp(updated_at)
    age = max(0, (now - last).total_seconds()) if last else None
    fresh = age is not None and age <= 120
    rate = None
    timestamps = [t for value in times if (t := _timestamp(value)) is not None and t <= now]
    if len(timestamps) >= 5:
        duration = (max(timestamps) - min(timestamps)).total_seconds()
        if duration > 0:
            rate = (len(timestamps) - 1) * 3600 / duration
    if not remaining:
        label, kind = "Lot parcouru", "complete"
    elif alive is False:
        label, kind = "Collecteur arrêté", "stopped"
    elif alive is None:
        label, kind = "Processus à confirmer", "unknown"
    elif not fresh:
        label, kind = "Actif · aucune fiche récente", "waiting"
    else:
        label, kind = "Collecte en cours", "running"
    records = [_progress_record(row) for row in recent]
    return {
        "server_time": now.isoformat(), "updated_at": updated_at,
        "source": "Motoplanete", "counts": counts, "total": total,
        "success": success, "remaining": remaining,
        "progress_percent": success * 100 / total if total else 0,
        "process": {"pid": pid, "alive": alive},
        "activity": {"label": label, "kind": kind}, "last_activity_age_seconds": age,
        "rate_per_hour": rate,
        "eta_seconds": remaining * 3600 / rate if rate and fresh and alive is True else None,
        "minimum_remaining_seconds": remaining * 10,
        "out_dir": str(out_dir.resolve()), "last_records": records, "years": years,
        "last_success": _progress_record(last_success) if last_success else None,
    }


class MonitorHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, out_dir=DEFAULT_OUT, **kwargs):
        self.out_dir = out_dir
        super().__init__(*args, **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == "/":
                payload, content_type = HTML.read_bytes(), "text/html; charset=utf-8"
            elif path == "/api/progress":
                payload = json.dumps(read_progress(self.out_dir), ensure_ascii=False).encode()
                content_type = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.send_response(503)
            payload = json.dumps({"error": str(exc)}, ensure_ascii=False).encode()
            content_type = "application/json; charset=utf-8"
        else:
            self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--port", type=int, default=7861)
    args = parser.parse_args()
    if not (args.out / "crawl.sqlite3").is_file():
        parser.error("No collection database found at --out")
    handler = partial(MonitorHandler, out_dir=args.out.resolve())
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Collection monitor: http://127.0.0.1:{args.port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

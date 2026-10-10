#!/usr/bin/env python3
"""Collect technical source records, without modifying the chat database.

Pilot: --urls-file data/motoplanete/fiche_urls.txt --limit 20
Full discovery/crawl: --refresh-sitemaps --all
Resume: same --out and --all; successful pages are never downloaded again.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal

from bikefinder_rag.scraper.motoplanete_technical import parse_technical_page
from bikefinder_rag.scraper.technical_crawl import (
    CrawlStore, HostAccessState, PoliteClient, SourceBusy, atomic_text, crawl, discover_fiches,
)

HOST_LOCK = Path("/private/tmp/bikefinder-motoplanete-technical.lock")
HOST_STATE = Path("/private/tmp/bikefinder-motoplanete-access.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data/technical/motoplanete"))
    parser.add_argument("--urls-file", type=Path)
    parser.add_argument("--refresh-sitemaps", action="store_true")
    size = parser.add_mutually_exclusive_group()
    size.add_argument("--limit", type=int, default=20)
    size.add_argument("--all", action="store_true", help="Attempt every queued fiche sequentially")
    parser.add_argument("--delay", type=float, default=10.0, help="Minimum 10 seconds")
    parser.add_argument("--export-only", action="store_true", help="No HTTP; export durable successes/status")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be non-negative")
    args.out.mkdir(parents=True, exist_ok=True)
    # All new instances share this host lock, even when their output paths differ.
    # Legacy collectors must remain stopped: they do not implement this lock.
    with HOST_LOCK.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("A technical Motoplanete collector is already active")
        store = CrawlStore(args.out)
        def stop(signum, frame):
            raise KeyboardInterrupt
        old_handler = signal.signal(signal.SIGTERM, stop)
        try:
            if args.export_only:
                store.export()
                print(json.dumps(store.report(), ensure_ascii=False))
                return
            atomic_text(args.out / "pid.txt", str(os.getpid()) + "\n")
            store.report(running=True)
            host_state = HostAccessState(HOST_STATE)
            cooldown = max(store.cooldown_remaining(), host_state.cooldown_remaining())
            if cooldown > 0:
                parser.error(f"Source cooldown still active for {cooldown:.0f}s; no HTTP requested")
            client = PoliteClient(args.delay, store=host_state)
            client.check_access(args.out)
            if args.urls_file:
                store.seed(args.urls_file.read_text(encoding="utf-8").splitlines())
            cache = args.out / "fiche_urls.txt"
            if args.refresh_sitemaps or (not args.urls_file and not cache.exists() and not store.has_pages()):
                urls = discover_fiches(client)
                atomic_text(cache, "\n".join(urls) + "\n")
                store.seed(urls)
            elif cache.exists():
                store.seed(cache.read_text(encoding="utf-8").splitlines())
            report = crawl(store, client, parse_technical_page, limit=None if args.all else args.limit)
            print(json.dumps(report, ensure_ascii=False))
            if report["halted"]:
                raise SystemExit(2)
        except SourceBusy as exc:
            store.cooldown(exc.retry_after)
            store.export()
            report = store.report(running=False)
            report["halted"] = str(exc)
            atomic_text(args.out / "last_run.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            raise SystemExit(str(exc))
        finally:
            signal.signal(signal.SIGTERM, old_handler)
            store.report(running=False)
            store.close()


if __name__ == "__main__":
    main()

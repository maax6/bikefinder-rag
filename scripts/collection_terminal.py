#!/usr/bin/env python3
"""Read-only, bounded Zellij dashboard with an explicit refresh heartbeat."""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import subprocess
import sys
import termios
import time
import unicodedata
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from monitor_technical_collection import DEFAULT_OUT, _timestamp, read_progress

PARIS = ZoneInfo('Europe/Paris')
TITLES = {'progress': 'AVANCEMENT', 'http': 'HTTP ET DERNIÈRES FICHES',
          'coverage': 'COUVERTURE DU LOT', 'incidents': 'SANTÉ ET INCIDENTS'}


def number(value):
    return f'{value:,}'.replace(',', ' ')


def display_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)


def fit(text, width):
    text = ''.join(c if c >= ' ' and c != '\x7f' else ' ' for c in str(text)).strip()
    if display_width(text) <= width:
        return text
    result = ''
    for char in text:
        if display_width(result + char) > max(0, width - 1):
            break
        result += char
    return result + ('…' if width else '')


def age_text(seconds):
    if seconds is None:
        return 'aucune fiche reçue'
    if seconds < 60:
        return f'{int(seconds)} s'
    if seconds < 3600:
        return f'{int(seconds / 60)} min'
    return f'{seconds / 3600:.1f} h'


def local_time(value):
    parsed = _timestamp(value)
    return parsed.astimezone(PARIS).strftime('%d/%m %H:%M:%S') if parsed else 'inconnue'


def read_details(panel, out_dir, progress):
    details = {}
    if panel == 'progress':
        check = subprocess.run(['ps', '-axo', 'command='], capture_output=True, text=True, timeout=2)
        details['sleep_protected'] = (
            f"/usr/bin/caffeinate -i -w {progress['process']['pid']}" in check.stdout.splitlines()
            if check.returncode == 0 else None)
    elif panel in {'http', 'coverage', 'incidents'}:
        with closing(sqlite3.connect((out_dir / 'crawl.sqlite3').resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN')
            if panel == 'http':
                details['http_totals'] = dict(conn.execute('SELECT status,count(*) FROM pages WHERE attempts>0 GROUP BY status'))
                rows = conn.execute('SELECT updated_at,status,state,error,result FROM pages WHERE attempts>0 ORDER BY updated_at DESC LIMIT 8')
                details['http_rows'] = []
                for row in rows:
                    record = json.loads(row['result']) if row['result'] else {}
                    identity = record.get('identity', {})
                    details['http_rows'].append(dict(row, name=identity.get('raw_name') or f"{identity.get('brand', '')} {identity.get('model', '')}".strip() or 'Fiche non extraite'))
            elif panel == 'coverage':
                row = conn.execute("""SELECT count(*) fiches,
                    count(DISTINCT json_extract(result,'$.identity.brand')) brands,
                    coalesce(sum(json_array_length(result,'$.spec_rows')),0) spec_rows,
                    coalesce(sum(json_array_length(result,'$.equipment_evidence')),0) equipment,
                    coalesce(sum(json_array_length(result,'$.equipment_evidence')>0),0) equipment_fiches
                    FROM pages WHERE state='success' AND json_valid(result)""").fetchone()
                details['coverage'] = dict(row)
            else:
                details['retried'] = conn.execute('SELECT count(*) FROM pages WHERE attempts>1').fetchone()[0]
                details['errors'] = conn.execute('SELECT count(*) FROM pages WHERE error IS NOT NULL').fetchone()[0]
                row = conn.execute("SELECT value FROM source_state WHERE key='cooldown_until'").fetchone()
                details['cooldown_until'] = row[0] if row else 0
            conn.rollback()
    if panel == 'incidents':
        try:
            details['last_run'] = json.loads((out_dir / 'last_run.json').read_text())
        except (OSError, ValueError):
            details['last_run'] = {}
    return details


def render(panel, *, progress=None, details=None, now=None, width=80, height=24, interval=.5, data_interval=1):
    now = now or datetime.now(timezone.utc)
    p = progress if progress is not None else read_progress(DEFAULT_OUT, now=now)
    d = details or {}
    tick = '|/-\\'[int(now.timestamp() * 2) % 4]
    lines = [f'MOTOPLANETE / {TITLES[panel]}',
             f"Actualisé : {now.astimezone(PARIS):%H:%M:%S} {tick} | données {data_interval:g} s",
             '─' * max(1, width)]
    counts = p['counts']
    last = _timestamp(p.get('updated_at'))
    age = max(0, (now - last).total_seconds()) if last else None
    if panel == 'progress':
        kind = p['activity']['kind']
        labels = {'running': 'EN COURS', 'waiting': 'AUCUNE FICHE RÉCENTE',
                  'stopped': 'COLLECTEUR ARRÊTÉ', 'unknown': 'PROCESSUS NON VÉRIFIÉ', 'complete': 'LOT PARCOURU'}
        lines += [f"[{labels.get(kind, kind)}]  PID {p['process']['pid'] or '?'}", '']
        latest = p.get('last_success') or next((record for record in p.get('last_records', []) if record.get('state') == 'success'), None)
        lines += ['DERNIÈRE MOTO ENREGISTRÉE']
        if latest:
            received = _timestamp(latest.get('updated_at'))
            elapsed = max(0, (now - received).total_seconds()) if received else None
            parts = urlsplit(latest.get('url', '')).path.strip('/').split('/')
            fiche_id = parts[1] if len(parts) > 1 and parts[1].isdigit() else '?'
            lines += [latest['name'], f"Fiche #{fiche_id} · reçue le {local_time(latest.get('updated_at'))}",
                      f"Enregistrée il y a {age_text(elapsed)}", '']
        else:
            lines += ['Aucune fiche récupérée pour le moment.', '']
        bar_width = max(8, min(32, width - 12))
        filled = int(bar_width * p['progress_percent'] / 100)
        lines += ['[' + '█' * filled + '░' * (bar_width - filled) + f"] {p['progress_percent']:.1f} %",
                  f"{number(p['success'])} / {number(p['total'])} fiches récupérées",
                  f"À récupérer : {number(p['remaining'])}",
                  f"Depuis ouverture : +{number(p.get('since_open', 0))} fiches",
                  f"Dernière fiche : il y a {age_text(age)}"]
        if p.get('rate_per_hour') and kind == 'running':
            lines += [f"Cadence récente : {p['rate_per_hour']:.0f} fiches/h"]
        if p.get('eta_seconds') and kind == 'running':
            eta = now + timedelta(seconds=p['eta_seconds'])
            lines += [f"Reste environ : {p['eta_seconds'] / 3600:.1f} h",
                      f"Fin estimée : {eta.astimezone(PARIS):%d/%m à %H:%M} (si cadence stable)"]
        protected = d.get('sleep_protected')
        lines += ['Veille : ' + ('bloquée (caffeinate -i)' if protected is True else 'NON BLOQUÉE' if protected is False else 'non vérifiée')]
        lines += [f"À examiner : {counts.get('quarantined', 0) + counts.get('needs_review', 0)} | en erreur : {counts.get('retryable', 0) + counts.get('terminal', 0) + counts.get('blocked', 0)}"]
        lines += ['', 'Horloge mobile = panneau actif.', 'Collecte : 10 s minimum entre requêtes.']
    elif panel == 'http':
        totals = d.get('http_totals', {})
        lines += ['Dernier statut enregistré par fiche', ' | '.join(f"HTTP {code or '?'} : {number(count)}" for code, count in totals.items()) or 'Aucune requête enregistrée', '']
        for row in d.get('http_rows', []):
            state = {'success': 'OK', 'retryable': 'À REPRENDRE', 'terminal': 'ÉCHEC', 'needs_review': 'À EXAMINER', 'blocked': 'ACCÈS BLOQUÉ'}.get(row['state'], row['state'])
            lines += [f"{local_time(row['updated_at'])}  HTTP {row['status'] or '?'}  {state}", row['name']]
            if row['error']:
                lines += [f"Erreur : {row['error']}"]
        lines += ['', 'Les anciennes tentatives peuvent être remplacées.']
    elif panel == 'coverage':
        c = d.get('coverage', {})
        lines += [f"{number(c.get('brands', 0))} marques source | {number(c.get('spec_rows', 0))} lignes",
                  f"{number(c.get('equipment', 0))} mentions sur {number(c.get('equipment_fiches', 0))} fiches", '',
                  'Millésimes     Reçues / file       %']
        bands = [('Avant 1990', 0, 1989), ('1990–1999', 1990, 1999), ('2000–2009', 2000, 2009), ('2010–2019', 2010, 2019), ('2020–2027', 2020, 2027)]
        for name, start, end in bands:
            cohort = [y for y in p.get('years', []) if start <= y['year'] <= end]
            total = sum(y['total'] for y in cohort)
            success = sum(y['success'] for y in cohort)
            lines += [f'{name:<12} {number(success):>5} / {number(total):<6} {100 * success / total if total else 0:5.1f}']
        lines += ['', 'Couverture de la file connue, pas mondiale.', 'Mentions d’équipement : classification à venir.']
    else:
        lines += [f"Processus collecteur : {('actif' if p['process']['alive'] else 'arrêté') if p['process']['alive'] is not None else 'non vérifié'}",
                  f"Dernière fiche : {local_time(p.get('updated_at'))}",
                  f"Erreurs actuelles : {d.get('errors', 0)} | fiches retentées : {d.get('retried', 0)}",
                  f"À examiner : {counts.get('quarantined', 0)} isolée(s), {counts.get('needs_review', 0)} extraite(s)"]
        cooldown = max(0, d.get('cooldown_until', 0) - now.timestamp())
        lines += [f'Pause source : {cooldown:.0f} s restantes' if cooldown else 'Aucune pause source en cours', '']
        previous = d.get('last_run', {})
        if previous.get('halted'):
            lines += ['DERNIER ARRÊT ENREGISTRÉ', local_time(previous.get('updated_at')), previous['halted']]
            if p['process']['alive'] is True and last and (_timestamp(previous.get('updated_at')) or now) < last:
                lines += ['Reprise constatée : de nouvelles fiches arrivent.']
        lines += ['', '429 / 5xx : arrêt du lot, reprise contrôlée.', 'Fermer ce tableau ne ferme pas le collecteur.']
    return '\n'.join(fit(line, max(1, width)) for line in lines[:max(1, height)])


def paint(content, *, color=True):
    lines = content.splitlines()
    result = []
    for index, line in enumerate(lines):
        style = '\033[1;36m' if index == 0 else '\033[1;32m' if '[EN COURS]' in line else '\033[1;33m' if any(s in line for s in ['ARRÊTÉ', 'AUCUNE FICHE', 'NON VÉRIFIÉ', 'DERNIÈRE MOTO']) else '\033[1m' if index and lines[index - 1] == 'DERNIÈRE MOTO ENREGISTRÉE' else ''
        result.append(f'\033[{index + 1};1H\033[2K' + (style if color else '') + line + ('\033[0m' if color else ''))
    return '\033[H\033[2J' + ''.join(result)


def terminal_dimensions(stream):
    try:
        return os.get_terminal_size(stream.fileno())
    except (OSError, ValueError):
        return os.terminal_size((80, 24))


@contextmanager
def terminal_screen(stream):
    original = None
    if stream.isatty():
        try:
            original = termios.tcgetattr(stream.fileno())
            updated = original[:]
            updated[0] &= ~termios.IXON
            termios.tcsetattr(stream.fileno(), termios.TCSANOW, updated)
        except (OSError, termios.error):
            pass
        stream.write('\033[?1049h\033[?25l')
        stream.flush()
    try:
        yield
    finally:
        if original is not None:
            termios.tcsetattr(stream.fileno(), termios.TCSANOW, original)
        if stream.isatty():
            stream.write('\033[?25h\033[?1049l')
            stream.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('panel', choices=TITLES)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--interval', type=float, default=.5, help='Intervalle de rendu de l’écran')
    parser.add_argument('--data-interval', type=float, default=1, help='Intervalle de lecture des données')
    args = parser.parse_args()
    if args.interval < .5:
        parser.error('--interval doit être au moins 0.5 seconde')
    if args.data_interval < .5:
        parser.error('--data-interval doit être au moins 0.5 seconde')
    baseline = None
    next_read = 0
    progress = details = None
    with terminal_screen(sys.stdout):
        while True:
            now = datetime.now(timezone.utc)
            width, height = terminal_dimensions(sys.stdout)
            try:
                if time.monotonic() >= next_read:
                    # Publish both parts only after the complete read succeeds.
                    fresh = read_progress(DEFAULT_OUT, now=now)
                    fresh_details = read_details(args.panel, DEFAULT_OUT, fresh)
                    if baseline is None:
                        baseline = fresh['success']
                    fresh['since_open'] = fresh['success'] - baseline
                    progress, details = fresh, fresh_details
                    next_read = time.monotonic() + args.data_interval
                content = render(args.panel, progress=progress, details=details, now=now, width=width - 1, height=height, interval=args.interval, data_interval=args.data_interval)
            except (OSError, sqlite3.Error, ValueError, subprocess.TimeoutExpired) as exc:
                content = '\n'.join([f'MOTOPLANETE / {TITLES[args.panel]}',
                    f'Actualisé : {now.astimezone(PARIS):%H:%M:%S}', 'LECTURE IMPOSSIBLE — panneau toujours actif', fit(exc, width - 1)])
            if args.once:
                print(content, flush=True)
                break
            sys.stdout.write(paint(content, color=sys.stdout.isatty()))
            sys.stdout.flush()
            time.sleep(args.interval)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass

#!/usr/bin/env python3
"""Read-only Zellij panels; independent of the collector and HTTP monitor."""
import argparse
from contextlib import closing
import json
import sqlite3
import time
from monitor_technical_collection import DEFAULT_OUT, read_progress


def render(panel):
    p = read_progress(DEFAULT_OUT)
    if panel == 'progress':
        rate = p['rate_per_hour']
        eta = p['eta_seconds']
        lines = ['MOTOPLANETE — COLLECTE TECHNIQUE', '', p['activity']['label'],
                 f"PID : {p['process']['pid']}  |  Dernière activité : {p['updated_at']}",
                 f"Fiches : {p['success']:,} / {p['total']:,} ({p['progress_percent']:.1f} %)",
                 f"À parcourir : {p['remaining']:,}",
                 f"Cadence : {rate:.0f} fiches/h" if rate else 'Cadence : en cours de mesure',
                 f"Temps estimé : {eta / 3600:.1f} h" if eta else 'Temps estimé : indisponible',
                 '', 'États : ' + json.dumps(p['counts'], ensure_ascii=False),
                 '', 'Intervalle minimum : 10 s · reprise depuis SQLite',
                 'caffeinate -i : veille automatique bloquée pendant la collecte']
        if p['process']['alive'] is False:
            try:
                report = json.loads((DEFAULT_OUT / 'last_run.json').read_text())
                lines.append('Dernier arrêt : ' + str(report.get('halted') or 'fin du processus'))
            except (OSError, ValueError):
                pass
    else:
        with closing(sqlite3.connect((DEFAULT_OUT / 'crawl.sqlite3').as_uri() + '?mode=ro', uri=True)) as c:
            totals = c.execute('SELECT status,count(*) FROM pages WHERE attempts>0 GROUP BY status').fetchall()
            rows = c.execute('SELECT updated_at,status,state,url,error FROM pages WHERE attempts>0 ORDER BY updated_at DESC LIMIT 12').fetchall()
        lines = ['HTTP — DERNIER ÉTAT ENREGISTRÉ PAR FICHE',
                 'Ces compteurs ne sont pas un historique de toutes les requêtes.',
                 '  '.join(f"{code or 'sans réponse'} : {n}" for code, n in totals), '']
        for updated, code, state, url, error in rows:
            lines.extend([f'{updated} | HTTP {code or "?"} | {state}', url])
            if error:
                lines.append(error)
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('panel', choices=['progress', 'http'])
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    while True:
        try:
            content = render(args.panel)
        except (OSError, sqlite3.Error, ValueError) as exc:
            content = f'Données momentanément indisponibles : {exc}'
        print(('' if args.once else '\033[2J\033[H') + content, flush=True)
        if args.once:
            break
        time.sleep(5)


if __name__ == '__main__':
    main()

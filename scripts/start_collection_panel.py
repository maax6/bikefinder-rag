#!/usr/bin/env python3
"""Resume collector with idle-sleep protection and open its Zellij dashboard."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from monitor_technical_collection import DEFAULT_OUT, ROOT, collector_process_alive

SESSION = 'bikefinder-collecte'
LAYOUT_PATH = Path('/private/tmp/bikefinder-collection.kdl')


def dashboard_layout(python):
    def pane(name, panel, size, focus=False):
        quote = lambda value: json.dumps(value, ensure_ascii=False)
        return (f'pane name={quote(name)} size="{size}%" command={quote(python)}'
                + (' focus=true' if focus else '') + ' { args '
                + ' '.join(quote(a) for a in [str(ROOT / 'scripts/collection_terminal.py'), panel, '--interval', '0.5', '--data-interval', '1']) + '; }')
    return '\n'.join(['layout {', f'cwd {json.dumps(str(ROOT), ensure_ascii=False)}',
        'pane split_direction="horizontal" {', 'pane size="56%" split_direction="vertical" {',
        pane('Avancement · direct', 'progress', 56, True), pane('HTTP · dernières fiches', 'http', 44), '}',
        'pane size="44%" split_direction="vertical" {', pane('Couverture · millésimes', 'coverage', 56),
        pane('Santé · incidents', 'incidents', 44), '}', '}', '}', ''])


def dashboard_panes_only(panes):
    """Only a tab made exclusively of our readers can be replaced automatically."""
    terminals = [pane for pane in panes if not pane['is_plugin']]
    if not terminals:
        return False
    for pane in terminals:
        try:
            args = shlex.split(pane.get('terminal_command') or '')
        except ValueError:
            return False
        reader = len(args) >= 3 and args[:2] == [str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/collection_terminal.py')] and args[2] in {'progress', 'http', 'coverage', 'incidents'}
        old_log = args == ['/usr/bin/tail', '-n', '8', '-F', '/private/tmp/bikefinder-technical-collection.log']
        if not reader and not old_log:
            return False
    return True


def refresh_dashboard(zellij, layout):
    action = [zellij, '--session', SESSION, 'action']
    tabs = json.loads(subprocess.check_output(action + ['list-tabs', '--json'], text=True))
    previous = next((tab for tab in tabs if tab.get('active')), None)
    panes = json.loads(subprocess.check_output(action + ['list-panes', '--all', '--json'], text=True))
    old_panes = [pane for pane in panes if previous and pane.get('tab_id') == previous['tab_id']]
    new_id = subprocess.check_output(action + ['new-tab', '--layout', str(layout), '--name', 'Collecte Motoplanete', '--cwd', str(ROOT)], text=True).strip()
    # The live collector is detached and never a command in these reader panes.
    # Preserve any tab containing a shell, a collector or an unrelated command.
    if previous and dashboard_panes_only(old_panes):
        subprocess.run(action + ['close-tab-by-id', str(previous['tab_id'])], check=True)
    print(f'Tableau de bord rafraîchi · onglet {new_id} · collecteur inchangé')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--here', action='store_true', help='Afficher Zellij dans le terminal courant')
    parser.add_argument('--dashboard-only', action='store_true', help='Ouvrir le suivi sans lancer ni modifier le collecteur ou caffeinate')
    parser.add_argument('--refresh-dashboard', action='store_true', help='Remplacer les afficheurs existants par le nouveau tableau')
    args = parser.parse_args()
    zellij = shutil.which('zellij')
    if not zellij:
        raise SystemExit('Zellij doit être installé pour ouvrir le panneau.')
    python = str(ROOT / '.venv/bin/python')
    try:
        pid = int((DEFAULT_OUT / 'pid.txt').read_text())
    except (OSError, ValueError):
        pid = None
    if not args.dashboard_only:
        alive = collector_process_alive(pid, DEFAULT_OUT) if pid else False
        if alive is None:
            raise SystemExit('Processus non vérifiable : utiliser --dashboard-only ; aucune nouvelle collecte lancée.')
        if alive is False:
            state_file = Path('/private/tmp/bikefinder-motoplanete-access.json')
            state = json.loads(state_file.read_text()) if state_file.exists() else {}
            cooldown = max(0, state.get('cooldown_until', 0) - time.time())
            if cooldown:
                raise SystemExit(f'Source en pause : encore {cooldown:.0f} secondes.')
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONUNBUFFERED='1')
            with open('/private/tmp/bikefinder-technical-collection.log', 'a') as log:
                process = subprocess.Popen([python, str(ROOT / 'scripts/collect_technical_data.py'), '--out', str(DEFAULT_OUT), '--all'], cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            pid = process.pid
        commands = subprocess.run(['ps', '-axo', 'command='], capture_output=True, text=True, check=True).stdout.splitlines()
        if f'/usr/bin/caffeinate -i -w {pid}' not in commands:
            subprocess.Popen(['/usr/bin/caffeinate', '-i', '-w', str(pid)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    layout = LAYOUT_PATH
    layout.write_text(dashboard_layout(python))
    sessions = subprocess.run([zellij, 'list-sessions', '--no-formatting'], capture_output=True, text=True, check=True).stdout
    exists = any(line.startswith(SESSION + ' ') and '(EXITED' not in line for line in sessions.splitlines())
    if exists and args.refresh_dashboard:
        refresh_dashboard(zellij, layout)
        return
    launch = [zellij, 'attach', SESSION] if exists else [zellij, '--layout', str(layout), 'attach', '--create', SESSION]
    if args.here:
        os.execv(zellij, launch)
    command = shlex.join(launch)
    subprocess.run(['/usr/bin/osascript', '-e', 'tell application "Terminal"', '-e', 'activate', '-e', 'do script ' + json.dumps(command, ensure_ascii=False), '-e', 'end tell'], check=True)
    print(f'Suivi ouvert · collecteur PID {pid or "non enregistré"} · Zellij {SESSION}')


if __name__ == '__main__':
    main()

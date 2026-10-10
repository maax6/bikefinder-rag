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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--here', action='store_true', help='Afficher Zellij dans le terminal courant')
    args = parser.parse_args()
    zellij = shutil.which('zellij')
    if not zellij:
        raise SystemExit('Zellij doit être installé pour ouvrir le panneau.')
    python = str(ROOT / '.venv/bin/python')
    pid_file = DEFAULT_OUT / 'pid.txt'
    try:
        pid = int(pid_file.read_text())
    except (OSError, ValueError):
        pid = None
    if not pid or collector_process_alive(pid, DEFAULT_OUT) is not True:
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
    layout = Path('/private/tmp/bikefinder-collection.kdl')
    def pane(name, command, arguments):
        return f'pane name={json.dumps(name, ensure_ascii=False)} command={json.dumps(command, ensure_ascii=False)} {{ args ' + ' '.join(json.dumps(a, ensure_ascii=False) for a in arguments) + '; }'
    layout.write_text('layout {\n pane split_direction="horizontal" {\n pane split_direction="vertical" {\n' + pane('Avancement', python, [str(ROOT / 'scripts/collection_terminal.py'), 'progress']) + '\n' + pane('Codes HTTP et dernières fiches', python, [str(ROOT / 'scripts/collection_terminal.py'), 'http']) + '\n}\n' + pane('Journal de collecte', '/usr/bin/tail', ['-n', '8', '-F', '/private/tmp/bikefinder-technical-collection.log']) + '\n}\n}\n')
    # Open only the dashboard in Terminal; the collector is detached from it.
    sessions = subprocess.run([zellij, 'list-sessions', '--no-formatting'], capture_output=True, text=True).stdout
    exists = any(line.startswith('bikefinder-collecte ') and '(EXITED' not in line for line in sessions.splitlines())
    launch = [zellij, 'attach', 'bikefinder-collecte'] if exists else [zellij, '--layout', str(layout), 'attach', '--create', 'bikefinder-collecte']
    if args.here:
        os.execv(zellij, launch)
    command = shlex.join(launch)
    subprocess.run(['/usr/bin/osascript', '-e', 'tell application "Terminal"', '-e', 'activate', '-e', 'do script ' + json.dumps(command, ensure_ascii=False), '-e', 'end tell'], check=True)
    print(f'Collecteur PID {pid} · caffeinate -i actif · Zellij bikefinder-collecte')


if __name__ == '__main__':
    main()

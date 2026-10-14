"""Rebuilding a dashboard must never replace a collector or unrelated shell."""
import importlib.util
from pathlib import Path
import shlex
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('panel_launcher', ROOT / 'scripts/start_collection_panel.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_only_known_reader_tabs_can_be_closed():
    reader = {'is_plugin': False, 'terminal_command': shlex.join([str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/collection_terminal.py'), 'progress'])}
    assert launcher.dashboard_panes_only([reader])
    for command in [shlex.join([str(ROOT / '.venv/bin/python'), str(ROOT / 'scripts/collect_technical_data.py'), '--all']), '/bin/zsh', '/usr/bin/tail -F /other/log']:
        assert not launcher.dashboard_panes_only([reader, {'is_plugin': False, 'terminal_command': command}])


def test_dashboard_only_never_checks_or_spawns_the_collector(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['panel', '--dashboard-only', '--refresh-dashboard'])
    monkeypatch.setattr(launcher, 'DEFAULT_OUT', tmp_path)
    monkeypatch.setattr(launcher, 'LAYOUT_PATH', tmp_path / 'layout.kdl')
    monkeypatch.setattr(launcher.shutil, 'which', lambda name: '/opt/homebrew/bin/zellij')
    def forbidden(*args, **kwargs):
        raise AssertionError('Dashboard-only accessed collector lifecycle')
    monkeypatch.setattr(launcher, 'collector_process_alive', forbidden)
    monkeypatch.setattr(launcher.subprocess, 'Popen', forbidden)
    def sessions(args, **kwargs):
        assert args == ['/opt/homebrew/bin/zellij', 'list-sessions', '--no-formatting']
        return SimpleNamespace(stdout='bikefinder-collecte [Created 3h ago]\n')
    monkeypatch.setattr(launcher.subprocess, 'run', sessions)
    refreshed = []
    monkeypatch.setattr(launcher, 'refresh_dashboard', lambda *args: refreshed.append(args))
    launcher.main()
    assert len(refreshed) == 1


def test_unknown_process_state_cannot_launch_a_duplicate_collector(tmp_path, monkeypatch):
    (tmp_path / 'pid.txt').write_text('123\n')
    monkeypatch.setattr(sys, 'argv', ['panel'])
    monkeypatch.setattr(launcher, 'DEFAULT_OUT', tmp_path)
    monkeypatch.setattr(launcher.shutil, 'which', lambda name: '/opt/homebrew/bin/zellij')
    monkeypatch.setattr(launcher, 'collector_process_alive', lambda *args: None)
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('Duplicate collector started'))
    with pytest.raises(SystemExit, match='aucune nouvelle collecte'):
        launcher.main()

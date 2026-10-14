"""The dashboard must expose freshness and avoid freezing terminal output."""
from datetime import datetime, timedelta, timezone
import importlib.util
import os
import fcntl
from pathlib import Path
import pty
import sys
import struct
import termios

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('collection_terminal', ROOT / 'scripts/collection_terminal.py')
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)
NOW = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)


def progress():
    return {
        'counts': {'success': 100, 'pending': 99, 'quarantined': 1},
        'success': 100, 'total': 200, 'remaining': 99, 'progress_percent': 50,
        'process': {'pid': 123, 'alive': True},
        'activity': {'label': 'Collecte en cours', 'kind': 'running'},
        'updated_at': NOW.isoformat(), 'rate_per_hour': 350,
        'eta_seconds': 1000, 'last_records': [],
    }


def test_heartbeat_changes_even_when_no_new_fiche_arrives():
    before = panel.render('progress', progress=progress(), now=NOW, width=60, height=18)
    after = panel.render('progress', progress=progress(), now=NOW + timedelta(seconds=2), width=60, height=18)
    assert 'Actualisé : 02:00:00' in before
    assert 'Actualisé : 02:00:02' in after
    assert before != after


def test_small_pane_keeps_status_and_freshness_without_scrolling():
    result = panel.render('progress', progress=progress(), now=NOW, width=40, height=12)
    assert 'EN COURS' in result
    assert 'Actualisé' in result
    assert len(result.splitlines()) <= 12
    assert all(panel.display_width(line) <= 40 for line in result.splitlines())


def test_last_moto_remains_visible_in_a_short_pane_with_its_receipt_time():
    state = progress()
    state['last_success'] = {'name': 'Suzuki GSX-F 750 2007', 'year': 2007,
        'updated_at': NOW.isoformat(), 'state': 'success',
        'url': 'https://www.motoplanete.com/suzuki/3381/GSX-F-750-2007/contact.html'}
    result = panel.render('progress', progress=state, now=NOW, width=60, height=12)
    assert 'Suzuki GSX-F 750 2007' in result
    assert '02:00:00' in result
    assert '#3381' in result


def test_latest_failed_attempt_cannot_replace_the_last_collected_moto():
    state = progress()
    state['last_success'] = {'name': 'Honda Example 2000', 'year': 2000,
        'updated_at': NOW.isoformat(), 'state': 'success',
        'url': 'https://www.motoplanete.com/honda/42/Example-2000/contact.html'}
    state['last_records'] = [{'name': 'Fiche sans titre', 'state': 'retryable'}]
    result = panel.render('progress', progress=state, now=NOW, width=80, height=24)
    assert 'Honda Example 2000' in result
    assert 'Fiche sans titre' not in result


def test_live_but_stale_collector_has_no_eta_claim():
    state = progress()
    state['activity'] = {'kind': 'waiting', 'label': 'Actif · aucune fiche récente'}
    state['updated_at'] = (NOW - timedelta(minutes=10)).isoformat()
    result = panel.render('progress', progress=state, now=NOW, width=80, height=24)
    assert 'AUCUNE FICHE RÉCENTE' in result
    assert '10 min' in result
    assert 'Fin estimée' not in result


def test_unverified_sleep_protection_is_never_reported_as_active():
    result = panel.render('progress', progress=progress(), details={}, now=NOW, width=80, height=24)
    assert 'Veille : non vérifiée' in result
    assert 'veille bloquée' not in result


def test_frame_uses_no_final_newline_that_scrolls_the_viewport():
    frame = panel.paint('one\ntwo', color=False)
    assert frame.startswith('\033[H')
    assert not frame.endswith(('\n', '\r'))


def test_resize_uses_actual_pty_dimensions_despite_stale_environment(monkeypatch):
    master, slave = pty.openpty()
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 18, 60, 0, 0))
        monkeypatch.setenv('COLUMNS', '180')
        monkeypatch.setenv('LINES', '60')
        with os.fdopen(os.dup(slave), 'w') as stream:
            assert panel.terminal_dimensions(stream) == (60, 18)
    finally:
        os.close(master)
        os.close(slave)


def test_terminal_mode_prevents_ctrl_s_pause_and_restores_settings():
    master, slave = pty.openpty()
    try:
        original = termios.tcgetattr(slave)
        original[0] |= termios.IXON
        termios.tcsetattr(slave, termios.TCSANOW, original)
        with os.fdopen(os.dup(slave), 'w', buffering=1) as stream:
            with panel.terminal_screen(stream):
                assert not termios.tcgetattr(slave)[0] & termios.IXON
            assert termios.tcgetattr(slave) == original
    finally:
        os.close(master)
        os.close(slave)

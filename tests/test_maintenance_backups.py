"""Daily maintenance window and backups (Settings > Maintenance & backups)."""
import datetime
import os
import sqlite3
import zipfile

import fixture
import pytest

import backups


@pytest.fixture(autouse=True)
def backup_dir(tmp_path, monkeypatch):
    path = tmp_path / "backups"
    monkeypatch.setattr(backups, "BACKUP_DIR", str(path))
    return path


@pytest.fixture
def admin_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code == 302
    return shop_app.client


def _pending_maintenance():
    from db import Task
    return Task.query.filter_by(task_name='scheduled_maintenance', status='pending').all()


# --- backups -------------------------------------------------------------------------

def test_backup_contains_a_consistent_database_and_the_settings(shop_app, backup_dir, tmp_path):
    import settings as settings_mod
    with open(settings_mod.KEYS_FILE, 'w') as f:
        f.write('dummy = 00\n')
    with shop_app.app.app_context():
        settings_mod.get_settings()  # writes settings.yaml
        entry = backups.create_backup()

    path = backup_dir / entry['name']
    assert backups.NAME_RE.match(entry['name']) and entry['size'] == path.stat().st_size
    with zipfile.ZipFile(path) as zf:
        assert set(zf.namelist()) == {'ownfoil.db', 'settings.yaml', 'keys.txt'}
        zf.extract('ownfoil.db', tmp_path / 'restored')
    con = sqlite3.connect(tmp_path / 'restored' / 'ownfoil.db')
    users = {row[0] for row in con.execute('SELECT user FROM user')}
    con.close()
    assert users == {'admin', 'shopper', 'noshop'}
    # No half-written leftovers next to it.
    assert os.listdir(backup_dir) == [entry['name']]


def test_listing_is_newest_first_and_ignores_other_files(backup_dir):
    backup_dir.mkdir()
    for name in ('ownfoil-backup-20260101-040000.zip', 'ownfoil-backup-20260103-040000.zip',
                 'ownfoil-backup-20260102-040000.zip', 'notes.txt', 'ownfoil-backup-bad.zip'):
        (backup_dir / name).write_bytes(b'x')
    assert [b['name'] for b in backups.list_backups()] == [
        'ownfoil-backup-20260103-040000.zip', 'ownfoil-backup-20260102-040000.zip',
        'ownfoil-backup-20260101-040000.zip']


def test_prune_keeps_the_newest(backup_dir):
    backup_dir.mkdir()
    for day in range(1, 6):
        (backup_dir / f'ownfoil-backup-202601{day:02d}-040000.zip').write_bytes(b'x')
    assert backups.prune_backups(2) == 3
    assert [b['name'] for b in backups.list_backups()] == [
        'ownfoil-backup-20260105-040000.zip', 'ownfoil-backup-20260104-040000.zip']


@pytest.mark.parametrize('name', ['../settings.yaml', 'ownfoil.db', 'ownfoil-backup-20260101-040000.zip'])
def test_backup_path_only_resolves_existing_backups(name):
    assert backups.backup_path(name) is None


# --- scheduling ----------------------------------------------------------------------

def test_next_run_is_today_or_tomorrow():
    import tasks
    offset = datetime.datetime.now() - datetime.datetime.utcnow()
    morning = datetime.datetime(2026, 11, 1, 2, 0)
    assert tasks.next_maintenance_run('04:00', now=morning) + offset == pytest.approx(
        datetime.datetime(2026, 11, 1, 4, 0), abs=datetime.timedelta(seconds=2))
    evening = datetime.datetime(2026, 11, 1, 5, 0)
    assert tasks.next_maintenance_run('04:00', now=evening) + offset == pytest.approx(
        datetime.datetime(2026, 11, 2, 4, 0), abs=datetime.timedelta(seconds=2))


def test_saving_schedules_and_disabling_unschedules(admin_client):
    resp = admin_client.post('/api/settings/maintenance', json={'enabled': True, 'time': '3:30'})
    body = resp.get_json()
    assert body['success'] and body['next_run'].endswith('03:30')
    with admin_client.application.app_context():
        assert len(_pending_maintenance()) == 1
    assert admin_client.get('/api/settings').get_json()['maintenance']['time'] == '03:30'

    admin_client.post('/api/settings/maintenance', json={'enabled': False})
    with admin_client.application.app_context():
        assert _pending_maintenance() == []


@pytest.mark.parametrize('payload', [
    {'time': '25:00'}, {'time': 'noon'}, {'verify_all': 'hourly'}, {'backup_keep': 0}, {'backup_keep': 'x'},
])
def test_invalid_values_are_rejected(admin_client, payload):
    before = admin_client.get('/api/settings').get_json()['maintenance']
    assert admin_client.post('/api/settings/maintenance', json=payload).get_json()['success'] is False
    assert admin_client.get('/api/settings').get_json()['maintenance'] == before


def test_non_admin_cannot_touch_maintenance_or_backups(shop_app):
    shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    assert shop_app.client.post('/api/settings/maintenance', json={'enabled': True}).status_code == 403
    assert shop_app.client.get('/api/backups').status_code == 403
    assert shop_app.client.post('/api/backups').status_code == 403


# --- the maintenance task --------------------------------------------------------------

def _run_maintenance(shop_app, monkeypatch, **settings):
    import tasks
    from settings import set_maintenance_settings
    queued = []
    monkeypatch.setattr(tasks, 'enqueue_task', lambda name, data=None, **k: queued.append((name, data)))
    with shop_app.app.app_context():
        set_maintenance_settings({'enabled': True, **settings})
        tasks.scheduled_maintenance_task()
        pending = len(_pending_maintenance())
    return queued, pending


def test_maintenance_runs_the_chosen_jobs_and_books_the_next_run(shop_app, monkeypatch, backup_dir):
    queued, pending = _run_maintenance(shop_app, monkeypatch, backup=True, scan=True,
                                       remove_outdated_updates=True, verify_all='daily')
    assert ('scan_libraries', None) in queued
    assert ('verify_library', {'force': True}) in queued
    assert ('remove_outdated_updates', None) in queued
    assert len(backups.list_backups()) == 1
    assert pending == 1


def test_weekly_verify_only_on_sundays(shop_app, monkeypatch):
    import tasks

    class Monday(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime(2026, 11, 2, 4, 0)
    monkeypatch.setattr(tasks.datetime, 'datetime', Monday)
    queued, _ = _run_maintenance(shop_app, monkeypatch, backup=False, scan=False, verify_all='weekly')
    assert queued == []


def test_a_failed_backup_still_books_the_next_run(shop_app, monkeypatch):
    def broken():
        raise OSError('disk full')
    monkeypatch.setattr(backups, 'create_backup', broken)
    with pytest.raises(OSError):
        _run_maintenance(shop_app, monkeypatch, backup=True)
    with shop_app.app.app_context():
        assert len(_pending_maintenance()) == 1


def test_backups_are_rotated_to_the_configured_count(shop_app, monkeypatch, backup_dir):
    backup_dir.mkdir()
    for day in range(1, 5):
        (backup_dir / f'ownfoil-backup-202601{day:02d}-040000.zip').write_bytes(b'x')
    _run_maintenance(shop_app, monkeypatch, backup=True, backup_keep=2, scan=False)
    assert len(backups.list_backups()) == 2


# --- backup endpoints ------------------------------------------------------------------

def test_backup_now_download_and_delete(admin_client):
    body = admin_client.post('/api/backups').get_json()
    name = body['backup']['name']
    assert [b['name'] for b in body['backups']] == [name]

    resp = admin_client.get(f'/api/backups/{name}')
    assert resp.status_code == 200
    assert 'attachment' in resp.headers['Content-Disposition']
    assert resp.data[:2] == b'PK'
    resp.close()

    assert admin_client.delete(f'/api/backups/{name}').get_json()['backups'] == []
    assert admin_client.get(f'/api/backups/{name}').status_code == 404


def test_download_rejects_names_outside_the_backup_folder(admin_client):
    # `..%2F` never reaches the route (the path no longer matches it); nothing is served.
    resp = admin_client.get('/api/backups/..%2Fsettings.yaml')
    assert resp.status_code != 200 and b'shop' not in resp.data
    assert admin_client.get('/api/backups/settings.yaml').status_code == 404
    assert admin_client.delete('/api/backups/settings.yaml').status_code == 404

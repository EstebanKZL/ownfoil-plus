"""Collaborator: a user who sees every admin page and changes nothing."""
from pathlib import Path

import fixture
import pytest

from db import User, db

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def collab(shop_app):
    with shop_app.app.app_context():
        User.query.filter_by(user="shopper").update({"collaborator_access": True})
        db.session.commit()
    resp = shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    assert resp.status_code == 302
    return shop_app.client


def test_migration_adds_the_column():
    text = (ROOT / 'app/migrations/versions/e5f6a7b8c9d1_add_collaborator_access.py').read_text(encoding='utf-8')
    assert "down_revision = 'd4e5f6a7b8c0'" in text and "'collaborator_access'" in text


@pytest.mark.parametrize("path", ["/admin", "/admin/settings", "/admin/services", "/admin/files",
                                  "/admin/tasks", "/admin/stats", "/api/dashboard", "/api/users",
                                  "/api/backups", "/api/services"])
def test_sees_the_admin_pages(collab, path):
    assert collab.get(path).status_code == 200


def test_pages_say_read_only(collab):
    html = collab.get("/admin/settings").get_data(as_text=True)
    assert 'data-readonly="true"' in html and 'readonly-notice' in html


@pytest.mark.parametrize("method,path", [
    ("post", "/api/services/shop"), ("post", "/api/settings/shop"), ("post", "/api/settings/maintenance"),
    ("post", "/api/backups"), ("delete", "/api/tasks/history"), ("delete", "/api/stats/downloads"),
    ("post", "/api/settings/import"), ("patch", "/api/user"), ("delete", "/api/user"),
])
def test_changes_nothing(collab, method, path):
    assert getattr(collab, method)(path, json={}).status_code == 403


def test_may_upload_games(collab):
    # Starting an upload reaches the upload code (refused here on its merits, never 403).
    assert collab.post('/api/uploads', json={}).status_code != 403
    assert collab.patch('/api/uploads/nope', data=b'').status_code != 403
    assert collab.delete('/api/uploads/nope').status_code != 403
    # The keys upload stays with admins.
    assert collab.post('/api/upload').status_code == 403


@pytest.mark.parametrize("path", ["/api/settings/export", "/api/backups/x.zip"])
def test_reads_no_keys_or_other_peoples_saves(collab, path):
    assert collab.get(path).status_code == 403


def test_settings_come_without_secrets(shop_app, collab):
    import settings as settings_mod
    s = settings_mod.get_settings()
    s['notifications']['telegram']['bot_token'] = 'SECRET-TOKEN'
    s['notifications']['webhook']['url'] = 'https://hooks.example/abc'
    try:
        body = collab.get('/api/settings').get_json()
        assert body['notifications']['telegram']['bot_token'] == ''
        assert body['notifications']['webhook']['url'] == ''
        assert body['notifications']['telegram']['chat_id'] == s['notifications']['telegram']['chat_id']
        assert 'clientCertKey' not in str(body) or body['shop']['clients']['tinfoil']['clientCertKey'] == ''
    finally:
        s['notifications']['telegram']['bot_token'] = ''
        s['notifications']['webhook']['url'] = ''


def test_graphql_reads_like_an_admin_and_writes_nothing(collab):
    q = '{ apps(appType: [BASE], page: 1, pageSize: 5) { items { files { id } } } }'
    data = collab.post('/api/graphql', json={'query': q}).get_json()
    assert 'errors' not in data and data['data']['apps']['items'][0]['files'] is not None
    m = collab.post('/api/graphql', json={'query': 'mutation { purgeFailedTasks }'}).get_json()
    assert m.get('errors') and 'Admin access' in m['errors'][0]['message']


def test_admin_sets_it_from_the_users_form(shop_app):
    client = shop_app.client
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    with shop_app.app.app_context():
        uid = User.query.filter_by(user="noshop").one().id
    assert client.patch('/api/user', json={'user_id': uid, 'collaborator_access': True}).get_json()['success']
    users = {u['user']: u for u in client.get('/api/users').get_json()}
    assert users['noshop']['collaborator_access'] is True
    # An admin is never also a collaborator.
    client.patch('/api/user', json={'user_id': uid, 'admin_access': True, 'collaborator_access': True})
    with shop_app.app.app_context():
        u = db.session.get(User, uid)
        assert u.admin_access and not u.collaborator_access
        u.admin_access = False
        db.session.commit()


def test_read_only_pages_hide_the_writes():
    css = (ROOT / 'app/static/style.css').read_text(encoding='utf-8')
    for sel in ('.task-cancel', '#verifyNowBtn', '.stats-record-action', '.files-delete', '.users-actions'):
        assert f'html[data-readonly] {sel}' in css
    assert 'html[data-readonly] [data-bs-target="#uploadModal"]' not in css   # they may upload
    assert 'READ_ONLY' in (ROOT / 'app/static/js/files.js').read_text(encoding='utf-8')
    assert 'READ_ONLY' in (ROOT / 'app/static/js/services.js').read_text(encoding='utf-8')


# --- the Saves page says what the server keeps ------------------------------------------

def test_saves_page_states_the_vault_limits(shop_app, monkeypatch):
    import vault
    monkeypatch.setattr(vault, "enabled", lambda: True)
    monkeypatch.setattr(vault, "config", lambda: {"enabled": True, "keep": 5, "max_games": 10,
                                                   "admins": True, "users": True})
    client = shop_app.client
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    client.set_cookie("ownfoil_lang", "es")
    html = client.get("/saves").get_data(as_text=True)
    assert "dash-notice--wait saves-limits" in html
    assert "las últimas 5 copias" in html and "hasta 10 juegos distintos (0 en uso)" in html

    monkeypatch.setattr(vault, "config", lambda: {"enabled": True, "keep": 0, "max_games": 0,
                                                   "admins": True, "users": True})
    html = client.get("/saves").get_data(as_text=True)
    assert "todas las copias de cada juego" in html and "todos los juegos que quieras" in html


def test_downloads_uploaded_saves_from_the_dashboard_only(shop_app, collab, monkeypatch):
    """The Saves page is one's own for everyone; a collaborator, like an admin, downloads
    every upload from the Dashboard's "Uploaded saves"."""
    import vault
    with shop_app.app.app_context():
        other = User.query.filter_by(user="admin").one().id
    asked = []
    monkeypatch.setattr(vault, "backup_path", lambda user, path: asked.append(user) or None)
    assert collab.get(f"/api/admin/saves/download?user={other}&path=Game/a.zip").status_code == 404
    assert asked == [other]                      # reached the download, not refused
    assert collab.get("/saves").status_code == 403   # no Backup permission: no Saves page

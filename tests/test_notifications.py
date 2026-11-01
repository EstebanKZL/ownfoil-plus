"""Push notifications (Settings > Notifications): settings API, batching, each
provider's request, the test button, and the four events wired into the app.
"""
import fixture
import pytest
import yaml

import notifications


class _Response:
    def __init__(self, status_code=200, text='ok'):
        self.status_code, self.text = status_code, text


@pytest.fixture
def posts(monkeypatch):
    """Capture every outgoing HTTP POST instead of sending it."""
    sent = []

    def fake_post(url, **kwargs):
        sent.append({'url': url, **kwargs})
        return _Response()
    monkeypatch.setattr(notifications.requests, 'post', fake_post)
    notifications._pending.clear()
    yield sent
    notifications._pending.clear()


@pytest.fixture
def admin_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code == 302
    return shop_app.client


def _enable(client, **overrides):
    payload = {'enabled': True, 'language': 'en',
               'events': {e: True for e in notifications.EVENTS},
               'discord': {'enabled': True, 'webhook_url': 'https://discord.test/hook'}}
    payload.update(overrides)
    assert client.post('/api/settings/notifications', json=payload).get_json()['success']


# --- settings ------------------------------------------------------------------------

def test_defaults_are_off(shop_app):
    from settings import get_settings
    n = get_settings()['notifications']
    assert n['enabled'] is False
    assert not any(n[p]['enabled'] for p in notifications.PROVIDERS)
    assert not notifications.is_enabled(notifications.EVENT_FILE_ADDED)


def test_saving_coerces_and_ignores_unknown_keys(admin_client):
    admin_client.post('/api/settings/notifications', json={
        'enabled': 1, 'bogus': 'x',
        'telegram': {'enabled': 'yes', 'bot_token': ' 123:abc ', 'chat_id': 42, 'extra': 1}})
    n = admin_client.get('/api/settings').get_json()['notifications']
    assert n['enabled'] is True
    assert n['telegram'] == {'enabled': True, 'bot_token': '123:abc', 'chat_id': '42'}
    assert 'bogus' not in n


def test_unsupported_language_is_rejected(admin_client):
    resp = admin_client.post('/api/settings/notifications', json={'language': 'xx'})
    assert resp.get_json()['success'] is False


def test_non_admin_cannot_change_notifications(shop_app):
    shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    assert shop_app.client.post('/api/settings/notifications', json={'enabled': True}).status_code == 403


def test_shareable_export_drops_notification_credentials(admin_client):
    _enable(admin_client, telegram={'enabled': True, 'bot_token': 'secret', 'chat_id': '1'})
    shared = yaml.safe_load(admin_client.get('/api/settings/export?include_secrets=0').get_data(as_text=True))
    n = shared['notifications']
    assert 'webhook_url' not in n['discord'] and 'bot_token' not in n['telegram']
    assert n['telegram']['chat_id'] == '1'


# --- batching ------------------------------------------------------------------------

def test_nothing_is_queued_while_disabled(shop_app, posts):
    notifications.notify(notifications.EVENT_FILE_ADDED, 'Game')
    notifications.flush()
    assert posts == []


def test_a_burst_becomes_one_message_per_event(admin_client, posts, monkeypatch):
    monkeypatch.setattr(notifications, '_ensure_sender', lambda: None)
    _enable(admin_client)
    for i in range(20):
        notifications.notify(notifications.EVENT_FILE_ADDED, f'Game {i}')
    notifications.notify(notifications.EVENT_TASK_FAILED, 'Scan: boom')
    notifications.flush()

    assert len(posts) == 2
    added = posts[0]['json']['content']
    assert 'Added to the library (20)' in added
    assert 'Game 14' in added and 'Game 15' not in added
    assert '...and 5 more' in added
    assert 'Scan: boom' in posts[1]['json']['content']


def test_disabled_event_is_not_sent(admin_client, posts, monkeypatch):
    monkeypatch.setattr(notifications, '_ensure_sender', lambda: None)
    _enable(admin_client, events={'file_added': False})
    notifications.notify(notifications.EVENT_FILE_ADDED, 'Game')
    notifications.flush()
    assert posts == []


def test_messages_use_the_configured_language(admin_client, posts, monkeypatch):
    monkeypatch.setattr(notifications, '_ensure_sender', lambda: None)
    _enable(admin_client, language='es')
    notifications.notify(notifications.EVENT_FILE_CORRUPT, 'juego.nsp')
    notifications.flush()
    assert 'Archivos corruptos detectados (1)' in posts[0]['json']['content']


def test_a_failing_provider_does_not_raise(admin_client, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError('down')
    monkeypatch.setattr(notifications.requests, 'post', boom)
    monkeypatch.setattr(notifications, '_ensure_sender', lambda: None)
    _enable(admin_client)
    notifications.notify(notifications.EVENT_FILE_ADDED, 'Game')
    notifications.flush()  # must not raise


# --- providers -----------------------------------------------------------------------

def test_provider_requests(shop_app, posts):
    config = {
        'discord': {'enabled': True, 'webhook_url': 'https://discord.test/hook'},
        'telegram': {'enabled': True, 'bot_token': '123:abc', 'chat_id': '99'},
        'ntfy': {'enabled': True, 'server': 'https://ntfy.test/', 'topic': 'games', 'token': 'tk'},
        'webhook': {'enabled': True, 'url': 'https://hook.test/x'},
    }
    results = notifications.send(config, 'file_added', 'Título', ['Zelda v65536'])
    assert results == {p: None for p in notifications.PROVIDERS}

    by_url = {p['url']: p for p in posts}
    assert 'Zelda v65536' in by_url['https://discord.test/hook']['json']['content']
    tg = by_url['https://api.telegram.org/bot123:abc/sendMessage']['json']
    assert tg['chat_id'] == '99' and 'Zelda' in tg['text']
    ntfy = by_url['https://ntfy.test']
    assert ntfy['json']['topic'] == 'games' and ntfy['json']['title'].endswith('Título')
    assert ntfy['headers']['Authorization'] == 'Bearer tk'
    assert by_url['https://hook.test/x']['json'] == {
        'shop': 'Ownfoil-Plus', 'event': 'file_added', 'title': 'Título', 'items': ['Zelda v65536']}


def test_provider_errors_are_reported(shop_app, monkeypatch):
    monkeypatch.setattr(notifications.requests, 'post', lambda *a, **k: _Response(401, 'bad token'))
    results = notifications.send({'discord': {'enabled': True, 'webhook_url': 'https://d.test'},
                                  'telegram': {'enabled': True, 'bot_token': '', 'chat_id': ''}},
                                 'test', 'T', ['x'])
    assert 'HTTP 401' in results['discord']
    assert 'missing' in results['telegram']


def test_connection_errors_are_summarised(shop_app, monkeypatch):
    def refused(*a, **k):
        raise notifications.requests.ConnectionError('HTTPConnectionPool(...) Max retries exceeded ...')
    monkeypatch.setattr(notifications.requests, 'post', refused)
    results = notifications.send({'webhook': {'enabled': True, 'url': 'http://127.0.0.1:9'}}, 'test', 'T', ['x'])
    assert results == {'webhook': 'could not connect'}


# --- test button ---------------------------------------------------------------------

def test_test_button_uses_the_unsaved_form(admin_client, posts):
    resp = admin_client.post('/api/settings/notifications/test', json={
        'language': 'es', 'webhook': {'enabled': True, 'url': 'https://hook.test/y'}})
    body = resp.get_json()
    assert body == {'success': True, 'results': {'webhook': None}}
    assert posts[0]['json']['title'] == 'Notificación de prueba'


def test_test_button_without_a_provider(admin_client, posts):
    body = admin_client.post('/api/settings/notifications/test', json={}).get_json()
    assert body['error'] == 'no_provider'


# --- events wired into the app ---------------------------------------------------------

@pytest.fixture
def captured(monkeypatch):
    got = []
    monkeypatch.setattr(notifications, 'is_enabled', lambda event: True)
    monkeypatch.setattr(notifications, 'notify', lambda event, item: got.append((event, item)))
    return got


def test_new_update_after_titledb_refresh_is_announced(shop_app, captured):
    from db import Apps, Titles, db
    from library import notify_new_apps_available
    with shop_app.app.app_context():
        known = {(a, v) for a, v in db.session.query(Apps.app_id, Apps.app_version).all()}
        title = Titles.query.filter_by(title_id='0100000000010000').one()
        db.session.add(Apps(title_id=title.id, app_id='0100000000010800', app_version='131072',
                            app_type='UPDATE', owned=False))
        db.session.commit()
        notify_new_apps_available(known)

    assert len(captured) == 1
    event, item = captured[0]
    assert event == notifications.EVENT_UPDATE_AVAILABLE
    assert 'v131072' in item and '[UPDATE]' in item


def test_owned_or_already_known_apps_are_not_announced(shop_app, captured):
    from db import Apps, db
    from library import notify_new_apps_available
    with shop_app.app.app_context():
        known = {(a, v) for a, v in db.session.query(Apps.app_id, Apps.app_version).all()}
        notify_new_apps_available(known)
    assert captured == []


def test_corrupt_verification_is_announced(shop_app, captured, monkeypatch):
    import tasks
    from db import Files, db
    monkeypatch.setattr(tasks.verification_lib, 'verify', lambda *a, **k: (True, False, False, 'hash mismatch'))
    monkeypatch.setattr(tasks, 'enqueue_task', lambda *a, **k: None)
    with shop_app.app.app_context():
        from settings import set_library_management_settings
        set_library_management_settings({'verification': {'enabled': True, 'depth': 'hash'}})
        file_id = Files.query.filter_by(extension='nsp').first().id
        tasks.verify_file_task(file_id, manual=True)
        name = db.session.get(Files, file_id).filename
    assert captured == [(notifications.EVENT_FILE_CORRUPT, name)]


def test_valid_verification_is_not_announced(shop_app, captured, monkeypatch):
    import tasks
    from db import Files
    monkeypatch.setattr(tasks.verification_lib, 'verify', lambda *a, **k: (True, True, False, None))
    monkeypatch.setattr(tasks, 'enqueue_task', lambda *a, **k: None)
    with shop_app.app.app_context():
        tasks.verify_file_task(Files.query.filter_by(extension='nsp').first().id, manual=True)
    assert captured == []


def test_first_identification_is_announced_but_not_a_reidentify(shop_app, captured, monkeypatch):
    import tasks
    from db import Files
    content = [{'title_id': '0100000000010000', 'app_id': '0100000000010000', 'type': 'BASE', 'version': '0'}]
    monkeypatch.setattr(tasks.titles_lib, 'identify_file', lambda path: ('cnmt', True, content, None))
    monkeypatch.setattr(tasks, 'enqueue_task', lambda *a, **k: None)
    monkeypatch.setattr(tasks, 'add_file_to_app', lambda *a, **k: None)
    with shop_app.app.app_context():
        mystery = Files.query.filter_by(identified=False).one()
        tasks._identify(mystery, None)
        assert len(captured) == 1 and captured[0][0] == notifications.EVENT_FILE_ADDED
        tasks._identify(mystery, None)  # now identified: a re-identify pass
    assert len(captured) == 1


def test_failed_task_is_announced(shop_app, captured, monkeypatch):
    import tasks
    from worker import TaskWorker
    from db import Task, db

    @tasks.register_task('_test_explodes')
    def explodes(**kwargs):
        raise RuntimeError('kaboom')
    try:
        with shop_app.app.app_context():
            task, _ = tasks.enqueue_task('_test_explodes')
            task_id = task.id
            TaskWorker(shop_app.app, worker_id=1).execute_task(task_id)
            assert db.session.get(Task, task_id).status == 'failed'
    finally:
        tasks.TASK_REGISTRY.pop('_test_explodes', None)
    assert captured and captured[0][0] == notifications.EVENT_TASK_FAILED
    assert 'kaboom' in captured[0][1]

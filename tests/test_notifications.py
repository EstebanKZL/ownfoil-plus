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
        'gotify': {'enabled': True, 'server': 'https://gotify.test/', 'token': 'gk'},
        'pushover': {'enabled': True, 'user_key': 'uk', 'app_token': 'at'},
        'slack': {'enabled': True, 'webhook_url': 'https://hooks.slack.test/s'},
    }
    results = notifications.send(config, 'file_added', 'Título', ['Zelda v65536'])
    assert results == {p: None for p in config}

    by_url = {p['url']: p for p in posts}
    assert 'Zelda v65536' in by_url['https://discord.test/hook']['json']['content']
    tg = by_url['https://api.telegram.org/bot123:abc/sendMessage']['json']
    assert tg['chat_id'] == '99' and 'Zelda' in tg['text']
    ntfy = by_url['https://ntfy.test']
    assert ntfy['json']['topic'] == 'games' and ntfy['json']['title'].endswith('Título')
    assert ntfy['headers']['Authorization'] == 'Bearer tk'
    assert by_url['https://hook.test/x']['json'] == {
        'shop': 'Ownfoil-Plus', 'event': 'file_added', 'title': 'Título', 'items': ['Zelda v65536']}
    gotify = by_url['https://gotify.test/message']
    assert gotify['headers'] == {'X-Gotify-Key': 'gk'} and 'Zelda' in gotify['json']['message']
    push = by_url['https://api.pushover.net/1/messages.json']['data']
    assert push['user'] == 'uk' and push['token'] == 'at' and 'Zelda' in push['message']
    assert 'Zelda v65536' in by_url['https://hooks.slack.test/s']['json']['text']


def test_the_email_channel_sends_html_with_covers(shop_app, monkeypatch):
    import accounts
    sent = []
    monkeypatch.setattr(accounts, 'smtp_config', lambda: {'from': 'shop@example.test'})
    monkeypatch.setattr(accounts, 'public_url', lambda: 'https://shop.example.test')
    monkeypatch.setattr(accounts, 'send_mail', lambda to, subject, body, html=None: sent.append((to, subject, body, html)))
    monkeypatch.setattr(notifications, '_cover', lambda tid: 'https://img.test/cover.jpg' if tid else None)
    config = {'email': {'enabled': True, 'to': 'a@example.test, b@example.test'}}
    results = notifications.send(config, 'update_available', 'New updates (1)', ['Zelda v65536'],
                                 entries=[{'text': 'Zelda v65536', 'title_id': '01007EF00011E000'}], lang='en')
    assert results == {'email': None}
    assert [s[0] for s in sent] == ['a@example.test', 'b@example.test']
    to, subject, body, html = sent[0]
    assert subject == 'Ownfoil-Plus: New updates (1)' and 'Zelda v65536' in body
    assert 'https://img.test/cover.jpg' in html and 'Open the library' in html and 'Zelda v65536' in html


def test_the_email_channel_needs_smtp(shop_app, monkeypatch):
    import accounts
    monkeypatch.setattr(accounts, 'smtp_config', lambda: None)
    results = notifications.send({'email': {'enabled': True, 'to': 'a@example.test'}}, 'test', 'T', ['x'])
    assert 'SMTP' in results['email']


def test_html_emails_escape_what_they_show():
    import mail_html
    html = mail_html.render('Shop <b>', 'Heading & co', ['<script>x</script>'], button=('Go', 'https://x.test/?a=1&b=2'),
                            items=[{'text': '"Game"', 'image': 'https://i.test/a.jpg'}], footer='Sent')
    assert '<script>x' not in html and '&lt;script&gt;' in html and 'Shop &lt;b&gt;' in html
    assert 'href="https://x.test/?a=1&amp;b=2"' in html


def test_an_account_email_puts_its_link_on_a_button():
    import mail_html
    body = ('Hi gamer,\n\nOpen this link to verify your email (it works for a day):\n'
            'https://s.test/verify/abc\n\nIf you did not ask for this, ignore this email.')
    html = mail_html.from_text('Shop', 'Verify your email', body, 'https://s.test/verify/abc', 'Verify my email',
                               'If the button does not work:', 'Sent by Shop.')
    assert '>Verify my email</a>' in html and 'href="https://s.test/verify/abc"' in html
    assert 'Hi gamer,' in html and 'If you did not ask for this' in html


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
    monkeypatch.setattr(notifications, 'notify', lambda event, item, title_id=None: got.append((event, item)))
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


def _flush_with(monkeypatch, config, *events):
    notifications._pending.clear()
    notifications.forget_subscribers()
    monkeypatch.setattr(notifications, '_ensure_sender', lambda: None)
    monkeypatch.setattr(notifications, '_config', lambda: config)
    for event, item in events:
        notifications.notify(event, item, title_id='01007EF00011E000')
    notifications.flush()


def test_users_who_asked_get_the_email_with_no_channel_set_up(shop_app, monkeypatch):
    """Asked for: notifications on in the server and a user who wants them (My account,
    verified email) is enough - the admin needn't turn on the email channel. A user gets
    the game news; only an admin also gets the housekeeping."""
    import accounts
    from db import User, db
    sent = []
    monkeypatch.setattr(accounts, 'smtp_config', lambda: {'from': 'shop@example.test'})
    monkeypatch.setattr(accounts, 'public_url', lambda: None)
    monkeypatch.setattr(accounts, 'send_mail', lambda to, subject, body, html=None: sent.append(to))
    config = {'enabled': True, 'language': 'en', 'events': {e: True for e in notifications.EVENTS}}
    with shop_app.app.app_context():
        for name, email in (('admin', 'boss@example.test'), ('shopper', 'fan@example.test'), ('noshop', 'nope@example.test')):
            u = User.query.filter_by(user=name).one()
            u.email, u.email_verified, u.notify_email = email, name != 'noshop', True
        db.session.commit()
        _flush_with(monkeypatch, config, (notifications.EVENT_UPDATE_AVAILABLE, 'Zelda v65536'))
        assert sorted(sent) == ['boss@example.test', 'fan@example.test']     # not the unverified one
        sent.clear()
        _flush_with(monkeypatch, config, (notifications.EVENT_TASK_FAILED, 'Scan: boom'))
        assert sent == ['boss@example.test']
        sent.clear()
        _flush_with(monkeypatch, {**config, 'enabled': False}, (notifications.EVENT_UPDATE_AVAILABLE, 'Zelda'))
        assert sent == []                                                     # notifications off: nothing
        # The test button: only the addresses set in Settings, never the users.
        assert 'missing' in notifications.send({'email': {'enabled': True, 'to': ''}}, 'test', 'T', ['x'])['email']


def test_my_account_keeps_the_choice_only_with_a_verified_email(shop_app):
    import fixture
    from db import User, db
    client = shop_app.client
    client.post('/login', data={'user': 'shopper', 'password': fixture.PASSWORDS['shopper']})
    client.post('/api/account', json={'console_firmware': '', 'show_background_image': 'default', 'notify_email': True})
    with shop_app.app.app_context():
        assert User.query.filter_by(user='shopper').one().notify_email is False
        u = User.query.filter_by(user='shopper').one()
        u.email, u.email_verified = 'fan@example.test', True
        db.session.commit()
    client.post('/api/account', json={'console_firmware': '', 'show_background_image': 'default', 'notify_email': True})
    with shop_app.app.app_context():
        assert User.query.filter_by(user='shopper').one().notify_email is True


def test_each_user_gets_the_email_in_their_language(shop_app, monkeypatch):
    """Each user's email is in the language set in My account (or, until then, the one
    they browse in)."""
    import accounts
    import fixture
    from db import User, db
    client = shop_app.client
    client.post('/login', data={'user': 'shopper', 'password': fixture.PASSWORDS['shopper']})
    client.set_cookie('ownfoil_lang', 'es')
    client.get('/account')
    with shop_app.app.app_context():
        assert User.query.filter_by(user='shopper').one().language == 'es'   # filled in from the web
    resp = client.post('/api/account', json={'console_firmware': '', 'show_background_image': 'default', 'language': 'fr'})
    assert resp.get_json()['success'] and 'ownfoil_lang=fr' in resp.headers.get('Set-Cookie', '')
    with shop_app.app.app_context():
        assert User.query.filter_by(user='shopper').one().language == 'fr'   # My account's choice
        for name, email in (('admin', 'boss@example.test'), ('shopper', 'fan@example.test')):
            u = User.query.filter_by(user=name).one()
            u.email, u.email_verified, u.notify_email = email, True, True
            if name == 'admin':
                u.language = 'en'
        db.session.commit()
        sent = {}
        monkeypatch.setattr(accounts, 'smtp_config', lambda: {'from': 'shop@example.test'})
        monkeypatch.setattr(accounts, 'public_url', lambda: None)
        monkeypatch.setattr(accounts, 'send_mail', lambda to, subject, body, html=None: sent.__setitem__(to, subject))
        _flush_with(monkeypatch, {'enabled': True, 'language': 'en', 'events': {'update_available': True}},
                    (notifications.EVENT_UPDATE_AVAILABLE, 'Zelda v65536'))
    from i18n import TRANSLATIONS
    title = TRANSLATIONS['notify.event.update_available.title']
    assert title['en'].split('{')[0].strip() in sent['boss@example.test']
    assert title['fr'].split('{')[0].strip() in sent['fan@example.test']


def test_slack_escapes_names_that_could_ping_the_channel(shop_app, posts):
    notifications.send({'slack': {'enabled': True, 'webhook_url': 'https://hooks.slack.test/s'}},
                       'file_added', 'T', ['<!channel> Game & co'])
    text = posts[0]['json']['text']
    assert '<!channel>' not in text and '&lt;!channel&gt; Game &amp; co' in text


def test_a_user_without_shop_access_gets_no_game_news(shop_app, monkeypatch):
    from db import User, db
    with shop_app.app.app_context():
        u = User.query.filter_by(user='noshop').one()
        u.email, u.email_verified, u.notify_email = 'nope@example.test', True, True
        db.session.commit()
        notifications.forget_subscribers()
        assert 'nope@example.test' not in [e for e, _ in notifications._subscribers('update_available')]

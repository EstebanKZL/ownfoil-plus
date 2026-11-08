"""Push notifications: tell the admin when something happens in the library, through
Discord, Telegram, ntfy, Gotify, Pushover, Slack, email or a generic JSON webhook
(Settings > Notifications).

Events are batched: a scan can identify hundreds of files in a minute, and one message
per file would flood the channel (and hit Discord/Telegram rate limits). `notify()`
only queues; a per-process background thread waits BATCH_SECONDS after the first
queued item, then sends one message per event type listing what accumulated. Worker
processes each run their own sender - fine, they each batch what they produced.

Sending never raises into the caller: a down webhook must not fail a scan.
"""
import logging
import re
import threading
import time

import requests

from i18n import TRANSLATIONS, DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from settings import get_settings

logger = logging.getLogger('main')

EVENT_FILE_ADDED = 'file_added'
EVENT_UPDATE_AVAILABLE = 'update_available'
EVENT_FILE_CORRUPT = 'file_corrupt'
EVENT_TASK_FAILED = 'task_failed'
EVENT_SAVE_BACKUP = 'save_backup'
EVENTS = (EVENT_FILE_ADDED, EVENT_UPDATE_AVAILABLE, EVENT_FILE_CORRUPT, EVENT_TASK_FAILED, EVENT_SAVE_BACKUP)

PROVIDERS = ('discord', 'telegram', 'ntfy', 'gotify', 'pushover', 'slack', 'email', 'webhook')

BATCH_SECONDS = 20
MAX_ITEMS_LISTED = 15
TIMEOUT = 10

_pending = {}  # event -> [item, ...]
_lock = threading.Lock()
_wakeup = threading.Event()
_sender = None


def _text(key, lang, **kwargs):
    entry = TRANSLATIONS.get(key, {})
    text = entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or key
    return text.format(**kwargs) if kwargs else text


def _config():
    return get_settings().get('notifications', {})


def _active_providers(config):
    return [name for name in PROVIDERS if config.get(name, {}).get('enabled')]


def is_enabled(event):
    """Whether `event` would be delivered anywhere right now - lets callers skip
    building a message (title lookups etc.) nobody will receive."""
    try:
        config = _config()
    except Exception:
        return False
    return bool(config.get('enabled') and config.get('events', {}).get(event)
                and (_active_providers(config) or _subscribers(event)))


def notify(event, item, title_id=None):
    """Queue one line (`item`, already human-readable) under `event` - with the game it
    is about, when there is one: the email shows its cover."""
    if event not in EVENTS or not is_enabled(event):
        return
    with _lock:
        _pending.setdefault(event, []).append((str(item), title_id))
    _ensure_sender()
    _wakeup.set()


def _ensure_sender():
    global _sender
    with _lock:
        if _sender is None or not _sender.is_alive():
            _sender = threading.Thread(target=_sender_loop, name='notifications', daemon=True)
            _sender.start()


def _sender_loop():
    while True:
        _wakeup.wait()
        # Let the burst finish (a scan, a TitleDB refresh) before sending.
        time.sleep(BATCH_SECONDS)
        _wakeup.clear()
        flush()


def flush():
    """Send everything queued now. Called by the sender thread; tests call it directly."""
    with _lock:
        batch = dict(_pending)
        _pending.clear()
    if not batch:
        return
    config = _config()
    lang = config.get('language') if config.get('language') in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    for event in EVENTS:
        items = batch.get(event)
        if not items:
            continue
        title = _text(f'notify.event.{event}.title', lang, count=len(items))
        entries = [{'text': text, 'title_id': tid} for text, tid in items[:MAX_ITEMS_LISTED]]
        lines = [e['text'] for e in entries]
        if len(items) > MAX_ITEMS_LISTED:
            lines.append(_text('notify.more', lang, count=len(items) - MAX_ITEMS_LISTED))
        send(config, event, title, lines, entries=entries, lang=lang, total=len(items))
        _send_user_emails(config, event, title, lines, entries, lang, len(items))


def _shop_name():
    return get_settings()['shop'].get('name') or 'Ownfoil-Plus'


def send(config, event, title, lines, entries=None, lang=None, total=None):
    """Deliver one message to every enabled provider. Returns {provider: error or None}."""
    results = {}
    for name in _active_providers(config):
        try:
            if name == 'email':
                _send_email(config[name], event, title, lines, entries or [], lang or DEFAULT_LANGUAGE, total)
            else:
                SENDERS[name](config[name], event, title, lines)
            results[name] = None
        except requests.Timeout:
            logger.warning(f'Notification via {name} failed: timed out')
            results[name] = 'timed out'
        except requests.ConnectionError as e:
            # The raw message is a screenful of urllib3 retry details.
            logger.warning(f'Notification via {name} failed: {e}')
            results[name] = 'could not connect'
        except Exception as e:
            logger.warning(f'Notification via {name} failed: {e}')
            results[name] = str(e)
    return results


def _plain(title, lines):
    return f'{title}\n' + '\n'.join(f'• {line}' for line in lines)


def _check(response):
    if response.status_code >= 400:
        raise RuntimeError(f'HTTP {response.status_code}: {response.text[:200]}')


def _send_discord(cfg, event, title, lines):
    url = (cfg.get('webhook_url') or '').strip()
    if not url:
        raise ValueError('missing webhook URL')
    content = f'**{title}**\n' + '\n'.join(f'• {line}' for line in lines)
    # Names come from files and folders: '@everyone' in one must not ping the channel.
    _check(requests.post(url, json={'content': content[:2000], 'username': _shop_name(),
                                    'allowed_mentions': {'parse': []}},
                         timeout=TIMEOUT))


def _send_telegram(cfg, event, title, lines):
    token, chat_id = (cfg.get('bot_token') or '').strip(), str(cfg.get('chat_id') or '').strip()
    if not token or not chat_id:
        raise ValueError('missing bot token or chat id')
    text = f'{_shop_name()} - {_plain(title, lines)}'
    _check(requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                         json={'chat_id': chat_id, 'text': text[:4096],
                               'disable_web_page_preview': True},
                         timeout=TIMEOUT))


def _send_ntfy(cfg, event, title, lines):
    server = (cfg.get('server') or 'https://ntfy.sh').strip().rstrip('/')
    topic = (cfg.get('topic') or '').strip().strip('/')
    if not topic:
        raise ValueError('missing topic')
    # JSON publishing (POST to the server root), not headers: a Title header can't
    # carry non-ASCII, and game names and the Spanish texts often do.
    headers = {}
    if cfg.get('token'):
        headers['Authorization'] = f'Bearer {cfg["token"].strip()}'
    _check(requests.post(server, json={
        'topic': topic, 'title': f'{_shop_name()}: {title}', 'tags': ['video_game'],
        'message': '\n'.join(f'• {line}' for line in lines)}, headers=headers, timeout=TIMEOUT))


def _send_webhook(cfg, event, title, lines):
    url = (cfg.get('url') or '').strip()
    if not url:
        raise ValueError('missing URL')
    _check(requests.post(url, json={'shop': _shop_name(), 'event': event, 'title': title,
                                    'items': lines}, timeout=TIMEOUT))


def _send_gotify(cfg, event, title, lines):
    server = (cfg.get('server') or '').strip().rstrip('/')
    token = (cfg.get('token') or '').strip()
    if not server or not token:
        raise ValueError('missing server or app token')
    # The token in a header, not the URL: URLs end up in proxy logs.
    _check(requests.post(f'{server}/message', headers={'X-Gotify-Key': token}, timeout=TIMEOUT,
                         json={'title': f'{_shop_name()}: {title}', 'priority': 5,
                               'message': '\n'.join(f'• {line}' for line in lines)}))


def _send_pushover(cfg, event, title, lines):
    user, token = (cfg.get('user_key') or '').strip(), (cfg.get('app_token') or '').strip()
    if not user or not token:
        raise ValueError('missing user key or app token')
    _check(requests.post('https://api.pushover.net/1/messages.json', timeout=TIMEOUT, data={
        'token': token, 'user': user, 'title': f'{_shop_name()}: {title}'[:250],
        'message': '\n'.join(f'• {line}' for line in lines)[:1024]}))


def _send_slack(cfg, event, title, lines):
    url = (cfg.get('webhook_url') or '').strip()
    if not url:
        raise ValueError('missing webhook URL')
    # Slack reads <...> as links and mentions (<!channel>): names come from files and
    # folders, so &, < and > are escaped as its formatting rules ask.
    def esc(text):
        return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = f'*{esc(_shop_name())}: {esc(title)}*\n' + '\n'.join(f'• {esc(line)}' for line in lines)
    _check(requests.post(url, json={'text': text[:3000]}, timeout=TIMEOUT))


def _cover(title_id):
    """A game's icon for an email, only when it is a full web address (a local media
    path means nothing in a mail client)."""
    if not title_id:
        return None
    try:
        import titles as titles_lib
        url = (titles_lib.get_game_info(title_id) or {}).get('iconUrl') or ''
    except Exception:
        return None
    return url if url.startswith(('https://', 'http://')) else None


# What a user who isn't an admin gets by email (My account): news about games, not the
# server's housekeeping (corrupt files, failed tasks, other people's saves).
USER_EVENTS = (EVENT_FILE_ADDED, EVENT_UPDATE_AVAILABLE)


_subscribers_cache = {'at': 0.0, 'users': []}
SUBSCRIBERS_TTL = 30


def _subscribers(event):
    """The users who asked for the server's news by email (My account), with a verified
    address, as (email, their language): admins for every event, the others for
    USER_EVENTS only. Read at most every SUBSCRIBERS_TTL seconds - notify() asks for each
    file of a scan."""
    now = time.monotonic()
    if now - _subscribers_cache['at'] > SUBSCRIBERS_TTL:
        try:
            from db import User
            users = User.query.filter(User.notify_email.is_(True), User.email_verified.is_(True),
                                      User.email.isnot(None), User.pending.is_(False)).all()
            # Only who may see the library: game news to a user without shop access would
            # tell them what they can't open. Admins always may.
            _subscribers_cache['users'] = [(u.email, u.language if u.language in SUPPORTED_LANGUAGES else None,
                                            bool(u.admin_access)) for u in users
                                           if u.email and (u.admin_access or u.shop_access)]
        except Exception:
            _subscribers_cache['users'] = []
        _subscribers_cache['at'] = now
    return [(email, lang) for email, lang, admin in _subscribers_cache['users']
            if admin or event in USER_EVENTS]


def forget_subscribers():
    """Read the subscribers again next time (a user just changed their choice)."""
    _subscribers_cache['at'] = 0.0


def _channel_addresses(config):
    """The addresses the email channel sends to, when it is on."""
    cfg = config.get('email') or {}
    if not cfg.get('enabled'):
        return []
    return [a.strip() for a in re.split(r'[,;\s]+', cfg.get('to') or '') if a.strip()]


def _deliver_emails(recipients, event, title, lines, entries, lang, total=None):
    """The HTML email to each (address, language): the event as heading, a row per item -
    with the game's cover when it's about a game - and a button to the library; one
    version per language."""
    import accounts
    import mail_html
    if accounts.smtp_config() is None:
        raise RuntimeError('SMTP is not configured (SMTP_* variables)')
    for address, _ in recipients:
        if not accounts.valid_email(address):
            raise ValueError(f'invalid address: {address}')
    shop = _shop_name()
    base = accounts.public_url()
    covers = {e.get('title_id'): _cover(e.get('title_id')) for e in entries}
    count = total if total is not None else len(entries)
    by_lang = {}
    for address, address_lang in recipients:
        by_lang.setdefault(address_lang or lang, []).append(address)
    for mail_lang, addresses in by_lang.items():
        # The texts in this language: the heading, and "...and N more" when cut short.
        if event in EVENTS and mail_lang != lang:
            mail_title = _text(f'notify.event.{event}.title', mail_lang, count=count)
            mail_lines = [e['text'] for e in entries]
            if count > len(entries):
                mail_lines.append(_text('notify.more', mail_lang, count=count - len(entries)))
        else:
            mail_title, mail_lines = title, lines
        items = ([{'text': e['text'], 'image': covers.get(e.get('title_id'))} for e in entries]
                 or [{'text': line} for line in mail_lines])
        extra = mail_lines[len(entries):] if entries else []
        html = mail_html.render(shop, mail_title, extra, items=items,
                                button=(_text('notif.email_open', mail_lang), base) if base else None,
                                footer=_text('mail.footer', mail_lang, shop=shop))
        text = _plain(mail_title, mail_lines)
        for address in addresses:
            accounts.send_mail(address, f'{shop}: {mail_title}', text, html=html)


def _send_email(cfg, event, title, lines, entries, lang, total=None):
    """The email channel (Settings > Notifications): the addresses set there, in the
    messages' language."""
    to = _channel_addresses({'email': {**cfg, 'enabled': True}})
    if not to:
        raise ValueError('missing address')
    _deliver_emails([(a, lang) for a in to], event, title, lines, entries, lang, total)


def _send_user_emails(config, event, title, lines, entries, lang, total):
    """Every user who asked for the news by email (My account) gets it at their verified
    address, in their language - with notifications on, whatever channels are set up.
    An address the email channel already covers isn't sent twice."""
    taken = {a.lower() for a in _channel_addresses(config)}
    recipients = [(e, user_lang) for e, user_lang in _subscribers(event) if e.lower() not in taken]
    if not recipients:
        return
    try:
        _deliver_emails(recipients, event, title, lines, entries, lang, total)
    except Exception as e:
        logger.warning(f'Notification emails to users failed: {e}')

SENDERS = {
    'discord': _send_discord,
    'telegram': _send_telegram,
    'ntfy': _send_ntfy,
    'gotify': _send_gotify,
    'pushover': _send_pushover,
    'slack': _send_slack,
    'webhook': _send_webhook,
}


def send_test(config):
    """Send a test message right away, through every enabled provider of `config`
    (the form as currently filled in, not necessarily saved yet)."""
    lang = config.get('language') if config.get('language') in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    return send(config, 'test', _text('notify.test.title', lang), [_text('notify.test.body', lang)])


# --- message helpers for callers ------------------------------------------------------

def app_label(title_id, app_type=None, version=None):
    """"Title Name [DLC] v65536" - best effort, never raises."""
    try:
        import titles as titles_lib
        name = titles_lib.get_game_info(title_id).get('name') or title_id
    except Exception:
        name = title_id
    if name == 'Unrecognized':
        name = title_id
    parts = [name]
    if app_type and app_type != 'BASE':
        parts.append(f'[{app_type}]')
    if version not in (None, '', '0', 0):
        parts.append(f'v{version}')
    return ' '.join(parts)

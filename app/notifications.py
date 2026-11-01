"""Push notifications: tell the admin when something happens in the library, through
Discord, Telegram, ntfy or a generic JSON webhook (Settings > Notifications).

Events are batched: a scan can identify hundreds of files in a minute, and one message
per file would flood the channel (and hit Discord/Telegram rate limits). `notify()`
only queues; a per-process background thread waits BATCH_SECONDS after the first
queued item, then sends one message per event type listing what accumulated. Worker
processes each run their own sender - fine, they each batch what they produced.

Sending never raises into the caller: a down webhook must not fail a scan.
"""
import logging
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
EVENTS = (EVENT_FILE_ADDED, EVENT_UPDATE_AVAILABLE, EVENT_FILE_CORRUPT, EVENT_TASK_FAILED)

PROVIDERS = ('discord', 'telegram', 'ntfy', 'webhook')

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
                and _active_providers(config))


def notify(event, item):
    """Queue one line (`item`, already human-readable) under `event`."""
    if event not in EVENTS or not is_enabled(event):
        return
    with _lock:
        _pending.setdefault(event, []).append(str(item))
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
        lines = items[:MAX_ITEMS_LISTED]
        if len(items) > MAX_ITEMS_LISTED:
            lines.append(_text('notify.more', lang, count=len(items) - MAX_ITEMS_LISTED))
        send(config, event, title, lines)


def _shop_name():
    return get_settings()['shop'].get('name') or 'Ownfoil-Plus'


def send(config, event, title, lines):
    """Deliver one message to every enabled provider. Returns {provider: error or None}."""
    results = {}
    for name in _active_providers(config):
        try:
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
    _check(requests.post(url, json={'content': content[:2000], 'username': _shop_name()},
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


SENDERS = {
    'discord': _send_discord,
    'telegram': _send_telegram,
    'ntfy': _send_ntfy,
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

"""Resumable uploads of game files from the web UI (Files page, admin only).

The browser sends a file in chunks, each one appended at the offset the server says it
has. An upload is identified by (library, filename, size), so picking the same file
again after a dropped connection, a closed tab or a server restart resumes it instead of
starting over.

The partial file lives in the target library itself, as a hidden `.part` file the scan
and the watcher ignore (not a game extension), so finishing is a rename, not a copy of
several GB across filesystems. The rename is what the file watcher sees; `add_file` is
also queued explicitly so it works with the watcher off (a duplicate is deduplicated).

Session metadata is a small JSON file per upload under DATA_DIR/uploads, so it survives
restarts without a database table. Partial files left alone for STALE_DAYS are removed.
"""
import datetime
import hashlib
import json
import logging
import os
import shutil
import threading

from constants import ALLOWED_EXTENSIONS, DATA_DIR

logger = logging.getLogger('main')

SESSION_DIR = os.path.join(DATA_DIR, 'uploads')
STALE_DAYS = 7
READ_BLOCK = 4 * 1024 * 1024   # bigger reads: fewer Python round trips per chunk

# Characters no supported filesystem takes in a name (Windows is the strictest).
_FORBIDDEN = set('<>:"/\\|?*')

_locks = {}
_locks_guard = threading.Lock()


class UploadError(Exception):
    """A refused request: `status` is the HTTP status, `code` a stable key for the UI."""

    def __init__(self, code, message, status=400, **extra):
        super().__init__(message)
        self.code, self.status, self.extra = code, status, extra


def sanitize_filename(name):
    """The bare file name to store, or UploadError. Keeps brackets and Unicode: a
    title ID in brackets is how a file is identified without keys."""
    name = os.path.basename(str(name or '').replace('\\', '/')).strip()
    name = ''.join(ch for ch in name if ch not in _FORBIDDEN and ord(ch) >= 32)
    name = name.strip(' .')
    if not name:
        raise UploadError('bad_name', 'Invalid file name')
    extension = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadError('bad_extension', f'Only {", ".join(ALLOWED_EXTENSIONS)} files can be uploaded')
    return name


def _upload_id(library, filename, size):
    return hashlib.sha256(f'{library}\0{filename}\0{size}'.encode('utf-8')).hexdigest()[:32]


def _session_path(upload_id):
    return os.path.join(SESSION_DIR, f'{upload_id}.json')


def _lock(upload_id):
    with _locks_guard:
        return _locks.setdefault(upload_id, threading.Lock())


def _load(upload_id, user=None):
    """One upload session. With `user`, only that user's: an upload belongs to whoever
    started it, and to anyone else it doesn't exist (no adding to it, no cancelling it)."""
    if not upload_id or not all(c in '0123456789abcdef' for c in upload_id):
        raise UploadError('not_found', 'No such upload', 404)
    try:
        with open(_session_path(upload_id), encoding='utf-8') as f:
            session = json.load(f)
    except FileNotFoundError:
        raise UploadError('not_found', 'No such upload', 404)
    if user is not None and session.get('user') not in (None, user):
        raise UploadError('not_found', 'No such upload', 404)
    return session


def _save(session):
    os.makedirs(SESSION_DIR, exist_ok=True)
    tmp = _session_path(session['id']) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(session, f)
    os.replace(tmp, _session_path(session['id']))


def _offset(session):
    try:
        return os.path.getsize(session['partial'])
    except OSError:
        return 0


def _public(session):
    return {
        'id': session['id'], 'library': session['library'], 'filename': session['filename'],
        'size': session['size'], 'offset': _offset(session), 'created': session['created'],
    }


def start(library, filename, size, libraries, user=None):
    """Create or resume an upload. Returns its public state (with the offset to send from).
    The session belongs to `user`: another user starting the same file gets a refusal."""
    if library not in libraries:
        raise UploadError('bad_library', 'Unknown library')
    filename = sanitize_filename(filename)
    try:
        size = int(size)
    except (TypeError, ValueError):
        raise UploadError('bad_size', 'Invalid size')
    if size <= 0:
        raise UploadError('bad_size', 'Empty file')
    if not os.path.isdir(library):
        raise UploadError('library_offline', 'The library folder is not reachable', 409)

    final = os.path.join(library, filename)
    if os.path.exists(final):
        raise UploadError('exists', 'A file with that name is already in the library', 409)

    upload_id = _upload_id(library, filename, size)
    with _lock(upload_id):
        try:
            session = _load(upload_id)
        except UploadError:
            session = None
        if session is not None and session.get('user') not in (None, user):
            raise UploadError('exists', 'Someone else is uploading a file with that name', 409)
        if session is None:
            session = {
                'id': upload_id, 'library': library, 'filename': filename, 'size': size, 'user': user,
                'final': final, 'partial': os.path.join(library, f'.{filename}.{upload_id[:8]}.part'),
                'created': datetime.datetime.now().isoformat(timespec='seconds'),
            }
        needed = size - _offset(session)
        if shutil.disk_usage(library).free < needed:
            raise UploadError('no_space', 'Not enough free space in the library', 507,
                              needed=needed, free=shutil.disk_usage(library).free)
        session['touched'] = datetime.datetime.now().isoformat(timespec='seconds')
        _save(session)
        if not os.path.exists(session['partial']):
            open(session['partial'], 'ab').close()
        return _public(session)


def status(upload_id, user=None):
    return _public(_load(upload_id, user))


def append(upload_id, offset, stream, length, user=None):
    """Append `length` bytes from `stream` at `offset`. Returns (state, finished_path):
    finished_path is the library file once the last byte has landed, else None."""
    with _lock(upload_id):
        session = _load(upload_id, user)
        current = _offset(session)
        if offset != current:
            # Lost response, retried chunk, two tabs: tell the client where we really are.
            raise UploadError('offset_mismatch', 'Offset does not match', 409, offset=current)
        if length is None or length < 0:
            raise UploadError('bad_length', 'Content-Length required', 411)
        if current + length > session['size']:
            raise UploadError('too_large', 'More data than the declared size', 400)

        received = 0
        with open(session['partial'], 'ab') as f:
            while received < length:
                block = stream.read(min(READ_BLOCK, length - received))
                if not block:
                    break
                f.write(block)
                received += len(block)
        session['touched'] = datetime.datetime.now().isoformat(timespec='seconds')
        _save(session)

        if _offset(session) < session['size']:
            return _public(session), None
        return _finish(session)


def _finish(session):
    if os.path.exists(session['final']):
        raise UploadError('exists', 'A file with that name appeared in the library meanwhile', 409)
    os.replace(session['partial'], session['final'])
    _remove_session(session['id'])
    logger.info(f'Upload finished: {session["final"]}')
    state = {**_public(session), 'offset': session['size'], 'finished': True}
    return state, session['final']


def _remove_session(upload_id):
    try:
        os.remove(_session_path(upload_id))
    except FileNotFoundError:
        pass


def cancel(upload_id, user=None):
    with _lock(upload_id):
        session = _load(upload_id, user)
        try:
            os.remove(session['partial'])
        except FileNotFoundError:
            pass
        _remove_session(upload_id)


def list_sessions(user=None):
    """Unfinished uploads (with `user`, only that user's), newest first."""
    try:
        names = [n for n in os.listdir(SESSION_DIR) if n.endswith('.json')]
    except FileNotFoundError:
        return []
    sessions = []
    for name in names:
        try:
            sessions.append(_public(_load(name[:-5], user)))
        except (UploadError, ValueError, OSError):
            continue
    return sorted(sessions, key=lambda s: s['created'], reverse=True)


def cleanup_stale(max_age_days=STALE_DAYS):
    """Drop uploads nobody has touched for `max_age_days`, partial file included."""
    cutoff = datetime.datetime.now() - datetime.timedelta(days=max_age_days)
    removed = 0
    try:
        names = [n for n in os.listdir(SESSION_DIR) if n.endswith('.json')]
    except FileNotFoundError:
        return 0
    for name in names:
        try:
            session = _load(name[:-5])
            touched = datetime.datetime.fromisoformat(session.get('touched') or session['created'])
        except (UploadError, ValueError, KeyError, OSError):
            continue
        if touched < cutoff:
            cancel(session['id'])
            removed += 1
    if removed:
        logger.info(f'Removed {removed} abandoned upload(s).')
    return removed

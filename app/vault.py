"""The save vault: where the console keeps its save backups.

JKSV, the save manager of the Switch, uploads its backups over WebDAV. The server answers
at /dav/ only while an admin has the vault turned on (Services), to users with the Backup
permission (or admins), each with their web user name and their own vault password - set
in My account, never the web password. Each user has their own space,
data/saves/users/<user id>/: nobody reaches another's backups, from the console or the
web (admins see everyone's on the Saves page). JKSV makes a folder per game under "JKSV"
and uploads one ZIP per backup, with a small `.nx_save_meta.bin` inside telling the title
ID and the time - that is how each backup is matched to its game.

Only what JKSV does is answered (OPTIONS, GET/HEAD, PROPFIND one level deep, MKCOL, PUT,
DELETE, MOVE), and even with the right password changes stay inside the JKSV folder and
are ZIP files: never a path out of it, never a whole game folder deleted, never a full
disk. An upload takes the place of a backup only once it arrived whole.

The design follows the save vault of Switch Library Manager Web by DeLFuS77 (AGPL-3.0,
see NOTICE.md).
"""
import datetime
import email.utils
import hashlib
import hmac
import re
import zlib
import logging
import os
import posixpath
import shutil
import struct
import threading
import time
import uuid
from urllib.parse import quote, unquote, urlsplit
from xml.sax.saxutils import escape

from flask import Response, request, send_file
from werkzeug.security import check_password_hash, generate_password_hash

import auth
from constants import DATA_DIR
from settings import get_settings

logger = logging.getLogger('main')

SAVES_DIR = os.path.join(DATA_DIR, 'saves')
PREFIX = '/dav'
BASE = 'JKSV'                       # the folder JKSV is told to use ("basepath")
KEEP_CHOICES = (0, 2, 5, 10, 20, 50)    # backups kept per game; 0 keeps them all
GAME_CHOICES = (0, 10, 20, 30, 40, 50)  # different games each user may keep; 0: no limit
MIN_FREE = 512 << 20                # an upload must leave this much free (small SD cards too)
MAX_UPLOAD = 4 << 30                # a save backup is rarely more than a few hundred MB
MAX_ZIP_ENTRIES = 20000             # a real save has a handful of files
MAX_NAME_BYTES = 1024               # per central directory entry: name + extra + comment
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')
METHODS = ['OPTIONS', 'GET', 'HEAD', 'PROPFIND', 'MKCOL', 'PUT', 'DELETE', 'MOVE']
META_NAME = '.nx_save_meta.bin'
META_MAGIC = 0x56534B4A             # "JKSV"
AUTH_CACHE_SECONDS = 600            # JKSV sends the password with every request
CHUNK = 1 << 20

_auth_cache = {}
_auth_lock = threading.Lock()
_meta_cache = {}
_meta_lock = threading.Lock()


def clear_auth_cache():
    with _auth_lock:
        _auth_cache.clear()


def _free_bytes(path):
    for folder in (path, os.path.dirname(path)):
        try:
            return shutil.disk_usage(folder).free
        except OSError:
            continue
    return None


def config():
    return get_settings().get('vault') or {}


def enabled():
    return bool(config().get('enabled'))


def user_root(user_id):
    """A user's own space; their JKSV folder is inside it."""
    return os.path.join(SAVES_DIR, 'users', str(int(user_id)))


def max_games():
    return int(config().get('max_games') or 0)


def _games_in(root):
    """The game folders of a user's JKSV space that hold at least one backup."""
    base = _disk('/' + BASE, root)
    try:
        folders = os.listdir(base)
    except OSError:
        return set()
    games = set()
    for folder in folders:
        path = os.path.join(base, folder)
        try:
            if os.path.isdir(path) and any(n.lower().endswith('.zip') for n in os.listdir(path)):
                games.add(folder)
        except OSError:
            continue
    return games


def game_limit_reached(root, folder):
    """Whether a backup into `folder` would be one game too many: the limit counts
    different games, never their backups. A game already kept always takes more; deleting
    every backup of a game frees its place. Nothing is ever deleted to make room."""
    limit = max_games()
    if not limit:
        return False
    games = _games_in(root)
    return folder not in games and len(games) >= limit


def may_use(user):
    """Who may keep saves in the vault - and so sees the Saves page and the vault in My
    account: admins when Settings > Save vault allows admins, users with the Backup
    permission when it allows users; never a registration still waiting for its email."""
    if not user or user.pending:
        return False
    cfg = config()
    if user.admin_access:
        return bool(cfg.get('admins', True))
    return bool(user.backup_access) and bool(cfg.get('users', True))


# --- the shared space from before -----------------------------------------------------

_adopt_lock = threading.Lock()


def adopt_shared_backups():
    """The vault used to have one space for everyone, data/saves/JKSV. Its backups move to
    the first admin's space (once; games already there keep theirs)."""
    old = os.path.join(SAVES_DIR, BASE)
    if not os.path.isdir(old):
        return
    from db import User
    with _adopt_lock:
        if not os.path.isdir(old):
            return
        admin = User.query.filter_by(admin_access=True).order_by(User.id).first()
        if admin is None:
            return
        target = os.path.join(user_root(admin.id), BASE)
        os.makedirs(target, exist_ok=True)
        for game in os.listdir(old):
            source, dest = os.path.join(old, game), os.path.join(target, game)
            if not os.path.exists(dest):
                shutil.move(source, dest)
            elif os.path.isdir(source):
                for name in os.listdir(source):
                    if not os.path.exists(os.path.join(dest, name)):
                        shutil.move(os.path.join(source, name), os.path.join(dest, name))
        shutil.rmtree(old, ignore_errors=True)
        logger.info(f'Save vault: the shared backups moved to {admin.user!r}\'s space')


# --- who gets in ----------------------------------------------------------------------

_dummy_hash = []


def _cache_key(username, password):
    return (username, hashlib.sha256((password or '').encode()).hexdigest())


def _vault_user(username):
    from db import User
    return User.query.filter_by(user=username).first() if username else None


def _cached_login(username, password):
    """The user, when these credentials were verified in the last minutes: they skip the
    hash check and the lockout, so someone guessing (from behind the same proxy, say)
    can't lock the console out. The user is read again every time: a vault password
    changed or a permission taken away counts at once."""
    with _auth_lock:
        hit = _auth_cache.get(_cache_key(username, password))
    if not hit or hit[0] <= time.monotonic():
        return None
    user = _vault_user(username)
    if user is None or not may_use(user) or not hmac.compare_digest(user.vault_password or '', hit[1]):
        return None
    return user


def _check_credentials(username, password):
    """The user these credentials open the vault for, or None."""
    user = _vault_user(username)
    stored = (user.vault_password or '') if may_use(user) else ''
    if not stored:
        # The same hash check either way: a wrong username doesn't answer faster.
        if not _dummy_hash:
            _dummy_hash.append(generate_password_hash('not the vault password'))
        check_password_hash(_dummy_hash[0], password or '')
        return None
    if not check_password_hash(stored, password or ''):
        return None
    with _auth_lock:
        _auth_cache[_cache_key(username, password)] = (time.monotonic() + AUTH_CACHE_SECONDS, stored)
    return user


def _unauthorized():
    return Response('unauthorized', 401, {'WWW-Authenticate': 'Basic realm="Save vault", charset="UTF-8"'})


# --- paths -----------------------------------------------------------------------------

def _relative(url_path, encoded=False):
    """The path inside the vault ('/', '/JKSV', '/JKSV/game/x.zip'), or None when it climbs
    out, names a Windows stream or holds control characters. Flask has already decoded
    request.path; a Destination header (`encoded`) still has its %xx."""
    rel = unquote(url_path) if encoded else url_path
    if _CONTROL.search(rel):
        return None
    if rel.startswith(PREFIX):
        rel = rel[len(PREFIX):]
    if '\\' in rel or '\0' in rel or any(part == '..' for part in rel.split('/')):
        return None
    # One leading slash: normpath keeps a double one ('//' is special in POSIX).
    rel = posixpath.normpath('/' + rel.lstrip('/'))
    if ':' in rel:
        return None
    return rel


def _inside_base(rel):
    return rel is not None and rel.startswith(f'/{BASE}/') and rel != f'/{BASE}/'


def _is_zip(rel):
    return rel.lower().endswith('.zip')


def _disk(rel, root):
    return os.path.join(root, *[p for p in rel.split('/') if p])


# --- WebDAV ----------------------------------------------------------------------------

def handle(subpath=''):
    """Flask view for /dav and /dav/<path>."""
    if not enabled():
        return Response('not found', 404)
    creds = request.authorization
    username = (creds.username if creds else '') or ''
    lock_key = 'vault:' + username
    user = _cached_login(username, creds.password) if creds is not None else None
    if user is None:
        if auth.login_locked_for(lock_key):
            return Response('too many failed logins, try again later', 429, {'Retry-After': '900'})
        user = _check_credentials(username, creds.password) if creds is not None else None
        if user is None:
            if creds is not None:
                auth.record_login_failure(lock_key)
                logger.warning(f'Failed save vault login for {username!r} from {request.remote_addr}')
            return _unauthorized()
        auth.clear_login_failures(lock_key)
    adopt_shared_backups()
    root = user_root(user.id)

    method = request.method.upper()
    if method not in METHODS:
        return Response('not used by the save vault', 405, {'Allow': ', '.join(METHODS)})
    rel = _relative(request.path)
    if rel is None:
        return Response('bad path', 400)
    os.makedirs(_disk('/' + BASE, root), exist_ok=True)

    if method == 'OPTIONS':
        return Response('', 200, {'DAV': '1', 'Allow': ', '.join(METHODS), 'MS-Author-Via': 'DAV'})
    if method in ('GET', 'HEAD'):
        return _get(rel, root)
    if method == 'PROPFIND':
        return _propfind(rel, root)
    # Everything else changes the vault: only inside the JKSV folder.
    if not _inside_base(rel):
        return Response('only the JKSV folder can be changed', 403)
    if method == 'MKCOL':
        return _mkcol(rel, root)
    if not _is_zip(rel):
        return Response('only backups (ZIP files) are kept', 403)
    if method == 'PUT':
        return _put(rel, root, user.user)
    if method == 'DELETE':
        return _delete(rel, root)
    return _move(rel, root, user.user)


def _get(rel, root):
    path = _disk(rel, root)
    if not os.path.isfile(path):
        return Response('not found', 404 if not os.path.isdir(path) else 405)
    return send_file(path, mimetype='application/zip', conditional=True)


def _http_date(timestamp):
    return email.utils.formatdate(timestamp, usegmt=True)


def _entry_xml(rel, path):
    is_dir = os.path.isdir(path)
    href = quote(PREFIX + rel.rstrip('/') + ('/' if is_dir else ''), safe='/')
    stat = os.stat(path)
    name = escape(posixpath.basename(rel.rstrip('/')) or '/')
    props = [f'<D:displayname>{name}</D:displayname>',
             f'<D:getlastmodified>{_http_date(stat.st_mtime)}</D:getlastmodified>']
    if is_dir:
        props.append('<D:resourcetype><D:collection/></D:resourcetype>')
    else:
        props += ['<D:resourcetype/>', f'<D:getcontentlength>{stat.st_size}</D:getcontentlength>',
                  '<D:getcontenttype>application/zip</D:getcontenttype>']
    return (f'<D:response><D:href>{escape(href)}</D:href><D:propstat><D:prop>{"".join(props)}'
            f'</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>')


def _propfind(rel, root):
    depth = (request.headers.get('Depth') or '1').strip().lower()
    if depth not in ('0', '1'):
        return Response('only listings of one level are answered', 403)
    path = _disk(rel, root)
    if not os.path.exists(path):
        return Response('not found', 404)
    entries = [_entry_xml(rel, path)]
    if depth == '1' and os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            if name.startswith('.upload-'):
                continue
            try:
                entries.append(_entry_xml(posixpath.join(rel, name), os.path.join(path, name)))
            except OSError:
                continue   # gone (or unreadable) since the listing
    body = '<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:">' + ''.join(entries) + '</D:multistatus>'
    return Response(body, 207, content_type='application/xml; charset="utf-8"')


def _mkcol(rel, root):
    if _is_zip(rel):
        return Response('a folder named like a backup', 403)
    path = _disk(rel, root)
    if os.path.exists(path):
        return Response('exists', 405)
    if not os.path.isdir(os.path.dirname(path)):
        return Response('no parent folder', 409)
    os.mkdir(path)
    return Response('', 201)


def _central_directory(path):
    """The entries of a ZIP's central directory - (name, method, compressed size, size,
    local header offset) - read without zipfile: zipfile trusts nothing from the end
    record and reads the whole central directory, however large, into memory. Here the
    directory is read only up to MAX_ZIP_ENTRIES entries' worth of bytes and its entries
    are counted as they are, not as the end record says. None when the file isn't a plain
    ZIP of a save (ZIP64 included: no save needs it)."""
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as f:
            read = min(size, 22 + 65535)
            f.seek(size - read)
            tail = f.read(read)
            # The real end record is the one whose comment reaches the end of the file -
            # a comment can't fake one.
            at = tail.rfind(b'PK\x05\x06')
            while at >= 0 and at + 22 + struct.unpack('<H', tail[at + 20:at + 22])[0] != len(tail):
                at = tail.rfind(b'PK\x05\x06', 0, at)
            if at < 0 or at + 22 > len(tail):
                return None
            entries, cd_size, cd_offset = struct.unpack('<HII', tail[at + 10:at + 20])
            if 0xFFFF in (entries,) or 0xFFFFFFFF in (cd_size, cd_offset):
                return None
            if cd_size > MAX_ZIP_ENTRIES * (46 + MAX_NAME_BYTES) or cd_offset + cd_size > size:
                return None
            f.seek(cd_offset)
            cd = f.read(cd_size)
    except (OSError, struct.error):
        return None
    out, pos = [], 0
    while pos + 46 <= len(cd):
        if cd[pos:pos + 4] != b'PK\x01\x02':
            return None
        method, = struct.unpack('<H', cd[pos + 10:pos + 12])
        comp_size, file_size, n, e, c = struct.unpack('<IIHHH', cd[pos + 20:pos + 34])
        offset, = struct.unpack('<I', cd[pos + 42:pos + 46])
        name = cd[pos + 46:pos + 46 + n].decode('utf-8', 'replace')
        out.append((name, method, comp_size, file_size, offset))
        if len(out) > MAX_ZIP_ENTRIES:
            return None
        pos += 46 + n + e + c
    return out


def zip_entry_count(path):
    """Entries a ZIP really has (see _central_directory); None when it isn't one."""
    entries = _central_directory(path)
    return None if entries is None else len(entries)


def _put(rel, root, username):
    path = _disk(rel, root)
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        return Response('no game folder', 409)
    if game_limit_reached(root, os.path.basename(folder)):
        return Response('the limit of games with saves is reached: delete the saves of a game first', 507)
    free = _free_bytes(SAVES_DIR)
    declared = request.content_length
    if free is not None and free < MIN_FREE + (declared or 0):
        return Response('not enough free space on the server', 507)
    if declared is not None and declared > MAX_UPLOAD:
        return Response('too large for a save backup', 413)
    if os.path.isdir(path):
        return Response('a folder has that name', 409)
    room = None if free is None else free - MIN_FREE
    limit = MAX_UPLOAD if room is None else min(MAX_UPLOAD, room)
    tmp = os.path.join(folder, f'.upload-{uuid.uuid4().hex}.part')
    written = 0
    stored = False
    try:
        with open(tmp, 'wb') as out:
            while True:
                chunk = request.stream.read(CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    too_big = room is None or MAX_UPLOAD <= room
                    return (Response('too large for a save backup', 413) if too_big
                            else Response('not enough free space on the server', 507))
                out.write(chunk)
        # A body cut short (the console lost its Wi-Fi) never replaces a backup.
        if declared is not None and written != declared:
            return Response('the upload was cut short', 400)
        if _central_directory(tmp) is None:
            return Response('not a save backup', 422)
        existed = os.path.exists(path)
        os.replace(tmp, path)
        stored = True
    except Exception as e:
        logger.warning(f'Save vault upload of {rel} failed: {e}')
        return Response('the upload could not be stored', 400)
    finally:
        if not stored:
            _remove_quietly(tmp)
    _after_upload(path, username)
    return Response('', 204 if existed else 201)


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _delete(rel, root):
    path = _disk(rel, root)
    if not os.path.isfile(path):
        return Response('not found', 404)
    os.remove(path)
    return Response('', 204)


def _move(rel, root, username):
    source = _disk(rel, root)
    target_rel = _relative(urlsplit(request.headers.get('Destination') or '').path, encoded=True)
    if not target_rel or not _inside_base(target_rel) or not _is_zip(target_rel):
        return Response('backups stay in the JKSV folder', 403)
    if not os.path.isfile(source):
        return Response('not found', 404)
    target = _disk(target_rel, root)
    if not os.path.isdir(os.path.dirname(target)) or os.path.isdir(target):
        return Response('no game folder, or a folder has that name', 409)
    target_game = os.path.basename(os.path.dirname(target))
    if target_game != os.path.basename(os.path.dirname(source)) and game_limit_reached(root, target_game):
        return Response('the limit of games with saves is reached: delete the saves of a game first', 507)
    existed = os.path.exists(target)
    if existed and (request.headers.get('Overwrite') or 'T').upper() == 'F':
        return Response('exists', 412)
    os.replace(source, target)
    _after_upload(target, username)
    return Response('', 204 if existed else 201)


def _after_upload(path, username):
    """Keeps the number of backups asked for in the game's folder, and tells about it."""
    keep = int(config().get('keep') or 0)
    if keep:
        prune(os.path.dirname(path), keep)
    try:
        import notifications
        game = os.path.basename(os.path.dirname(path))
        notifications.notify(notifications.EVENT_SAVE_BACKUP, f'{username}: {game} - {os.path.basename(path)}')
    except Exception:
        logger.exception('Could not notify a new save backup')


def prune(folder, keep):
    """Deletes the oldest backups of a folder beyond `keep`. Returns how many went."""
    backups = []
    for n in os.listdir(folder):
        p = os.path.join(folder, n)
        try:
            if n.lower().endswith('.zip') and os.path.isfile(p):
                backups.append((os.path.getmtime(p), p))
        except OSError:
            continue
    backups = [p for _, p in sorted(backups, reverse=True)]
    for old in backups[keep:]:
        _remove_quietly(old)
    return max(0, len(backups) - keep)


# --- reading the backups ---------------------------------------------------------------

def read_meta(path):
    """(title id, time) from the meta file JKSV puts in its ZIP; (None, None) when the
    file isn't a JKSV backup. Read without zipfile (see _central_directory)."""
    try:
        entries = _central_directory(path)
        meta = next((e for e in entries or [] if e[0] == META_NAME), None)
        if meta is None:
            return None, None
        _, method, comp_size, file_size, offset = meta
        if not 57 <= file_size <= 4096 or comp_size > 8192 or method not in (0, 8):
            return None, None
        with open(path, 'rb') as f:
            f.seek(offset)
            header = f.read(30)
            if header[:4] != b'PK\x03\x04':
                return None, None
            n, e = struct.unpack('<HH', header[26:30])
            f.seek(offset + 30 + n + e)
            raw = f.read(comp_size)
        data = raw if method == 0 else zlib.decompressobj(-15).decompress(raw, 4096)
    except Exception:
        return None, None
    if len(data) < 57 or struct.unpack('<I', data[:4])[0] != META_MAGIC:
        return None, None
    title_id = f'{struct.unpack("<Q", data[5:13])[0]:016X}'
    stamp = struct.unpack('<Q', data[49:57])[0]
    when = datetime.datetime.fromtimestamp(stamp) if 1500000000 < stamp < 4102444800 else None
    return title_id, when


def _meta_cached(path, stat):
    key = (path, stat.st_size, stat.st_mtime)
    with _meta_lock:
        if key in _meta_cache:
            return _meta_cache[key]
    meta = read_meta(path)
    with _meta_lock:
        _meta_cache[key] = meta
    return meta


def _spaces():
    """The ids of every user with a space in the vault."""
    users = os.path.join(SAVES_DIR, 'users')
    return sorted(int(n) for n in os.listdir(users) if n.isdigit()) if os.path.isdir(users) else []


def backups(user_ids=None):
    """The backups of these users (None: everyone's): user id, path (inside their JKSV
    folder, with /), folder, file name, size, time, and the title id read from it."""
    adopt_shared_backups()
    out = []
    seen = set()
    for user_id in (_spaces() if user_ids is None else user_ids):
        _user_backups(user_id, out, seen)
    # The cache keeps only the backups there are: deleted and pruned ones go - with
    # everyone's listed only (one user's listing says nothing of the others').
    if user_ids is None:
        with _meta_lock:
            for key in [k for k in _meta_cache if k not in seen]:
                del _meta_cache[key]
    else:
        with _meta_lock:
            roots = tuple(user_root(u) + os.sep for u in user_ids)
            for key in [k for k in _meta_cache if k not in seen and k[0].startswith(roots)]:
                del _meta_cache[key]
    out.sort(key=lambda b: b['time'], reverse=True)
    return out


def _user_backups(user_id, out, seen):
    root = _disk('/' + BASE, user_root(user_id))
    if not os.path.isdir(root):
        return
    for folder in sorted(os.listdir(root)):
        folder_path = os.path.join(root, folder)
        if not os.path.isdir(folder_path):
            continue
        for name in os.listdir(folder_path):
            path = os.path.join(folder_path, name)
            if not name.lower().endswith('.zip') or not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            seen.add((path, stat.st_size, stat.st_mtime))
            title_id, when = _meta_cached(path, stat)
            out.append({'user_id': user_id, 'path': f'{folder}/{name}', 'folder': folder, 'name': name,
                        'size': stat.st_size, 'title_id': title_id,
                        'time': (when or datetime.datetime.fromtimestamp(stat.st_mtime)).isoformat(timespec='seconds')})


def backup_path(user_id, relative):
    """The file of one of this user's backups named as backups() names it ('game/x.zip'),
    or None when it isn't one inside their JKSV folder."""
    rel = _relative('/' + BASE + '/' + (relative or ''))
    if not _inside_base(rel) or not _is_zip(rel):
        return None
    path = _disk(rel, user_root(user_id))
    return path if os.path.isfile(path) else None


def delete_backup(user_id, relative):
    path = backup_path(user_id, relative)
    if path is None:
        return False
    os.remove(path)
    folder = os.path.dirname(path)
    # An emptied game folder goes too, as on the console.
    if not os.listdir(folder):
        os.rmdir(folder)
    return True

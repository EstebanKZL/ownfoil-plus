"""Files > Compression and Files > Combine: what each can act on, game by game.

Compression lists every identified NSP/NSZ/XCI/XCZ under its game with what it holds
(base, update, DLC, or several) and whether it's compressed - to compress or decompress.
Combine lists each game that has its base as a loose NSP/NSZ plus its latest update
and/or DLC as loose NSP/NSZ files (to combine), and every combined file (to split). Both
only read; the work runs as tasks (tasks.py), with the options Settings holds.
"""
from sqlalchemy.orm import selectinload

from constants import APP_TYPE_BASE, APP_TYPE_DLC, APP_TYPE_UPD, COMPRESS_EXT, DECOMPRESS_EXT
from db import Apps, Files, Titles, db
import titles as titles_lib

COMBINE_EXT = ('nsp', 'nsz')
PACK_EXT = tuple(COMPRESS_EXT) + tuple(DECOMPRESS_EXT)
KIND = {APP_TYPE_BASE: 'BASE', APP_TYPE_UPD: 'UPDATE', APP_TYPE_DLC: 'DLC'}
KIND_ORDER = {'BASE': 0, 'MULTI': 0, 'UPDATE': 1, 'DLC': 2}


def _game(title_id, cache):
    if title_id not in cache:
        info = titles_lib.get_game_info(title_id) or {}
        name = info.get('name')
        cache[title_id] = {'title_id': title_id,
                           'name': name if name and name != 'Unrecognized' else title_id,
                           'icon_url': info.get('iconUrl') or None}
    return dict(cache[title_id])


def _file(f, app):
    return {'id': f.id, 'filename': f.filename, 'extension': (f.extension or '').lower(),
            'size': f.size or 0, 'compressed': bool(f.compressed),
            'kind': 'MULTI' if f.multicontent else KIND.get(app.app_type, 'BASE'),
            'version': app.app_version, 'app_id': app.app_id}


def _titles():
    """Every title with an owned app, its apps and their files loaded in a few queries
    (not one per title and app: a big library has thousands)."""
    return (Titles.query.join(Titles.apps).filter(Apps.owned.is_(True)).distinct()
            .options(selectinload(Titles.apps).selectinload(Apps.files)).all())


def compression_candidates():
    """Games with files that can be compressed or decompressed:
    [{title_id, name, icon_url, files: [... compressed ...], size}]."""
    games, cache = {}, {}
    seen = set()
    for title in _titles():
        for app in title.apps:
            for f in app.files:
                if f.id in seen or not f.identified or (f.extension or '').lower() not in PACK_EXT:
                    continue
                seen.add(f.id)
                game = games.setdefault(title.title_id, {**_game(title.title_id, cache), 'files': []})
                game['files'].append(_file(f, app))
    for game in games.values():
        game['files'].sort(key=lambda x: (KIND_ORDER[x['kind']], x['filename'].lower()))
        game['size'] = sum(x['size'] for x in game['files'])
    return sorted(games.values(), key=lambda g: g['name'].lower())


def _loose(app):
    """The app's single-content NSP/NSZ file, if it has one."""
    for f in app.files:
        if f.identified and not f.multicontent and (f.extension or '').lower() in COMBINE_EXT:
            return f
    return None


def combine_parts(title):
    """What a combined file of this title holds: (base, latest update or None, [DLC]) as
    (file, app) pairs - or None when there's nothing to combine."""
    base = update = None
    dlcs = {}
    for app in title.apps:
        if not app.owned:
            continue
        f = _loose(app)
        if f is None:
            continue
        version = int(app.app_version or 0)
        if app.app_type == APP_TYPE_BASE and base is None:
            base = (f, app)
        elif app.app_type == APP_TYPE_UPD and (update is None or version > int(update[1].app_version or 0)):
            update = (f, app)
        elif app.app_type == APP_TYPE_DLC:
            known = dlcs.get(app.app_id)
            if known is None or version > int(known[1].app_version or 0):
                dlcs[app.app_id] = (f, app)
    if base is None or (update is None and not dlcs):
        return None
    return base, update, [dlcs[k] for k in sorted(dlcs)]


def _parts_of(files):
    return {'base': sum(1 for x in files if x['kind'] == 'BASE'),
            'update': sum(1 for x in files if x['kind'] == 'UPDATE'),
            'dlc': sum(1 for x in files if x['kind'] == 'DLC')}


def combine_candidates():
    """Games to combine (loose parts) and combined files to split:
    [{title_id, name, icon_url, state: 'loose'|'combined', files, parts, size, extension,
      file_id (combined only)}]."""
    out, cache = [], {}
    for title in _titles():
        parts = combine_parts(title)
        if parts is not None:
            base, update, dlcs = parts
            chosen = [base] + ([update] if update else []) + dlcs
            files = [_file(f, app) for f, app in chosen]
            out.append({**_game(title.title_id, cache), 'state': 'loose', 'files': files,
                        'parts': _parts_of(files), 'size': sum(x['size'] for x in files),
                        'extension': 'nsz' if any(x['extension'] == 'nsz' for x in files) else 'nsp'})
        # Every combined (multi-content) NSP/NSZ of this title, each one to split.
        seen = set()
        for app in title.apps:
            for f in app.files:
                if (f.id in seen or not f.multicontent or not f.identified
                        or (f.extension or '').lower() not in COMBINE_EXT):
                    continue
                seen.add(f.id)
                inside = [{'kind': KIND.get(a.app_type, 'BASE'), 'app_id': a.app_id, 'version': a.app_version}
                          for a in f.apps]
                out.append({**_game(title.title_id, cache), 'state': 'combined', 'file_id': f.id,
                            'files': [{'id': f.id, 'filename': f.filename, 'extension': f.extension.lower(),
                                       'size': f.size or 0, 'compressed': bool(f.compressed), 'kind': 'MULTI'}],
                            'parts': _parts_of(inside), 'size': f.size or 0, 'extension': f.extension.lower()})
    return sorted(out, key=lambda g: (g['name'].lower(), g['state']))


def compression_level_name(level):
    """How Settings' zstd level reads on the Files page."""
    level = int(level or 18)
    return 'fast' if level <= 10 else 'max' if level >= 20 else 'balanced'

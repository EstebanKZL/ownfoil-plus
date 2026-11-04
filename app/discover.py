"""Upcoming releases and sagas, from the TitleDB catalogue (titles.db) and the series of
series.py. Only base games count (title ids ending in 000), never demos.

The catalogue of one region also lists games sold only in Japan or Korea, under their
Japanese or Korean names: they are left out unless the interface itself is in one of
those languages.
"""
import os
import re
import threading

import series
import titledb

_CJK = re.compile(r'[぀-ヿ㐀-鿿가-힯]')
_CJK_LANGUAGES = ('ja', 'ko', 'zh')
_DEMO_VALUES = ('1', 'true', 'True')

_cache = {'key': None, 'titles': None, 'members': None}
_lock = threading.Lock()


def clear_cache():
    with _lock:
        _cache.update(key=None, titles=None, members=None)


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def _iso(date_text):
    text = str(date_text or '')
    return f'{text[:4]}-{text[4:6]}-{text[6:8]}' if len(text) == 8 and text.isdigit() else None


def _load():
    """Every base game of the catalogue, and the members of each series - rebuilt only
    when titles.db or series.json change."""
    key = (_mtime(titledb.store.TITLES_DB_FILE), _mtime(series.SERIES_FILE))
    with _lock:
        if _cache['key'] == key:
            return _cache['titles'], _cache['members']
    titles = {}
    conn = titledb.store._connect_ro()
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT id, name, release_date, publisher, icon_url, banner_url, is_demo "
                "FROM titles WHERE id LIKE '%000' AND name IS NOT NULL").fetchall()
        finally:
            conn.close()
        for r in rows:
            if str(r['is_demo']) in _DEMO_VALUES:
                continue
            title_id = r['id'].upper()
            titles[title_id] = {
                'title_id': title_id, 'name': r['name'], 'date': str(r['release_date'] or ''),
                'release_date': _iso(r['release_date']), 'publisher': r['publisher'],
                'icon_url': r['icon_url'], 'banner_url': r['banner_url'],
                'series': series.series_of(title_id, r['name']),
            }
    members = {}
    for t in titles.values():
        for qid in t['series']:
            members.setdefault(qid, []).append(t['title_id'])
    with _lock:
        _cache.update(key=key, titles=titles, members=members)
    return titles, members


def _visible(title, lang):
    return lang in _CJK_LANGUAGES or not _CJK.search(title['name'])


def _today(today):
    return today.strftime('%Y%m%d')


def upcoming(today, lang, owned_ids, wishlist_ids):
    """Base games with a release date after `today`, by date and grouped by month, plus
    "for you": the ones on the wishlist and the sequels of sagas the user has a game of."""
    titles, _members = _load()
    cut = _today(today)
    owned_series = {q for tid in owned_ids if tid in titles for q in titles[tid]['series']}
    games = []
    for t in sorted(titles.values(), key=lambda t: (t['date'], t['name'].lower())):
        if not t['date'] or t['date'] <= cut or not _visible(t, lang):
            continue
        games.append({
            'title_id': t['title_id'], 'name': t['name'], 'release_date': t['release_date'],
            'publisher': t['publisher'], 'icon_url': t['icon_url'], 'banner_url': t['banner_url'],
            'series': [{'id': q, 'name': series.series_name(q, lang)} for q in t['series']],
            'wishlisted': t['title_id'] in wishlist_ids,
            'sequel': bool(owned_series.intersection(t['series'])),
        })
    months = []
    for g in games:
        month = g['release_date'][:7]
        if not months or months[-1]['month'] != month:
            months.append({'month': month, 'games': []})
        months[-1]['games'].append(g)
    return {'for_you': [g for g in games if g['wishlisted'] or g['sequel']], 'months': months}


def _counts(qid, members, titles, cut, owned_ids):
    released = [tid for tid in members if titles[tid]['date'] and titles[tid]['date'] <= cut]
    upcoming_count = len(members) - len(released)
    owned = sum(1 for tid in members if tid in owned_ids)
    return owned, len(released), upcoming_count


def sagas(today, lang, owned_ids):
    """The sagas the user has at least one game of: "4 of 6", most complete first."""
    titles, members = _load()
    cut = _today(today)
    out = []
    for qid, ids in members.items():
        owned, total, upcoming_count = _counts(qid, ids, titles, cut, owned_ids)
        name = series.series_name(qid, lang)
        if not owned or not name:
            continue
        mine = sorted((titles[t] for t in ids if t in owned_ids), key=lambda t: t['date'])
        out.append({'id': qid, 'name': name, 'owned': owned, 'total': max(total, owned),
                    'upcoming': upcoming_count, 'icons': [t['icon_url'] for t in mine if t['icon_url']][:4]})
    out.sort(key=lambda s: (-s['owned'] / s['total'], -s['owned'], s['name'].lower()))
    return out


def saga(qid, today, lang, owned_ids):
    """One saga with all its games by release date: owned, missing or still to come."""
    titles, members = _load()
    ids = members.get(qid)
    name = series.series_name(qid, lang)
    if not ids or not name:
        return None
    cut = _today(today)
    games = []
    for t in sorted((titles[tid] for tid in ids), key=lambda t: (t['date'] or '99999999', t['name'].lower())):
        if not _visible(t, lang) and t['title_id'] not in owned_ids:
            continue
        games.append({'title_id': t['title_id'], 'name': t['name'], 'release_date': t['release_date'],
                      'icon_url': t['icon_url'], 'owned': t['title_id'] in owned_ids,
                      'upcoming': bool(t['date']) and t['date'] > cut})
    owned, total, upcoming_count = _counts(qid, ids, titles, cut, owned_ids)
    return {'id': qid, 'name': name, 'owned': owned, 'total': max(total, owned),
            'upcoming': upcoming_count, 'games': games}


def sagas_of(title_id, today, lang, owned_ids):
    """The sagas one game belongs to, with how many of each the user has."""
    titles, members = _load()
    t = titles.get((title_id or '').upper())
    if t is None:
        return []
    cut = _today(today)
    out = []
    for qid in t['series']:
        name = series.series_name(qid, lang)
        if not name:
            continue
        owned, total, _ = _counts(qid, members.get(qid, []), titles, cut, owned_ids)
        out.append({'id': qid, 'name': name, 'owned': owned, 'total': max(total, owned)})
    return out

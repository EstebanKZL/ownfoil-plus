"""Upcoming releases and sagas, from the TitleDB catalogue (titles.db) and the series of
series.py. Only base games count (title ids ending in 000), never demos.

The catalogue of one region also lists games sold only in Japan or Korea, under their
Japanese or Korean names: they are left out unless the interface itself is in one of
those languages.
"""
import datetime
import os
import re
import threading

import series
import titledb

_CJK = re.compile(r'[぀-ヿ㐀-鿿가-힯]')
_CJK_LANGUAGES = ('ja', 'ko', 'zh')
_DEMO_VALUES = ('1', 'true', 'True')
# Versions that aren't games of their own for a saga: streamed "Cloud" versions, and demos
# or trials the catalogue doesn't flag as such ("Online Tournament Demo", "Pre-launch").
_NOT_A_SAGA_GAME = re.compile(r"\b(cloud(\s+version)?|demo|trial|pre-?launch)\b", re.I)

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


# Words that don't tell a series apart ("The Legend of Zelda" is "legend zelda").
_SMALL_WORDS = frozenset({'the', 'of', 'a', 'an', 'and', 'de', 'del', 'la', 'el', 'los', 'las'})


def _words(name):
    return set(series.normalize(name).split()) - _SMALL_WORDS


def _own_series(name, qids):
    """The series a game is really part of. Wikidata files crossovers under every series
    they borrow from: Persona 5 Strikers under Persona, Persona 5 and Dynasty Warriors;
    Fire Emblem Warriors under Fire Emblem and Dynasty Warriors. When the game's name
    holds the whole name of some of its series, it stays in those only."""
    if len(qids) < 2:
        return qids
    names = series.load().get('series', {})
    words = _words(name)
    named = [q for q in qids
             if any(label and _words(label) and _words(label) <= words for label in (names.get(q) or {}).values())]
    return named or qids


def _series_by_prefix():
    """Series names of two words or more ("football manager", "resident evil"), by their
    first two words, longest first - to find games named after them."""
    index = {}
    for qid, labels in (series.load().get('series') or {}).items():
        for label in set((labels or {}).values()):
            words = series.normalize(label).split()
            if len([w for w in words if w not in _SMALL_WORDS]) >= 2:
                index.setdefault(tuple(words[:2]), []).append((' '.join(words), qid))
    for entries in index.values():
        entries.sort(key=lambda e: -len(e[0]))
    return index


def _named_after(name, index):
    """The series a game with no series of its own is named after: Wikidata links
    "Football Manager Touch 2018" to Football Manager but not "Football Manager 2019
    Touch", nor "Resident Evil 2 Cloud" to Resident Evil. Only series of two words or
    more, so "Mario" doesn't take every Mario game."""
    text = series.normalize(name)
    words = text.split()
    for full, qid in index.get(tuple(words[:2]), ()):
        if text == full or text.startswith(full + ' '):
            return [qid]
    return []


def _one_per_game(ids, titles, owned_ids, switch2=None):
    """A series' games, one per game: the catalogue lists some twice, from another region
    or edition under the same name ("The Elder Scrolls V: Skyrim" and "...Skyrim®"). The
    copy you have wins; else the first released. Switch 2 games you don't have count only
    with "I have a Switch 2" on."""
    if switch2 is None:
        switch2 = _has_switch2()
    chosen = {}
    for tid in sorted((t for t in ids if _console_ok(t, owned_ids, switch2)),
                      key=lambda t: (t not in owned_ids, titles[t]['date'] or '99999999', t)):
        chosen.setdefault(series.normalize(titles[tid]['name']), tid)
    return list(chosen.values())


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
        by_prefix = _series_by_prefix()
        for r in rows:
            if str(r['is_demo']) in _DEMO_VALUES:
                continue
            title_id = r['id'].upper()
            titles[title_id] = {
                'title_id': title_id, 'name': r['name'], 'date': str(r['release_date'] or ''),
                'release_date': _iso(r['release_date']), 'publisher': r['publisher'],
                'icon_url': r['icon_url'], 'banner_url': r['banner_url'],
                'series': [] if _NOT_A_SAGA_GAME.search(r['name']) else (
                    _own_series(r['name'], series.series_of(title_id, r['name']))
                    or _named_after(r['name'], by_prefix)),
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


def is_switch2(title_id):
    """Nintendo Switch 2 titles have ids starting with 04."""
    return (title_id or '').upper().startswith('04')


def _has_switch2():
    try:
        from settings import get_settings
        return bool(get_settings()['library']['management'].get('switch2'))
    except Exception:
        return False


def _console_ok(title_id, owned_ids, switch2):
    """A Switch 2 game shows when you have it, or with "I have a Switch 2" on."""
    return switch2 or title_id in owned_ids or not is_switch2(title_id)


def _today(today):
    return today.strftime('%Y%m%d')


RECENT_DAYS = 30    # "Just released": the games out in the last month
RECENT_MAX = 40


def upcoming(today, lang, owned_ids, wishlist_ids):
    """Base games with a release date after `today`, by date and grouped by month, plus
    "for you": the ones on the wishlist and the sequels of sagas the user has a game of,
    and "just released": the ones out in the last RECENT_DAYS, newest first. Nintendo
    Switch and Switch 2 games both, the latter marked."""
    titles, _members = _load()
    cut = _today(today)
    since = _today(today - datetime.timedelta(days=RECENT_DAYS))
    owned_series = {q for tid in owned_ids if tid in titles for q in titles[tid]['series']}

    def card(t):
        return {
            'title_id': t['title_id'], 'name': t['name'], 'release_date': t['release_date'],
            'publisher': t['publisher'], 'icon_url': t['icon_url'], 'banner_url': t['banner_url'],
            'series': [{'id': q, 'name': series.series_name(q, lang)} for q in t['series']],
            'wishlisted': t['title_id'] in wishlist_ids, 'switch2': is_switch2(t['title_id']),
            'owned': t['title_id'] in owned_ids,
            'sequel': bool(owned_series.intersection(t['series'])),
        }

    recent = [card(t) for t in sorted(titles.values(), key=lambda t: (t['date'], t['name'].lower()), reverse=True)
              if t['date'] and since < t['date'] <= cut and _visible(t, lang)][:RECENT_MAX]
    games = []
    for t in sorted(titles.values(), key=lambda t: (t['date'], t['name'].lower())):
        if not t['date'] or t['date'] <= cut or not _visible(t, lang):
            continue
        games.append(card(t))
    months = []
    for g in games:
        month = g['release_date'][:7]
        if not months or months[-1]['month'] != month:
            months.append({'month': month, 'games': []})
        months[-1]['games'].append(g)
    return {'for_you': [g for g in games if g['wishlisted'] or g['sequel']], 'months': months,
            'recent': recent}


def _counts(qid, members, titles, cut, owned_ids):
    released = [tid for tid in members if titles[tid]['date'] and titles[tid]['date'] <= cut]
    upcoming_count = len(members) - len(released)
    owned = sum(1 for tid in members if tid in owned_ids)
    return owned, len(released), upcoming_count


def _inside_another(members, titles, owned_ids):
    """The sub-series whose every game is already in a bigger saga (Pokémon Legends in the
    Pokémon main series, Minecraft: Story Mode in Minecraft): listed apart, their games
    would show twice. A series with the very same games as another counts once too."""
    sets = {q: frozenset(series.normalize(titles[t]['name']) for t in ids) for q, ids in members.items()}
    # Only the sagas that would be listed (one of your games in them) need the check.
    shown = [q for q, ids in members.items() if any(t in owned_ids for t in ids)]
    hidden = set()
    for q in shown:
        games = sets[q]
        for other, bigger in sets.items():
            if other == q or other in hidden or not games <= bigger:
                continue
            if len(games) < len(bigger) or q > other:   # equal sets: keep one of them
                hidden.add(q)
                break
    return hidden


def sagas(today, lang, owned_ids):
    """The sagas the user has at least one game of: "4 of 6", most complete first."""
    titles, members = _load()
    cut = _today(today)
    out = []
    hidden = _inside_another(members, titles, owned_ids)
    for qid, ids in members.items():
        if qid in hidden:
            continue
        ids = _one_per_game(ids, titles, owned_ids)
        owned, total, upcoming_count = _counts(qid, ids, titles, cut, owned_ids)
        name = series.series_name(qid, lang)
        if not owned or not name:
            continue
        mine = sorted((titles[t] for t in ids if t in owned_ids), key=lambda t: t['date'])
        # Every game out so far (and the ones you have), by release date, for the card's
        # strip of covers: the ones you have in colour, the missing ones greyed.
        out_now = sorted((titles[t] for t in ids
                          if t in owned_ids or (titles[t]['date'] and titles[t]['date'] <= cut
                                                and _visible(titles[t], lang))),
                         key=lambda t: (t['date'] or '99999999', t['name'].lower()))
        out.append({'id': qid, 'name': name, 'owned': owned, 'total': max(total, owned),
                    'upcoming': upcoming_count, 'icons': [t['icon_url'] for t in mine if t['icon_url']][:4],
                    'cover': next((t['icon_url'] for t in reversed(mine) if t['icon_url']), None),
                    'games': [{'title_id': t['title_id'], 'name': t['name'], 'icon_url': t['icon_url'],
                               'owned': t['title_id'] in owned_ids, 'switch2': is_switch2(t['title_id'])}
                              for t in out_now]})
    out.sort(key=lambda s: (-s['owned'] / s['total'], -s['owned'], s['name'].lower()))
    return out


def saga(qid, today, lang, owned_ids):
    """One saga with all its games by release date: owned, missing or still to come."""
    titles, members = _load()
    ids = members.get(qid)
    name = series.series_name(qid, lang)
    if not ids or not name:
        return None
    ids = _one_per_game(ids, titles, owned_ids)
    cut = _today(today)
    games = []
    for t in sorted((titles[tid] for tid in ids), key=lambda t: (t['date'] or '99999999', t['name'].lower())):
        if not _visible(t, lang) and t['title_id'] not in owned_ids:
            continue
        games.append({'title_id': t['title_id'], 'name': t['name'], 'release_date': t['release_date'],
                      'icon_url': t['icon_url'], 'owned': t['title_id'] in owned_ids,
                      'switch2': is_switch2(t['title_id']),
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
        owned, total, _ = _counts(qid, _one_per_game(members.get(qid, []), titles, owned_ids),
                                  titles, cut, owned_ids)
        out.append({'id': qid, 'name': name, 'owned': owned, 'total': max(total, owned)})
    return out

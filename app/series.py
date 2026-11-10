"""Sagas: the series each Switch game belongs to.

TitleDB has no series. Wikidata does (CC0, free to reuse): games link to their series
("part of the series", P179), and many to their Switch title ID (P11072). The server
asks Wikidata itself, after each TitleDB refresh at most once a week, and keeps the
answer in data/series.json:

    {"series": {"Q12395": {"en": "The Legend of Zelda", "es": "..."}},
     "ids":    {"01007EF00011E000": ["Q12395"]},        # base games' title IDs
     "names":  {"splatoon 3": ["Q20888356"]},             # normalized English/Spanish names
     "updated": "2026-11-04T10:00:00"}

A game is matched by title ID first, then by name. When Wikidata does not answer, the
last copy stays. Credits: see NOTICE.md.
"""
import datetime
import json
import logging
import os
import re
import threading
import unicodedata

import requests

from constants import DATA_DIR

logger = logging.getLogger('main')

SERIES_FILE = os.path.join(DATA_DIR, 'series.json')
WIKIDATA_URL = 'https://query.wikidata.org/sparql'
USER_AGENT = 'Ownfoil-Plus (https://github.com/EstebanKZL/ownfoil-plus)'
TIMEOUT = 90
MAX_AGE = datetime.timedelta(days=7)
# 'mul' is Wikidata's name for every language at once ("Mario Kart"): many series and
# games carry only that one.
LANGUAGES = ('en', 'es', 'mul')

# Games with a Switch title ID, and the name of their series.
QUERY_BY_ID = """
SELECT DISTINCT ?s ?tid ?sen ?ses ?smul WHERE {
  ?g wdt:P179 ?s .
  ?g wdt:P11072 ?tid .
  OPTIONAL { ?s rdfs:label ?sen . FILTER(LANG(?sen) = "en") }
  OPTIONAL { ?s rdfs:label ?ses . FILTER(LANG(?ses) = "es") }
  OPTIONAL { ?s rdfs:label ?smul . FILTER(LANG(?smul) = "mul") }
}
"""

# Switch games (platform Q19610114) of a series, by their English, Spanish and "mul" names: for
# the many games Wikidata has without their title ID.
QUERY_BY_NAME = """
SELECT DISTINCT ?s ?name ?sen ?ses ?smul WHERE {
  ?g wdt:P179 ?s .
  ?g wdt:P400 wd:Q19610114 .
  ?g rdfs:label ?name . FILTER(LANG(?name) IN ("en", "es", "mul"))
  OPTIONAL { ?s rdfs:label ?sen . FILTER(LANG(?sen) = "en") }
  OPTIONAL { ?s rdfs:label ?ses . FILTER(LANG(?ses) = "es") }
  OPTIONAL { ?s rdfs:label ?smul . FILTER(LANG(?smul) = "mul") }
}
"""

_MARKS = re.compile(r'[™®©]')
_NON_WORD = re.compile(r'[^a-z0-9]+')

_cache = {'mtime': None, 'data': None}
_lock = threading.Lock()


def normalize(name):
    """A name as compared: no accents, no ™/®/©, lowercase, words separated by one space."""
    text = unicodedata.normalize('NFKD', _MARKS.sub('', name or ''))
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    return _NON_WORD.sub(' ', text).strip()


def _qid(binding):
    return binding['s']['value'].rsplit('/', 1)[-1]


def _value(binding, key):
    return (binding.get(key) or {}).get('value')


def build(by_id, by_name):
    """series.json's content from the two Wikidata answers."""
    data = {'series': {}, 'ids': {}, 'names': {},
            'updated': datetime.datetime.utcnow().isoformat(timespec='seconds')}

    def add_series(binding):
        qid = _qid(binding)
        names = data['series'].setdefault(qid, {})
        for lang in LANGUAGES:
            label = _value(binding, 's' + lang)
            if label and lang not in names:
                names[lang] = label
        return qid

    for b in by_id['results']['bindings']:
        qid = add_series(b)
        tid = (_value(b, 'tid') or '').strip().upper()
        if re.fullmatch(r'[0-9A-F]{16}', tid):
            members = data['ids'].setdefault(tid, [])
            if qid not in members:
                members.append(qid)
    for b in by_name['results']['bindings']:
        qid = add_series(b)
        key = normalize(_value(b, 'name'))
        if key:
            members = data['names'].setdefault(key, [])
            if qid not in members:
                members.append(qid)
    # A series nobody named in either language can't be shown.
    data['series'] = {q: n for q, n in data['series'].items() if n}
    return data


def save(data):
    os.makedirs(os.path.dirname(SERIES_FILE), exist_ok=True)
    tmp = SERIES_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, SERIES_FILE)


def load():
    """series.json as read, re-read only when the file changes. Empty when there is none."""
    try:
        mtime = os.path.getmtime(SERIES_FILE)
    except OSError:
        return {'series': {}, 'ids': {}, 'names': {}}
    with _lock:
        if _cache['mtime'] != (SERIES_FILE, mtime):
            try:
                with open(SERIES_FILE, encoding='utf-8') as f:
                    _cache['data'] = json.load(f)
            except (OSError, ValueError):
                logger.warning('series.json could not be read; sagas are empty until the next refresh')
                _cache['data'] = {'series': {}, 'ids': {}, 'names': {}}
            _cache['mtime'] = (SERIES_FILE, mtime)
        return _cache['data']


def series_of(title_id, name):
    """The series (Wikidata ids) of a base game: by its title ID, else by its name."""
    data = load()
    found = data['ids'].get((title_id or '').upper())
    if found:
        return list(found)
    return list(data['names'].get(normalize(name), []))


def series_name(qid, lang):
    names = load()['series'].get(qid)
    if not names:
        return None
    return names.get(lang) or names.get('en') or names.get('mul') or next(iter(names.values()))


def _query(sparql):
    response = requests.get(WIKIDATA_URL, params={'query': sparql}, timeout=TIMEOUT,
                            headers={'Accept': 'application/sparql-results+json', 'User-Agent': USER_AGENT})
    response.raise_for_status()
    return response.json()


def refresh(force=False):
    """Ask Wikidata again when the copy is a week old (or `force`). True when refreshed,
    None when the copy was fresh enough, False when Wikidata failed (the copy stays)."""
    if not force:
        try:
            age = datetime.datetime.now() - datetime.datetime.fromtimestamp(os.path.getmtime(SERIES_FILE))
            if age < MAX_AGE:
                return None
        except OSError:
            pass
    try:
        data = build(_query(QUERY_BY_ID), _query(QUERY_BY_NAME))
    except Exception as e:
        logger.warning(f'Could not refresh the sagas from Wikidata ({e}); keeping the last copy')
        return False
    save(data)
    logger.info(f"Sagas refreshed from Wikidata: {len(data['series'])} series, "
                f"{len(data['ids'])} title IDs, {len(data['names'])} names")
    return True

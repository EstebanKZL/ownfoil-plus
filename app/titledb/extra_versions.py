"""Update versions from more sources than the TitleDB release.

The release's versions.json comes from blawar/titledb, which goes weeks without changes:
meanwhile new updates go unseen. Two more sources add the versions they know -
borntohonk/titledb's versions.json, and 16BitWonder's nx-versions (the last version of
every update) with its changelog for the day each was first listed. The release's own
versions stay first: these only add what it lacks, and a version both know keeps the
release's date.

Each source is downloaded only when it changed (its ETag), kept under titledb/extra/, and
read with checks - a version of an update is a multiple of 0x10000, a DLC is left to the
catalogue - since they are not the release. A source that can't be downloaded, or that
comes back as something else, keeps its last good copy.

The sources and checks follow Switch Library Manager Web by DeLFuS77 (AGPL-3.0, see
NOTICE.md), .github/scripts/merge_versions.py.
"""
import json
import logging
import os
import re

import requests

logger = logging.getLogger('main')

SOURCES = {
    'borntohonk.versions.json': 'https://raw.githubusercontent.com/borntohonk/titledb/master/versions.json',
    'nx-versions.txt': 'https://raw.githubusercontent.com/16BitWonder/nx-versions/master/versions.txt',
    'nx-changelog.md': 'https://raw.githubusercontent.com/16BitWonder/nx-versions/master/FULL-CHANGELOG.md',
}
TIMEOUT = (10, 60)

TITLE_ID = re.compile(r'[0-9a-fA-F]{16}')
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
CHANGELOG_SECTION = re.compile(r'## (\d{4}-\d{2}-\d{2})\b')
CHANGELOG_VERSION = re.compile(r'\[([0-9A-Fa-f]{16})\](?:\[v\d+\]->)?\[v(\d+)\]')


def valid_version(title_id, version):
    """A game's update versions are multiples of 0x10000; a number far from that isn't one."""
    if not 0 < version < 1 << 32:
        return False
    return not title_id.endswith('000') or version % 0x10000 == 0


def read_versions(path):
    """A versions.json like the release's: {game id: {version: date}} -> {GAME ID: {int: date|None}}."""
    with open(path, encoding='utf-8') as f:
        source = json.load(f)
    if not isinstance(source, dict) or not source:
        raise ValueError('not a JSON object with versions')
    titles = {}
    for title_id, versions in source.items():
        if not TITLE_ID.fullmatch(title_id) or not isinstance(versions, dict):
            continue
        title_id = title_id.upper()
        for version, date in versions.items():
            if not str(version).isdigit() or not valid_version(title_id, int(version)):
                continue
            titles.setdefault(title_id, {})[int(version)] = date if isinstance(date, str) and DATE.fullmatch(date) else None
    return titles


def read_changelog(path):
    """The day nx-versions first listed each version of an update: (UPDATE ID, version) -> date."""
    dates = {}
    day = None
    with open(path, encoding='utf-8') as f:
        for line in f:
            section = CHANGELOG_SECTION.match(line)
            if section:
                day = section.group(1)
                continue
            found = CHANGELOG_VERSION.fullmatch(line.strip())
            if found and day:
                key = (found.group(1).upper(), int(found.group(2)))
                # the newest section comes first: the oldest day is the one kept
                dates[key] = min(day, dates.get(key, day))
    return dates


def read_nx_versions(path, changelog=None):
    """nx-versions' versions.txt ("id|version", the last version of every update) under the
    id of each update's game, dated from the changelog when there is one."""
    dates = {}
    if changelog and os.path.isfile(changelog):
        try:
            dates = read_changelog(changelog)
        except (OSError, ValueError) as e:
            logger.warning(f'nx-versions changelog left out, its versions have no date: {e}')
    titles = {}
    with open(path, encoding='utf-8') as f:
        if f.readline().strip() != 'id|version':
            raise ValueError('not a versions.txt of nx-versions')
        for line in f:
            parts = line.strip().split('|')
            if len(parts) != 2 or not TITLE_ID.fullmatch(parts[0]) or not parts[1].isdigit():
                continue
            update_id, version = parts[0].upper(), int(parts[1])
            # only updates: a DLC (bit 12 set, even one ending in 800) comes from the catalogue
            if not update_id.endswith('800') or int(update_id, 16) & 0x1000:
                continue
            title_id = update_id[:-3] + '000'
            if valid_version(title_id, version):
                titles.setdefault(title_id, {})[version] = dates.get((update_id, version))
    return titles


def merged(folder):
    """Every version the extra sources in `folder` know: {GAME ID: {version: date|None}}.
    A source that is missing or unreadable is left out."""
    result = {}
    readers = [
        ('borntohonk.versions.json', lambda p: read_versions(p)),
        ('nx-versions.txt', lambda p: read_nx_versions(p, os.path.join(folder, 'nx-changelog.md'))),
    ]
    for name, read in readers:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        try:
            titles = read(path)
        except (OSError, ValueError) as e:
            logger.warning(f'Extra versions source {name} left out: {e}')
            continue
        for title_id, versions in titles.items():
            known = result.setdefault(title_id, {})
            for version, date in versions.items():
                known.setdefault(version, date)
    return result


def _looks_right(name, data):
    """A download is the file it should be, not an error page or a cut-off body."""
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return False
    if name.endswith('.json'):
        try:
            return isinstance(json.loads(text), dict)
        except ValueError:
            return False
    if name == 'nx-versions.txt':
        return text.startswith('id|version')
    return text.startswith('#') or '## ' in text[:4096]


def refresh(folder):
    """Download the sources that changed into `folder`. True when any did."""
    os.makedirs(folder, exist_ok=True)
    changed = False
    for name, url in SOURCES.items():
        path = os.path.join(folder, name)
        etag_path = path + '.etag'
        headers = {}
        if os.path.isfile(path) and os.path.isfile(etag_path):
            with open(etag_path, encoding='utf-8') as f:
                headers['If-None-Match'] = f.read().strip()
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
            if response.status_code == 304:
                continue
            response.raise_for_status()
            data = response.content
        except Exception as e:
            logger.warning(f'Extra versions source {name} not downloaded, keeping the last copy: {e}')
            continue
        if not _looks_right(name, data):
            logger.warning(f'Extra versions source {name} came back as something else, keeping the last copy')
            continue
        with open(path + '.tmp', 'wb') as f:
            f.write(data)
        os.replace(path + '.tmp', path)
        etag = response.headers.get('ETag')
        if etag:
            with open(etag_path, 'w', encoding='utf-8') as f:
                f.write(etag)
        changed = True
        logger.info(f'Extra versions source {name} updated')
    return changed

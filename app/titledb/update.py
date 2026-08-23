"""Drive a titledb refresh: download the upstream JSON files, rebuild titles.db from them."""
import logging
import os
import re

import requests
import zstandard

from constants import TITLEDB_DEFAULT_FILES, TITLEDB_DIR, TITLEDB_RELEASE_URL
from titledb import store

# Retrieve main logger
logger = logging.getLogger('main')

MARKER_FILE = '.latest'
REMOTE_MARKER = 'latest'
REGION_FILE_RE = re.compile(r"titles\.[A-Z]{2}\.[a-z]{2}\.json$")
TIMEOUT = (10, 60)


def get_region_titles_file(app_settings):
    return f"titles.{app_settings['titles']['region']}.{app_settings['titles']['language']}.json"


def get_locale(app_settings):
    return f"{app_settings['titles']['region']}.{app_settings['titles']['language']}"


def get_organizer_region_titles_file(app_settings):
    """The organizer's alternate-locale JSON filename, or None if no naming language is
    configured independently of the display locale."""
    locale = get_organizer_locale(app_settings)
    return f"titles.{locale}.json" if locale else None


def get_organizer_locale(app_settings):
    """The organizer's alternate locale (e.g. 'US.en'), or None when unconfigured -
    both `name_region` and `name_language` must be set for it to take effect."""
    organizer = app_settings.get('library', {}).get('management', {}).get('organizer', {})
    region = organizer.get('name_region')
    language = organizer.get('name_language')
    return f"{region}.{language}" if region and language else None


def get_remote_commit():
    """Read the release marker, which the build writes only once every asset is in place."""
    r = requests.get(f'{TITLEDB_RELEASE_URL}/{REMOTE_MARKER}', timeout=TIMEOUT,
                     headers={'Cache-Control': 'no-cache'})
    r.raise_for_status()
    return r.text.strip()


def get_local_commit():
    marker = os.path.join(TITLEDB_DIR, MARKER_FILE)
    if not os.path.isfile(marker):
        return None
    with open(marker, 'r') as f:
        return f.read().strip()


def download_file(file):
    """Stream one compressed asset, decompress it, and swap it in atomically."""
    store_path = os.path.join(TITLEDB_DIR, file)
    logger.info(f'Downloading {file} from remote titledb to {store_path}')
    decompressor = zstandard.ZstdDecompressor().decompressobj()
    with requests.get(f'{TITLEDB_RELEASE_URL}/{file}.zst', stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        with open(store_path + '.tmp', 'wb') as fpout:
            for chunk in r.iter_content(65536):
                fpout.write(decompressor.decompress(chunk))
    # A cut-off transfer still decompresses cleanly up to the break, so the frame end is what
    # tells us the file is whole. Without this the partial file would be swapped in as good.
    if not decompressor.eof:
        raise IOError(f'Truncated download for {file}')
    os.replace(store_path + '.tmp', store_path)


def update_titledb_files(app_settings):
    """Download changed titledb files. Returns (files written, remote commit)."""
    files_to_update = []
    region_titles_file = get_region_titles_file(app_settings)
    organizer_titles_file = get_organizer_region_titles_file(app_settings)
    remote_commit = get_remote_commit()
    current_commit = get_local_commit()

    if current_commit is None:
        logger.info('Retrieving titledb for the first time...')
    elif current_commit != remote_commit:
        logger.info(f'Titledb update available, current commit: {current_commit}, latest commit: {remote_commit}')
    else:
        logger.info(f'Titledb already up to date, commit: {current_commit}')

    if current_commit != remote_commit:
        files_to_update = TITLEDB_DEFAULT_FILES + [region_titles_file]
        files_to_update += [f for f in os.listdir(TITLEDB_DIR)
                            if REGION_FILE_RE.match(f) and f not in files_to_update]
    elif region_titles_file not in os.listdir(TITLEDB_DIR):
        files_to_update.append(region_titles_file)

    # The organizer's alternate-locale file follows the same "already covered by a
    # commit-changed refresh, otherwise fetched once if missing" rule as the display
    # locale above - it just isn't caught by either branch on its own first run, since
    # the catch-all glob only re-fetches files that already exist on disk.
    if organizer_titles_file and organizer_titles_file not in files_to_update \
            and organizer_titles_file not in os.listdir(TITLEDB_DIR):
        files_to_update.append(organizer_titles_file)

    for file in files_to_update:
        download_file(file)
    return files_to_update, remote_commit


def update_titledb(app_settings):
    """Download titledb JSON updates and (re)build titles.db if anything changed."""
    logger.info('Updating titledb...')
    if not os.path.isdir(TITLEDB_DIR):
        os.makedirs(TITLEDB_DIR, exist_ok=True)

    downloaded, remote_commit = update_titledb_files(app_settings)
    locale = get_locale(app_settings)
    locale_changed = store.get_imported_locale() != locale
    # A full rebuild recreates every table, including organizer_names, so that table
    # needs repopulating whenever this ran - not only when the organizer's own locale
    # setting changed.
    main_rebuilt = bool(downloaded or locale_changed)
    if main_rebuilt:
        store.import_from_json(os.path.join(TITLEDB_DIR, get_region_titles_file(app_settings)), locale)
        if locale_changed:
            from db import reset_files_organized
            reset_files_organized()

    organizer_locale = get_organizer_locale(app_settings)
    if organizer_locale:
        organizer_path = os.path.join(TITLEDB_DIR, get_organizer_region_titles_file(app_settings))
        if os.path.isfile(organizer_path):
            organizer_locale_changed = store.get_organizer_names_locale() != organizer_locale
            if main_rebuilt or organizer_locale_changed:
                store.import_organizer_names(organizer_path, organizer_locale)
                if organizer_locale_changed:
                    from db import reset_files_organized
                    reset_files_organized()

    # Written only once the files are on disk and imported, so a failure retries the same revision
    with open(os.path.join(TITLEDB_DIR, MARKER_FILE), 'w') as f:
        f.write(remote_commit)
    logger.info('titledb update done.')

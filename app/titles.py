import os
import re

import titledb
from constants import *
from utils import *
from settings import *
import logging

from nsz.nut import Keys

from containers.cnmt import identify_file_from_cnmt
from containers.container import read_display_versions

# Retrieve main logger
logger = logging.getLogger('main')

app_id_regex = r"\[([0-9A-Fa-f]{16})\]"
version_regex = r"\[v(\d+)\]"

# Re-export titledb.store query functions so existing callers
# (titles_lib.get_game_info, titles_lib.get_all_existing_versions, ...) keep working.
get_game_info = titledb.store.get_game_info
get_title_record = titledb.store.get_title_record
get_organizer_name = titledb.store.get_organizer_name
get_all_existing_versions = titledb.store.get_all_existing_versions
get_all_app_existing_versions = titledb.store.get_all_app_existing_versions
get_all_existing_dlc = titledb.store.get_all_existing_dlc
get_all_dlc_versions = titledb.store.get_all_dlc_versions

def getDirsAndFiles(path):
    entries = os.listdir(path)
    allFiles = []
    allDirs = []

    for entry in entries:
        fullPath = os.path.join(path, entry)
        if os.path.isdir(fullPath):
            allDirs.append(fullPath)
            dirs, files = getDirsAndFiles(fullPath)
            allDirs += dirs
            allFiles += files
        elif fullPath.split('.')[-1] in ALLOWED_EXTENSIONS:
            allFiles.append(fullPath)
    return allDirs, allFiles

def get_app_id_from_filename(filename):
    app_id_match = re.search(app_id_regex, filename)
    return app_id_match[1] if app_id_match is not None else None

def get_version_from_filename(filename):
    version_match = re.search(version_regex, filename)
    return version_match[1] if version_match is not None else None

def get_title_id_from_app_id(app_id, app_type):
    base_id = app_id[:-3]
    if app_type == APP_TYPE_UPD:
        title_id = base_id + '000'
    elif app_type == APP_TYPE_DLC:
        title_id = hex(int(base_id, base=16) - 1)[2:].rjust(len(base_id), '0') + '000'
    return title_id.upper()

def get_file_size(filepath):
    return os.path.getsize(filepath)

def get_file_info(filepath):
    filedir, filename = os.path.split(filepath)
    extension = filename.split('.')[-1]
    
    compressed = False
    if extension in ['nsz', 'xcz']:
        compressed = True

    return {
        'filepath': filepath,
        'filedir': filedir,
        'filename': filename,
        'extension': extension,
        'compressed': compressed,
        'size': get_file_size(filepath),
        'mtime': os.path.getmtime(filepath),
    }

def identify_appId(app_id):
    app_id = app_id.lower()

    cnmt = titledb.store.get_cnmt_latest(app_id)
    if cnmt is None:
        logger.warning(f'{app_id} not in cnmts, fallback to default identification.')
        if app_id.endswith('000'):
            return app_id.upper(), APP_TYPE_BASE
        if app_id.endswith('800'):
            return get_title_id_from_app_id(app_id, APP_TYPE_UPD), APP_TYPE_UPD
        return get_title_id_from_app_id(app_id, APP_TYPE_DLC), APP_TYPE_DLC

    title_type = cnmt.get('titleType')
    other_app_id = cnmt.get('otherApplicationId')
    if title_type == 128:
        return app_id.upper(), APP_TYPE_BASE
    if title_type == 129:
        if other_app_id:
            return other_app_id.upper(), APP_TYPE_UPD
        return get_title_id_from_app_id(app_id, APP_TYPE_UPD), APP_TYPE_UPD
    if title_type == 130:
        if other_app_id:
            return other_app_id.upper(), APP_TYPE_DLC
        return get_title_id_from_app_id(app_id, APP_TYPE_DLC), APP_TYPE_DLC

    logger.warning(f'{app_id} has unknown titleType {title_type}, fallback to default identification.')
    if app_id.endswith('000'):
        return app_id.upper(), APP_TYPE_BASE
    if app_id.endswith('800'):
        return get_title_id_from_app_id(app_id, APP_TYPE_UPD), APP_TYPE_UPD
    return get_title_id_from_app_id(app_id, APP_TYPE_DLC), APP_TYPE_DLC

def identify_file_from_filename(filename):
    title_id = None
    app_id = None
    app_type = None
    version = None
    errors = []

    app_id = get_app_id_from_filename(filename)
    if app_id is None:
        errors.append('Could not determine App ID from filename, pattern [APPID] not found. Title ID and Type cannot be derived.')
    else:
        title_id, app_type = identify_appId(app_id)

    version = get_version_from_filename(filename)
    if version is None:
        errors.append('Could not determine version from filename, pattern [vVERSION] not found.')
    
    error = ' '.join(errors)
    return app_id, title_id, app_type, version, error

def _identify_nup(filepath):
    """A NUP names its contents itself (containers/nup.py), keys or not."""
    from containers import nup
    contents = []
    for part in nup.contents(filepath):
        app_id = part['app_id']
        if part['kind'] == nup.KIND_BASE:
            title_id, app_type = app_id, APP_TYPE_BASE
        elif part['kind'] == nup.KIND_UPDATE:
            title_id, app_type = get_title_id_from_app_id(app_id, APP_TYPE_UPD), APP_TYPE_UPD
        else:
            title_id, app_type = identify_appId(app_id)
            app_type = APP_TYPE_DLC
        contents.append((title_id, app_type, app_id, part['version'], part['display_version'], None))
    return contents


def identify_file(filepath):
    filename = os.path.split(filepath)[-1]
    contents = []
    success = True
    error = ''
    if filename.lower().endswith('.nup'):
        identification = 'nup'
        try:
            contents = _identify_nup(filepath)
        except Exception as e:
            logger.error(f'Could not read NUP file {filepath}: {e}')
            error = str(e)
            success = False
    elif Keys.keys_loaded:
        identification = 'cnmt'
        try:
            cnmt_contents = identify_file_from_cnmt(filepath)

            # A second, independent read of the same file for its Control NCAs' display
            # version strings. Kept separate from identify_file_from_cnmt rather than
            # folded into one pass over the container: that function is already covered
            # by its own tests and used elsewhere unchanged, and a Control NCA that
            # fails to read (a corrupt one, or a master key gap narrower than the one
            # identification needed) must not turn a successful identification into a
            # failed one - so any failure here is swallowed into "no display versions
            # this time", never raised.
            try:
                display_versions = read_display_versions(filepath)
            except Exception as e:
                logger.warning(f'Could not read display versions from {filepath}: {e}')
                display_versions = {}

            for content in cnmt_contents:
                # The fourth field, the firmware the content needs, may be missing.
                app_type, app_id, version, *rest = content
                required = rest[0] if rest else None
                if app_type != APP_TYPE_BASE:
                    # need to get the title ID from cnmts
                    title_id, app_type = identify_appId(app_id)
                else:
                    title_id = app_id
                contents.append((title_id, app_type, app_id, version,
                                  display_versions.get((app_id, version)), required))
        except Exception as e:
            # Its contents can't be read (a master key missing for a newer game, a
            # damaged header): the name may still say what it is ([TitleID][vVersion]).
            app_id, title_id, app_type, version, name_error = identify_file_from_filename(filename)
            if not name_error:
                logger.warning(f'Could not read {filepath} ({e}): identified by its name')
                identification = 'filename'
                contents = [(title_id, app_type, app_id, version, None, None)]
            else:
                logger.error(f'Could not identify file {filepath} from metadata: {e}')
                error = str(e)
                success = False

    else:
        identification = 'filename'
        app_id, title_id, app_type, version, error = identify_file_from_filename(filename)
        if not error:
            contents.append((title_id, app_type, app_id, version, None, None))
        else:
            success = False

    if contents:
        contents = [{
            'title_id': c[0],
            'app_id': c[2],
            'type': c[1],
            'version': c[3],
            'display_version': c[4],
            # The firmware it needs, read from its own CNMT (None by name or for a DLC):
            # titledb's cnmts.json leaves it empty for many older updates.
            'required_system_version': c[5],
            } for c in contents]
    return identification, success, contents, error


def get_update_number(version):
    return int(version)//65536

def get_game_latest_version(all_existing_versions):
    return max(v['version'] for v in all_existing_versions)

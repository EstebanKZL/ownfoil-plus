import os
import re
import shutil
from constants import *
from db import *
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
import titles as titles_lib
from settings import mark_catalogue_revision
import sys
from pathlib import Path
from utils import *
from db import update_file_path

def prepare_template_names(format_data, windows_compatible):
    """Sanitize the names before formatting, so they cannot introduce path separators, and cap their length."""
    names = {k: sanitize_filename(v, windows_compatible) for k, v in format_data.items() if k in TEMPLATE_NAME_KEYS}
    if sys.platform == 'win32' or windows_compatible:
        names = {k: trim_name(v, MAX_NAME_WINDOWS) for k, v in names.items()}

    return {**format_data, **names}

# What a file holds, as its name says it: "Base", "Base + Update", "Base + Update + DLC"...
PACKAGE_PARTS = ((APP_TYPE_BASE, 'Base'), (APP_TYPE_UPD, 'Update'), (APP_TYPE_DLC, 'DLC'))


def package_contents(app_types):
    """{packageContents}: the kinds of content a file holds, in a fixed order - every DLC
    counts once ("Base + Update + DLC")."""
    present = set(app_types)
    return ' + '.join(label for kind, label in PACKAGE_PARTS if kind in present)


# Every field an organizer template may use (Settings > Library > Templates).
TEMPLATE_FIELDS = frozenset({
    'extension', 'titleId', 'titleName', 'appId', 'appVersion', 'patchLevel', 'appName',
    'packageContents', 'packageCounts', 'packageNames', 'sizeGb', 'sizeMb'})


def template_errors(templates):
    """[(template, problem)] for templates that would fail: an unknown {field} (it used to
    make the organizer skip every file silently), or braces that don't parse."""
    import string
    errors = []
    for key, template in (templates or {}).items():
        try:
            fields = [f for _, f, _, _ in string.Formatter().parse(template or '') if f is not None]
        except ValueError as e:
            errors.append((key, str(e)))
            continue
        for field in fields:
            name = field.split('.')[0].split('[')[0]
            if name not in TEMPLATE_FIELDS:
                errors.append((key, '{' + field + '}'))
    return errors


def package_counts(app_types):
    """{packageCounts}: how many of each the file holds, games first - "1G+1U+5D" (a part
    it lacks is left out: "1G+1U")."""
    types = list(app_types)
    parts = [(types.count(kind), letter) for kind, letter in
             ((APP_TYPE_BASE, 'G'), (APP_TYPE_UPD, 'U'), (APP_TYPE_DLC, 'D'))]
    return '+'.join(f'{n}{letter}' for n, letter in parts if n)


def size_fields(size):
    """{sizeGb} and {sizeMb}: the file's size, 3.23 and 3307 (GiB and MiB, like the web)."""
    size = size or 0
    return {'sizeGb': f'{size / 1024 ** 3:.2f}', 'sizeMb': f'{size / 1024 ** 2:.0f}'}


def organizer_name_locale(organizer_settings):
    """The organizer's naming locale (e.g. 'US.en'), or None when it should just use
    the library's display language - both `name_region` and `name_language` must be
    set for it to take effect."""
    region = organizer_settings.get('name_region')
    language = organizer_settings.get('name_language')
    return f'{region}.{language}' if region and language else None

def organize_file(file_obj, library_path, organizer_settings):
    try:
        templates = organizer_settings['templates']
        
        current_filepath = file_obj.filepath
        
        # Get the associated app for the file. A bundle (base + update + DLC in one
        # file) is named after its base game when it holds one.
        apps = list(file_obj.apps or [])
        app = next((a for a in apps if a.app_type == APP_TYPE_BASE), apps[0] if apps else None)
        if not app:
            logger.warning(f"No app associated with file {file_obj.filename}. Skipping organization.")
            return

        template = _get_template_for_file(file_obj, app, templates)

        # Retrieve data for template formatting
        format_data = {}
        # Get title name from the associated title_id
        title_info = titles_lib.get_game_info(app.title.title_id)
        if title_info['name'] == 'Unrecognized':
            logger.warning(f"No title info associated with file {file_obj.filename}. Skipping organization.")
            return
        format_data["extension"] = file_obj.extension
        format_data["titleId"] = app.title.title_id
        format_data["titleName"] = title_info['name']
        # Every template: what the file holds and how big it is, for names like
        # "Game [Base + Update + DLC] [3.23 GB]".
        # {packageContents}: "1G+1U+5D", as file names have always said it ({packageCounts}
        # is the same); {packageNames}: "Base + Update + DLC".
        format_data["packageContents"] = package_counts([a.app_type for a in apps])
        format_data["packageCounts"] = format_data["packageContents"]
        format_data["packageNames"] = package_contents([a.app_type for a in apps])
        format_data.update(size_fields(file_obj.size))
        if not file_obj.multicontent:
            format_data["appId"] = app.app_id
            format_data["appVersion"] = app.app_version
            format_data["patchLevel"] = titles_lib.get_update_number(app.app_version)

            game_info = titles_lib.get_game_info(app.app_id)
            if app.app_type == APP_TYPE_DLC:
                format_data["appName"] = game_info['name']
            else:
                format_data["appName"] = title_info['name']
        else:
            # A bundle takes every field a single file does, so any "multi" template
            # works: the base game's id and name, and the newest version it holds (its
            # update's). Without them a template using {appVersion} or {appName} failed
            # and the bundle was never organized.
            newest = max((int(a.app_version or 0) for a in apps), default=0)
            format_data["appId"] = app.app_id
            format_data["appVersion"] = str(newest)
            format_data["patchLevel"] = titles_lib.get_update_number(str(newest))
            format_data["appName"] = title_info['name']

        # Optionally rename in a language independent of the library's display locale
        # (Settings > Titles), so accents and other symbols the chosen language brings
        # along don't have to be fought with in filenames. Falls back to the display
        # name whenever the alternate locale has no entry for that id yet - a fresh
        # locale switch that titledb hasn't finished importing, for instance.
        name_locale = organizer_name_locale(organizer_settings)
        if name_locale:
            alt_title_name = titles_lib.get_organizer_name(app.title.title_id, name_locale)
            if alt_title_name:
                format_data["titleName"] = alt_title_name
            if "appName" in format_data:
                if app.app_type == APP_TYPE_DLC:
                    alt_app_name = titles_lib.get_organizer_name(app.app_id, name_locale)
                else:
                    alt_app_name = alt_title_name
                if alt_app_name:
                    format_data["appName"] = alt_app_name

        # Optionally strip trademark/copyright symbols (™, ®, ©) from the names used
        # in the organized path, mirroring Switch Library Manager's "clean name" option.
        if organizer_settings.get('clean_names', False):
            for key in ("titleName", "appName"):
                if key in format_data:
                    format_data[key] = clean_display_name(format_data[key])

        # Format the new relative path, sanitizing and shortening the names first
        windows_compatible = organizer_settings.get('windows_compatible', False)
        format_data = prepare_template_names(format_data, windows_compatible)
        safe_parts = sanitized_path_parts(template.format(**format_data), windows_compatible)
        if sys.platform == 'win32' or windows_compatible:
            safe_parts = truncate_path_parts(safe_parts, len(library_path))
        new_relative_path = os.path.join(*safe_parts)
        
        # Construct the full new path
        new_full_path = os.path.join(library_path, new_relative_path)

        if current_filepath == new_full_path:
            return True

        # Already organized with an "(n)" suffix from a previous collision:
        # Avoid re-running the rename loop only to bail out at the same name.
        new_dir_norm = os.path.dirname(new_full_path)
        base_name = os.path.splitext(os.path.basename(new_full_path))[0]
        current_dir = os.path.dirname(current_filepath)
        current_name = os.path.basename(current_filepath)
        if current_dir == new_dir_norm and os.path.exists(new_full_path) and re.fullmatch(
            rf"{re.escape(base_name)}\(\d+\)\.{re.escape(file_obj.extension)}",
            current_name,
        ):
            return True
        
        # Ensure the directory exists
        new_dir = os.path.dirname(new_full_path)
        try:
            os.makedirs(new_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"Error creating directory {new_dir} for file {file_obj.filename}: {e}")
            return
        
        # Move the file, handling duplicates.
        library_path_str = get_library_path(file_obj.library_id)
        original_filename = file_obj.filename

        counter = 1
        candidate = new_full_path
        src = current_filepath
        while True:
            if candidate == current_filepath:
                return True
            try:
                add_ignored_event(src, candidate)
                if os.path.exists(candidate):
                    raise FileExistsError(candidate)
                shutil.move(src, candidate)
                update_file_path(library_path_str, current_filepath, candidate)
                rel = os.path.relpath(candidate, library_path_str)
                logger.info(f'Organizing file: {original_filename} → {rel}')
                if organizer_settings.get('move_companions', True):
                    try:
                        move_companion_files(current_filepath, candidate, library_path_str)
                    except Exception as e:
                        # The game itself is in place: its notes are a nice-to-have.
                        logger.warning(f'Could not move the companion files of {original_filename}: {e}')
                return True
            except (FileExistsError, IntegrityError) as e:
                pop_ignored_event(src_path=src, dest_path=candidate)
                # If the move already happened, the file is now at `candidate`;
                # the next iteration must move from there, not from the original.
                if os.path.exists(candidate) and not os.path.exists(src):
                    src = candidate
                counter += 1
                candidate = os.path.join(new_dir, f"{base_name}({counter}).{file_obj.extension}")
            except (shutil.Error, OSError) as e:
                logger.error(f"Error moving file from '{src}' to '{candidate}': {e}")
                pop_ignored_event(src_path=src, dest_path=candidate)
                return
        # No finally block needed for removing from ignored_move_events, as it's removed by the watchdog handler

    except Exception as e:
        logger.error(f"An unexpected error occurred while organizing file {file_obj.filename}: {e}")

# Files that travel with a game when Organize moves it: release notes, checksums and the
# proof images a scene release comes with.
COMPANION_EXT = frozenset({'nfo', 'sfv', 'md5', 'sha1', 'sha256', 'diz', 'txt', 'jpg', 'jpeg', 'png'})
PROOF_DIRS = frozenset({'proof', 'proofs'})


def _is_companion(name):
    return os.path.splitext(name)[1][1:].lower() in COMPANION_EXT


def move_companion_files(old_path, new_path, library_root):
    """After a game moved from old_path to new_path: a companion named as the game
    (game.nfo next to game.nsp) takes its new name, and a folder left holding only
    companions (as a release comes: its NFO, SFV, images and Proof folder) hands them all
    over, so it ends up empty. A name already taken where it would go stays where it is.
    Returns (moved, skipped) lists of paths."""
    old_dir, new_dir = os.path.dirname(old_path), os.path.dirname(new_path)
    old_stem = os.path.splitext(os.path.basename(old_path))[0]
    new_stem = os.path.splitext(os.path.basename(new_path))[0]
    moved, skipped = [], []
    if not os.path.isdir(old_dir):
        return moved, skipped

    def move(src, dest):
        if os.path.exists(dest):
            logger.info(f'Organize: {os.path.basename(src)} stays where it is, '
                        f'{os.path.basename(dest)} already exists')
            skipped.append(src)
            return
        try:
            shutil.move(src, dest)
            moved.append(dest)
        except (shutil.Error, OSError) as e:
            logger.warning(f'Organize: could not move {src}: {e}')
            skipped.append(src)

    # 1. Named as the game: renamed along with it.
    for name in sorted(os.listdir(old_dir)):
        src = os.path.join(old_dir, name)
        stem, ext = os.path.splitext(name)
        if os.path.isfile(src) and _is_companion(name) and stem == old_stem:
            if old_dir != new_dir or stem != new_stem:
                move(src, os.path.join(new_dir, new_stem + ext))

    # 2. A release folder now holding only companions (never the library root, never
    #    the folder the game went to): the rest goes too.
    same = os.path.normcase(os.path.abspath(old_dir))
    if same in (os.path.normcase(os.path.abspath(library_root)),
                os.path.normcase(os.path.abspath(new_dir))):
        return moved, skipped
    entries = os.listdir(old_dir)
    only_companions = all(
        (os.path.isfile(os.path.join(old_dir, n)) and _is_companion(n))
        or (os.path.isdir(os.path.join(old_dir, n)) and n.lower() in PROOF_DIRS)
        for n in entries)
    if entries and only_companions:
        for name in sorted(entries):
            src = os.path.join(old_dir, name)
            # A companion left in place in step 1 (its new name taken) stays there - on a
            # case-sensitive disk its old name could still be free at the new folder.
            if src not in skipped:
                move(src, os.path.join(new_dir, name))
    return moved, skipped


def _get_template_for_file(file_obj, app, templates):
    """Helper function to determine the correct template for file organization."""
    if file_obj.multicontent:
        template_key = "multi"
    else:
        if app.app_type == APP_TYPE_BASE:
            template_key = "base"
        elif app.app_type == APP_TYPE_UPD:
            template_key = "update"
        elif app.app_type == APP_TYPE_DLC:
            template_key = "dlc"
    
    return templates.get(template_key) + '.{extension}'


def add_library_complete(app, watcher, path):
    """Add a library to settings, database, and watchdog"""
    from settings import add_library_path_to_settings
    
    with app.app_context():
        # Add to settings
        success, errors = add_library_path_to_settings(path)
        if not success:
            return success, errors
        
        # Add to database
        add_library(path)
        
        # Add to watchdog
        watcher.add_directory(path)
        
        logger.info(f"Successfully added library: {path}")
        return True, []

def remove_library_complete(app, watcher, path):
    """Remove a library: stop watching, drop from settings, enqueue DB cleanup task."""
    from settings import delete_library_path_from_settings
    import tasks as tasks_mod

    with app.app_context():
        watcher.remove_directory(path)
        success, errors = delete_library_path_from_settings(path)
        if success:
            tasks_mod.enqueue_task('remove_library', {'library_path': path})
        return success, errors

def init_libraries(app, watcher, paths):
    with app.app_context():
        # delete non existing libraries
        for library in get_libraries():
            path = library.path
            if not os.path.exists(path):
                logger.warning(f"Library {path} no longer exists, deleting from database.")
                # Use the complete removal function for consistency
                remove_library_complete(app, watcher, path)

        # add libraries and start watchdog
        for path in paths:
            # Check if library already exists in database
            existing_library = Libraries.query.filter_by(path=path).first()
            if not existing_library:
                # add library paths to watchdog if necessary
                watcher.add_directory(path)
                add_library(path)
            else:
                # Ensure watchdog is monitoring existing library
                watcher.add_directory(path)

def add_missing_apps_for_title(title_id):
    """Expand missing base/update/DLC apps (owned=False) for a single title via one bulk upsert.
    Safe to run concurrently with other workers expanding the same title."""
    title_db_id = get_title_id_db_id(title_id)

    rows = []
    update_app_id = title_id[:-3] + '800'
    base_added = False
    for version_info in titles_lib.get_all_existing_versions(title_id):
        v = str(version_info['version'])
        if v == '0':
            rows.append(dict(app_id=title_id, app_version=v, app_type=APP_TYPE_BASE,
                             owned=False, title_id=title_db_id,
                             release_date=version_info.get('release_date')))
            base_added = True
        else:
            rows.append(dict(app_id=update_app_id, app_version=v, app_type=APP_TYPE_UPD,
                             owned=False, title_id=title_db_id,
                             release_date=version_info.get('release_date')))

    if not base_added:
        rows.append(dict(app_id=title_id, app_version="0", app_type=APP_TYPE_BASE,
                         owned=False, title_id=title_db_id, release_date=None))

    for dlc_app_id, dlc_version, dlc_release_date in titles_lib.get_all_dlc_versions(title_id):
        rows.append(dict(app_id=dlc_app_id, app_version=str(dlc_version),
                         app_type=APP_TYPE_DLC, owned=False, title_id=title_db_id,
                         release_date=dlc_release_date))

    # Only refresh release_date on conflict — never touch `owned` or any other
    # column, since this same row may have been flipped to owned=True by a file
    # scan in between.
    stmt = sqlite_insert(Apps.__table__).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=['app_id', 'app_version'],
        set_={'release_date': stmt.excluded.release_date},
        where=Apps.__table__.c.release_date.is_not(stmt.excluded.release_date),
    )
    result = db.session.execute(stmt)
    db.session.commit()
    apps_upserted = result.rowcount or 0
    if apps_upserted:
        logger.debug(f'Upserted {apps_upserted} apps for Title ID {title_id}')
    return apps_upserted


# What the library reads from the catalogue, by revision: 1, every DLC titles.json lists
# (titledb.store.dlc_id_range), not only cnmts.json's; 2, update versions from more
# sources (titledb/extra_versions.py). Each one adds content that was out there already.
CATALOGUE_REVISION = 2


def add_missing_apps_to_db():
    """Batch: expand missing apps for every title. Used post-titledb-update."""
    logger.info('Adding missing apps to database...')
    known_apps = {(a, v) for a, v in db.session.query(Apps.app_id, Apps.app_version).all()}
    titles = get_all_titles()
    total = 0
    for n, title in enumerate(titles):
        total += add_missing_apps_for_title(title.title_id)
        if (n + 1) % 100 == 0:
            logger.info(f'Processed {n + 1}/{len(titles)} titles, upserted {total} apps so far')
    logger.info(f'Finished adding missing apps to database. Total apps upserted: {total}')
    # The first pass of a new catalogue revision adds what the catalogue always had (every
    # DLC cnmts.json lacked, updates the release didn't know): old, not new - announced,
    # it would be one message per DLC and update of every game. Later passes announce as before.
    first_catalogue_pass = mark_catalogue_revision(CATALOGUE_REVISION)
    # Only this batch path (run after a TitleDB refresh) announces new versions: the
    # per-title one runs when a game is first added, where every existing update/DLC
    # is "new" to the database but not to the world. An empty database is the same
    # case at install scale.
    if known_apps and not first_catalogue_pass:
        notify_new_apps_available(known_apps)

def notify_new_apps_available(known_apps):
    """Announce update/DLC rows that appeared since `known_apps` was taken, for games
    whose base the library actually has."""
    import notifications
    if not notifications.is_enabled(notifications.EVENT_UPDATE_AVAILABLE):
        return
    rows = (db.session.query(Apps.app_id, Apps.app_version, Apps.app_type, Titles.title_id)
            .join(Titles, Apps.title_id == Titles.id)
            .filter(Apps.owned.is_(False), Apps.app_type.in_([APP_TYPE_UPD, APP_TYPE_DLC]),
                    Titles.have_base.is_(True))
            .all())
    for app_id, app_version, app_type, title_id in rows:
        if (app_id, app_version) in known_apps:
            continue
        notifications.notify(notifications.EVENT_UPDATE_AVAILABLE, notifications.app_label(
            title_id if app_type == APP_TYPE_UPD else app_id, app_type, app_version), title_id=title_id)

def remove_outdated_update_files():
    logger.info("Starting removal of outdated update files...")
    try:
        titles = get_all_titles()
        
        for title in titles:
            title_apps = get_all_title_apps(title.title_id)
            
            # Filter for owned update apps
            owned_update_apps = [app for app in title_apps if app.get('app_type') == APP_TYPE_UPD and app.get('owned')]
            
            # If there's only one or no owned update apps, there's no "greater version available" to compare against.
            if len(owned_update_apps) <= 1:
                continue
            
            # Group owned update apps by their version for easy lookup
            owned_versions = {int(app['app_version']) for app in owned_update_apps}
            
            # Iterate through all update apps (owned or not) for this title
            for app_data in title_apps:
                if app_data.get('app_type') == APP_TYPE_UPD:
                    current_app_version = int(app_data['app_version'])
                    
                    # Check if there's a greater owned version available for this title
                    has_greater_owned_version = any(
                        owned_v > current_app_version for owned_v in owned_versions
                    )
                    
                    if has_greater_owned_version:
                        # Get the actual App object from the database
                        app_obj = get_app_by_id_and_version(app_data['app_id'], app_data['app_version'])
                        
                        if app_obj:
                            # Get files associated with this specific app version
                            # Create a list to iterate over as the original collection might change during deletion
                            files_to_process = list(app_obj.files) 
                            for file_obj in files_to_process:
                                # Check if file meets criteria: identified, not multicontent
                                if file_obj.identified and not file_obj.multicontent:
                                    logger.info(f"Removing outdated update file: {file_obj.filepath} (App ID: {app_obj.app_id}, Version: {app_obj.app_version}) - Greater owned version available.")
                                    
                                    # Remove from disk
                                    if os.path.exists(file_obj.filepath):
                                        try:
                                            # Add the delete event to the ignored list before performing the remove
                                            add_ignored_event(file_obj.filepath, '')
                                            os.remove(file_obj.filepath)
                                            logger.debug(f"Deleted physical file: {file_obj.filepath}")
                                            # Remove from database and update app owned status
                                            # This function handles db.session.delete(file_obj) and app.owned status
                                            remove_file_from_apps(file_obj.id)
                                        except OSError as e:
                                            logger.error(f"Error deleting physical file {file_obj.filepath}: {e}")
                                            # If an error occurs, remove from the ignored list
                                            pop_ignored_event(src_path=file_obj.filepath, dest_path='')
                                    else:
                                        logger.warning(f"Physical file not found for deletion: {file_obj.filepath}")
                                    
        logger.info(f"Finished removal of outdated update files.")
    except Exception as e:
        logger.error(f"Error during removal of outdated update files: {e}")


def outdated_update_groups():
    """A read-only preview of what `remove_outdated_update_files` would delete: for
    every title with more than one owned Update version, the newest owned version's
    files (kept) against every older owned version's files that are safe to remove
    (identified and not part of a multi-content bundle - the same two conditions
    `remove_outdated_update_files` itself checks before deleting anything).

    Returns a list of (newest_app, keep_files, remove_files) tuples. A title is
    skipped entirely when it has one or zero owned update versions (nothing to
    compare against) or when the newest version has no file of its own yet."""
    groups = []
    for title in get_all_titles():
        title_apps = get_all_title_apps(title.title_id)
        owned_update_apps = [a for a in title_apps if a.get('app_type') == APP_TYPE_UPD and a.get('owned')]
        if len(owned_update_apps) <= 1:
            continue

        newest = max(owned_update_apps, key=lambda a: int(a['app_version']))
        newest_app_obj = get_app_by_id_and_version(newest['app_id'], newest['app_version'])
        if not newest_app_obj or not newest_app_obj.files:
            continue

        remove_entries = []  # (version_str, file)
        for app_data in owned_update_apps:
            if int(app_data['app_version']) >= int(newest['app_version']):
                continue
            app_obj = get_app_by_id_and_version(app_data['app_id'], app_data['app_version'])
            if not app_obj:
                continue
            remove_entries.extend((app_data['app_version'], f) for f in app_obj.files
                                  if f.identified and not f.multicontent
                                  and (f.extension or '').lower() != 'nup')

        if not remove_entries:
            continue
        groups.append((newest_app_obj, list(newest_app_obj.files), remove_entries))
    return groups

# --- Duplicate file resolution -------------------------------------------------------
#
# A "duplicate" here means: an app (a specific title+content+version) that has more
# than one physical file attached to it - typically from re-downloading something
# already owned. organize_file()'s collision handling already keeps every one of them
# safely on disk (the extra copy gets a "(n)" suffix rather than being overwritten or
# silently merged), so nothing is ever lost by that step alone. This section is about
# what happens *after*: once verification has an answer for each copy, deciding
# whether it's now safe to say "keep the healthiest one, drop the rest."
#
# This is destructive (it deletes files), so every decision here is deliberately
# conservative: automatic resolution only ever acts when every file's verdict is one
# of Valid/Repack/Corrupt (a complete, unambiguous answer - never on a file that's
# still Unverified, Modified, or only checked at signature depth), and never picks a
# winner on a tie between two files at the same rank. Anything outside those bounds is
# left for a person to resolve deliberately, not guessed at.

# Valid beats Repack beats Corrupt - the exact ranking asked for. Every other status
# (Modified, Signature ok/failed, Unverified) is deliberately absent: a duplicate group
# containing any of them is not decided automatically at all, see
# `automatic_duplicate_winner`.
DUPLICATE_RANK = {'VALID': 3, 'REPACK': 2, 'CORRUPT': 1}

# A filename this organizer's own collision handling produced: "name(2).ext",
# "name(3).ext", etc. - never matches a plain, unsuffixed name.
_SUFFIX_NAME_RE = re.compile(r'^(?P<base>.+)\((?P<n>\d+)\)(?P<ext>\.[^.]+)$')


def duplicate_file_groups():
    """Every owned app that currently has more than one physical file attached,
    paired with those files. This is the library-wide "what has duplicates right now"
    view both the automatic task and the manual resolution API work from."""
    groups = []
    seen = set()
    for app in Apps.query.filter_by(owned=True).all():
        # A NUP (decrypted) and an NSP/XCI of the same content are different things to
        # keep, never duplicates of each other: NUPs are compared with NUPs only, every
        # other format with the others.
        for files in ([f for f in app.files if (f.extension or '').lower() != 'nup'],
                      [f for f in app.files if (f.extension or '').lower() == 'nup']):
            if len(files) < 2:
                continue
            # Two copies of a bundle share every app they hold: one group for them, not
            # one per app (the game, its update and each DLC).
            ids = frozenset(f.id for f in files)
            if ids in seen:
                continue
            seen.add(ids)
            groups.append((app, files))
    return groups


def automatic_duplicate_winner(files):
    """Which of `files` to automatically keep, or None if it can't be decided safely.

    Requires every file to have a definitive Valid/Repack/Corrupt verdict already (an
    unverified, modified, or signature-only file makes the whole group ineligible for
    automatic resolution - it needs an actual look), and requires a single clear best
    rank (two files tied at the same rank are left for a person to choose between - or
    for `duplicate_winner_preferring_largest` below, if that's been opted into).
    """
    contenders = _ranked_contenders(files)
    if contenders is None or len(contenders) != 1:
        return None
    return contenders[0]


def duplicate_winner_preferring_largest(files):
    """Like `automatic_duplicate_winner`, but breaks a tie at the best rank by keeping
    the largest file instead of refusing to decide.

    Still requires every file to have a complete Valid/Repack/Corrupt verdict - an
    unverified, modified, or signature-only file anywhere in the group still makes the
    whole group ineligible, exactly like `automatic_duplicate_winner`. The only
    difference is the very last step: once every file is ranked and more than one
    shares the top rank, every one of those tied files has *already* independently
    passed the same verification the sole winner would have - this is a preference
    between equally-legitimate copies (a newer build, extra padding, a different
    revision), not a guess about which one is real. Used for the manual "resolve by
    size" bulk action, which always resolves by size regardless of settings - a
    person invoking it explicitly wants that. For the opt-in automatic setting, see
    `duplicate_winner_with_preferences` below, which also accounts for compression.
    """
    return duplicate_winner_with_preferences(files, prefer_larger_on_tie=True)


def duplicate_winner_with_preferences(files, *, prefer_multicontent=False,
                                      prefer_larger_on_tie=False,
                                      compression_preference='none'):
    """Like `automatic_duplicate_winner`, but breaks a tie at the best rank using
    whichever of these independent, opt-in preferences apply - all default to
    "don't guess," matching the strict function's behavior when none is given. They
    are applied in this fixed order:

    - `prefer_multicontent` (upstream ownfoil calls this "prefer multi-content
      files"): applied *first*, but only ever among files that are already tied at
      the single best verification rank - unlike upstream, which lets this decide
      before verification is even considered, risking a worse-verified bundle beating
      a validly-verified individual file. Here it can only choose between copies that
      have *already* independently earned the same verdict, so if every tied file (or
      none of them) is multi-content, it settles nothing and falls through.
    - `compression_preference` ('compressed' or 'uncompressed'): applied next, to
      whatever's left after the step above. A compressed file is inherently smaller
      than the same content uncompressed, so a byte-size comparison alone would always
      penalize compression even when someone has explicitly chosen to compress their
      library - if the tied files aren't all the same compression status, narrow down
      to whichever side is preferred before even considering size.
    - `prefer_larger_on_tie`: applied to whatever's left after the steps above (or to
      the full tied set, if neither distinguished anything) - the file with more bytes
      wins.

    Every file must still have a complete Valid/Repack/Corrupt verdict, exactly like
    `automatic_duplicate_winner` - an unverified, modified, or signature-only file
    anywhere in the group still makes the whole group ineligible, regardless of any
    preference below.
    """
    contenders = _ranked_contenders(files)
    if not contenders:
        return None
    if len(contenders) == 1:
        return contenders[0]

    if prefer_multicontent:
        narrowed = [f for f in contenders if f.multicontent]
        # Only narrow down when it actually distinguishes something - if every tied
        # file (or none of them) is multi-content, it settles nothing.
        if narrowed and len(narrowed) < len(contenders):
            contenders = narrowed
            if len(contenders) == 1:
                return contenders[0]

    if compression_preference in ('compressed', 'uncompressed'):
        want_compressed = compression_preference == 'compressed'
        narrowed = [f for f in contenders if bool(f.compressed) == want_compressed]
        # Only narrow down when it actually distinguishes something - if every tied
        # file (or none of them) already matches the preference, it settles nothing.
        if narrowed and len(narrowed) < len(contenders):
            contenders = narrowed
            if len(contenders) == 1:
                return contenders[0]

    if prefer_larger_on_tie:
        return max(contenders, key=lambda f: f.size)
    return None


def _ranked_contenders(files):
    """Every file among `files` at the best (Valid > Repack > Corrupt) rank, or None
    if any file in the group lacks one of those three definitive verdicts - the shared
    eligibility gate both duplicate-winner functions above use."""
    statuses = [(f, verification_status(f)) for f in files]
    if any(status not in DUPLICATE_RANK for _, status in statuses):
        return None
    best_rank = max(DUPLICATE_RANK[status] for _, status in statuses)
    return [f for f, status in statuses if DUPLICATE_RANK[status] == best_rank]


def _delete_duplicate_file(file_obj):
    """Physically remove one losing copy, detach it from its app, and delete its row.

    Unlike remove_outdated_update_files (which only detaches and lets
    remove_missing_files_from_db's next pass clean up the row once the file is gone),
    this deletes the row immediately: the very next step here renames the survivor
    onto this file's old (plain, unsuffixed) name, and filepath is a unique column -
    a stale row still claiming that path would collide with it in the same instant.
    There's no ambiguity to preserve by waiting, unlike a file that merely vanished
    and might reappear.
    """
    if os.path.exists(file_obj.filepath):
        try:
            add_ignored_event(file_obj.filepath, '')
            os.remove(file_obj.filepath)
        except OSError as e:
            logger.error(f"Could not remove duplicate file '{file_obj.filepath}': {e}")
            pop_ignored_event(src_path=file_obj.filepath, dest_path='')
            return False
    else:
        logger.warning(f"Duplicate file already missing from disk: {file_obj.filepath}")
    filepath = file_obj.filepath  # captured before delete: the row is gone after commit
    remove_file_from_apps(file_obj.id)
    Files.query.filter_by(id=file_obj.id).delete(synchronize_session=False)
    db.session.commit()
    logger.info(f"Removed duplicate file: {filepath}")
    return True


def _rename_off_duplicate_suffix(file_obj):
    """If this file's name carries a "(n)" collision suffix and the plain (unsuffixed)
    name is now free - typically because the file that was occupying it just got
    removed as an inferior duplicate - rename it there. The file left standing after a
    duplicate cleanup should not be the one still looking like a leftover copy."""
    match = _SUFFIX_NAME_RE.match(file_obj.filename)
    if not match:
        return
    plain_name = match.group('base') + match.group('ext')
    plain_path = os.path.join(file_obj.folder, plain_name)
    if plain_path == file_obj.filepath or os.path.exists(plain_path):
        return  # nothing to do, or still occupied - never clobber another file
    try:
        add_ignored_event(file_obj.filepath, plain_path)
        shutil.move(file_obj.filepath, plain_path)
    except OSError as e:
        logger.warning(f"Could not rename '{file_obj.filepath}' off its duplicate suffix: {e}")
        pop_ignored_event(src_path=file_obj.filepath, dest_path=plain_path)
        return
    update_file_path(file_obj.folder, file_obj.filepath, plain_path)
    logger.info(f"Renamed surviving duplicate to drop its suffix: {plain_name}")


def resolve_duplicate_files(keep_file_id, all_file_ids):
    """Keep `keep_file_id` among `all_file_ids` (all of which must belong to the same
    app), deleting the rest and renaming the survivor off any "(n)" suffix it may have.

    Shared by both the automatic task and the manual GraphQL mutation - the only
    difference between them is how `keep_file_id` gets chosen, never what happens once
    it has been.
    """
    keep_file = db.session.get(Files, keep_file_id)
    if keep_file is None:
        return False
    for file_id in all_file_ids:
        if file_id == keep_file_id:
            continue
        loser = db.session.get(Files, file_id)
        if loser is not None:
            _delete_duplicate_file(loser)
    _rename_off_duplicate_suffix(keep_file)
    return True


def update_title_flags(title_id):
    """Recompute have_base / up_to_date / complete for a single title.
    Wrapped in BEGIN IMMEDIATE to serialize concurrent recomputes and prevent
    lost updates when another worker is mutating owned state for the same title."""
    connection = db.engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute("SELECT id FROM titles WHERE title_id = ?", (title_id,))
        row = cursor.fetchone()
        if not row:
            connection.commit()
            return
        title_db_id = row[0]

        cursor.execute(
            "SELECT app_type, app_version, owned FROM apps WHERE title_id = ?",
            (title_db_id,)
        )
        title_apps = [{'app_type': r[0], 'app_version': r[1], 'owned': bool(r[2])} for r in cursor.fetchall()]

        owned_base_apps = [a for a in title_apps if a['app_type'] == APP_TYPE_BASE and a['owned']]
        have_base = len(owned_base_apps) > 0

        available_update_apps = [a for a in title_apps if a['app_type'] == APP_TYPE_UPD]
        owned_update_apps = [a for a in available_update_apps if a['owned']]
        if not available_update_apps:
            up_to_date = True
        elif not owned_update_apps:
            up_to_date = False
        else:
            highest_available = max(int(a['app_version']) for a in available_update_apps)
            highest_owned = max(int(a['app_version']) for a in owned_update_apps)
            up_to_date = highest_owned >= highest_available

        cursor.execute(
            "SELECT app_id, app_version, owned FROM apps WHERE title_id = ? AND app_type = ?",
            (title_db_id, APP_TYPE_DLC)
        )
        # A DLC is in the library when any version of it is: a newer one is a pending
        # update of it (counted apart, see gql's stats.outdatedDlc), not a missing DLC.
        dlc_owned = {}
        for dlc_app_id, _version, owned in cursor.fetchall():
            dlc_owned[dlc_app_id] = dlc_owned.get(dlc_app_id, False) or bool(owned)
        complete = all(dlc_owned.values())

        cursor.execute(
            "UPDATE titles SET have_base = ?, up_to_date = ?, complete = ? WHERE id = ?",
            (int(have_base), int(up_to_date), int(complete), title_db_id)
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def update_titles():
    """Batch: recompute all titles. Also removes titles with no owned apps."""
    titles_removed = remove_titles_without_owned_apps()
    if titles_removed > 0:
        logger.info(f"Removed {titles_removed} titles with no owned apps.")

    for title in get_all_titles():
        update_title_flags(title.title_id)


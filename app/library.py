import os
import re
import shutil
from constants import *
from db import *
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
import titles as titles_lib
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
        
        # Get the associated app for the file
        app = file_obj.apps[0] if file_obj.apps else None
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
        if not file_obj.multicontent:
            format_data["appId"] = app.app_id
            format_data["appVersion"] = app.app_version
            format_data["patchLevel"] = titles_lib.get_update_number(app.app_version)

            game_info = titles_lib.get_game_info(app.app_id)
            if app.app_type == APP_TYPE_DLC:
                format_data["appName"] = game_info['name']
            else:
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


def add_missing_apps_to_db():
    """Batch: expand missing apps for every title. Used post-titledb-update."""
    logger.info('Adding missing apps to database...')
    titles = get_all_titles()
    total = 0
    for n, title in enumerate(titles):
        total += add_missing_apps_for_title(title.title_id)
        if (n + 1) % 100 == 0:
            logger.info(f'Processed {n + 1}/{len(titles)} titles, upserted {total} apps so far')
    logger.info(f'Finished adding missing apps to database. Total apps upserted: {total}')

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
    return [(app, list(app.files)) for app in Apps.query.filter_by(owned=True).all()
            if len(app.files) > 1]


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


def duplicate_winner_with_preferences(files, *, prefer_larger_on_tie=False,
                                      compression_preference='none'):
    """Like `automatic_duplicate_winner`, but breaks a tie at the best rank using
    whichever of these two independent, opt-in preferences apply - both default to
    "don't guess," matching the strict function's behavior when neither is given:

    - `compression_preference` ('compressed' or 'uncompressed'): applied *first*. A
      compressed file is inherently smaller than the same content uncompressed, so a
      byte-size comparison alone would always penalize compression even when someone
      has explicitly chosen to compress their library - if the tied files aren't all
      the same compression status, narrow down to whichever side is preferred before
      even considering size.
    - `prefer_larger_on_tie`: applied to whatever's left after the step above (or to
      the full tied set, if compression didn't distinguish anything) - the file with
      more bytes wins.

    Every file must still have a complete Valid/Repack/Corrupt verdict, exactly like
    `automatic_duplicate_winner` - an unverified, modified, or signature-only file
    anywhere in the group still makes the whole group ineligible, regardless of either
    preference below.
    """
    contenders = _ranked_contenders(files)
    if not contenders:
        return None
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
        dlc_by_id = {}
        for dlc_app_id, version_str, owned in cursor.fetchall():
            version = int(version_str)
            if dlc_app_id not in dlc_by_id or version > dlc_by_id[dlc_app_id]['version']:
                dlc_by_id[dlc_app_id] = {'version': version, 'owned': bool(owned)}
        complete = all(d['owned'] for d in dlc_by_id.values()) if dlc_by_id else True

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


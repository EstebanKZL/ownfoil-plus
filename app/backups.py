"""Backups of what can't be rebuilt from the library itself: the database (users,
identification and verification results, title overrides, task history), the settings
file and the console keys. TitleDB (titles.db) and artwork are re-downloadable, so they
are left out.

A backup is one zip in CONFIG_DIR/backups - the persistent config volume - written
under a temporary name and renamed into place, so a crash never leaves a truncated
archive that looks valid. The database is copied through SQLite's online backup API,
which gives a consistent snapshot while workers keep writing.
"""
import datetime
import logging
import os
import re
import sqlite3
import tempfile
import zipfile

from constants import CONFIG_DIR

logger = logging.getLogger('main')

BACKUP_DIR = os.path.join(CONFIG_DIR, 'backups')
PREFIX = 'ownfoil-backup-'
NAME_RE = re.compile(r'^ownfoil-backup-\d{8}-\d{6}\.zip$')


def _snapshot_database(dest_path):
    from db import db
    raw = db.engine.raw_connection()
    try:
        dest = sqlite3.connect(dest_path)
        try:
            raw.driver_connection.backup(dest)
        finally:
            dest.close()
    finally:
        raw.close()


def create_backup():
    """Write a new backup and return its listing entry."""
    import settings as settings_mod
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = f'{PREFIX}{datetime.datetime.now().strftime("%Y%m%d-%H%M%S")}.zip'
    final_path = os.path.join(BACKUP_DIR, name)
    with tempfile.TemporaryDirectory(dir=BACKUP_DIR) as scratch:
        db_copy = os.path.join(scratch, 'ownfoil.db')
        _snapshot_database(db_copy)
        partial = os.path.join(scratch, name)
        with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, 'ownfoil.db')
            for path, arcname in ((settings_mod.CONFIG_FILE, 'settings.yaml'),
                                  (settings_mod.KEYS_FILE, 'keys.txt')):
                if os.path.isfile(path):
                    zf.write(path, arcname)
        os.replace(partial, final_path)
    logger.info(f'Backup written: {final_path}')
    return _entry(name)


def _entry(name):
    path = os.path.join(BACKUP_DIR, name)
    stat = os.stat(path)
    return {'name': name, 'size': stat.st_size,
            'created': datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}


def list_backups():
    """Newest first. Ignores anything in the folder that isn't one of ours."""
    try:
        names = [n for n in os.listdir(BACKUP_DIR) if NAME_RE.match(n)]
    except FileNotFoundError:
        return []
    # The timestamp in the name sorts chronologically.
    return [_entry(n) for n in sorted(names, reverse=True)]


def prune_backups(keep):
    """Delete all but the `keep` newest backups. Returns how many were removed."""
    removed = 0
    for entry in list_backups()[max(1, int(keep)):]:
        try:
            os.remove(os.path.join(BACKUP_DIR, entry['name']))
            removed += 1
        except OSError as e:
            logger.warning(f'Could not delete old backup {entry["name"]}: {e}')
    if removed:
        logger.info(f'Removed {removed} old backup(s).')
    return removed


def backup_path(name):
    """The full path of an existing backup, or None - also for any name that isn't
    exactly one of ours, so a download/delete can't be pointed outside the folder."""
    if not name or not NAME_RE.match(name):
        return None
    path = os.path.join(BACKUP_DIR, name)
    return path if os.path.isfile(path) else None

"""The `files` realtime topic: a signature of the files table, for the Files page.

Files keeps each tab's rows until the files change - a tab entered again shows at once,
and one that would be stale (a file deleted in Duplicates still listed in All files, say)
is asked again. The signature is one aggregate over the table: rows added or removed,
sizes, names and folders (organize), formats (compression), identification and
verification all move it. It is read every few seconds and only while a Files page
watches it; nothing is sent unless it changed.
"""
import hashlib

from sqlalchemy import text

import realtime
from db import db

# Seconds between reads: a change shows on the page within this, which is plenty for a
# list a person reads, and keeps a library of tens of thousands of files cheap to watch.
DELAY = 3.0

_state = None


def signature():
    """A short fingerprint of everything the Files tabs show about the files."""
    row = db.session.execute(text("""
        SELECT COUNT(*), COALESCE(MAX(id), 0), TOTAL(size), TOTAL(LENGTH(filepath)),
               TOTAL(identified), TOTAL(identification_attempts), TOTAL(compressed),
               COALESCE(MAX(verified_at), ''), TOTAL(verified_at IS NOT NULL),
               TOTAL(hash_valid), TOTAL(signature_valid), TOTAL(organized),
               (SELECT COUNT(*) FROM app_files)
        FROM files""")).first()
    return hashlib.sha1(repr(tuple(row)).encode()).hexdigest()[:16]


def files_snapshot():
    """What a page connecting now starts from. It leaves the poller's own state alone: a
    second page connecting must not swallow a change the first has yet to be told."""
    return [{'id': 'files', 'revision': signature()}]


def files_poll():
    """An update when the signature moved since the last read (the first read sends one
    too, which a page already holding that revision ignores)."""
    global _state
    current = signature()
    if current == _state:
        return []
    _state = current
    return [('update', {'id': 'files', 'revision': current})]


realtime.register_topic('files', access='admin', snapshot=files_snapshot, poll=files_poll,
                        delay=lambda: DELAY)

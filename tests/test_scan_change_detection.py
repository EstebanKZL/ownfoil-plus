"""scan_library_task must never treat "I scanned again" as a reason to re-verify
anything by itself - only an actual on-disk change (different size or mtime, the same
signal the live watcher already uses) does. This closes the gap the watcher alone
doesn't cover: content replaced while ownfoil wasn't running, or a slow-polling
network mount, where nothing live ever saw the change - Scan is the only thing that
would.
"""
import os
import types

import pytest

import tasks
from db import Files, Libraries, db
from app import create_app

from test_compression import _settings


@pytest.fixture
def env(tmp_path, monkeypatch):
    app = create_app(f"sqlite:///{tmp_path/'test.db'}")
    lib_dir = tmp_path / "games"
    lib_dir.mkdir()
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    library = Libraries(path=str(lib_dir))
    db.session.add(library)
    db.session.commit()

    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(verify=True))
    monkeypatch.setattr(tasks, "enqueue_task", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "enqueue_or_child", lambda *a, **k: None)
    monkeypatch.setattr(tasks, "set_waiting_for_children", lambda: None)

    def seed(name="Game.nsp", content=b"RAWDATA", **columns):
        path = lib_dir / name
        path.write_bytes(content)
        f = Files(filepath=str(path), library_id=library.id, folder=str(lib_dir),
                  filename=name, extension=name.rsplit(".", 1)[-1], size=len(content),
                  mtime=os.path.getmtime(path), identified=True, **columns)
        db.session.add(f)
        db.session.commit()
        return f

    yield types.SimpleNamespace(app=app, lib_dir=lib_dir, library=library, seed=seed)
    ctx.pop()


def test_rescanning_an_unchanged_file_does_not_touch_its_verification(env):
    """The exact behavior asked for: scanning again, by itself, must never be a reason
    to re-verify - only real content changes are."""
    f = env.seed(signature_valid=True, hash_valid=True)
    fid = f.id

    tasks.scan_library_task(library_path=str(env.lib_dir))

    f = db.session.get(Files, fid)
    assert f.signature_valid is True and f.hash_valid is True  # untouched


def test_rescanning_twice_in_a_row_stays_stable(env):
    """Not just one extra scan - repeated scans of the same unchanged library must
    never accumulate resets or re-verifications."""
    f = env.seed(signature_valid=True, hash_valid=True)
    fid = f.id

    for _ in range(3):
        tasks.scan_library_task(library_path=str(env.lib_dir))

    f = db.session.get(Files, fid)
    assert f.signature_valid is True and f.hash_valid is True


def test_a_file_actually_replaced_while_ownfoil_was_off_gets_reverified(env):
    """The gap this closes: the live watcher never saw this change (ownfoil wasn't
    running when it happened), so only a Scan discovers it. Same size+mtime signal the
    watcher itself already uses - not a full re-hash of the library."""
    f = env.seed(signature_valid=True, hash_valid=True)
    fid, path = f.id, f.filepath
    with open(path, "wb") as fh:
        fh.write(b"COMPLETELY DIFFERENT PAYLOAD, LONGER")

    tasks.scan_library_task(library_path=str(env.lib_dir))

    f = db.session.get(Files, fid)
    assert f.signature_valid is None and f.hash_valid is None
    assert f.size == len(b"COMPLETELY DIFFERENT PAYLOAD, LONGER")
    assert f.identified is False  # re-identification was reset too, not just verification


def test_only_the_changed_file_is_touched_not_the_whole_library(env):
    """A scan finding one changed file must not blow away every other tracked file's
    verified state - only the one that actually changed on disk."""
    changed = env.seed("Changed.nsp", content=b"OLD", signature_valid=True, hash_valid=True)
    untouched = env.seed("Untouched.nsp", content=b"STAYS THE SAME",
                         signature_valid=True, hash_valid=True)
    changed_id, untouched_id = changed.id, untouched.id
    with open(changed.filepath, "wb") as fh:
        fh.write(b"NEW CONTENT HERE")

    tasks.scan_library_task(library_path=str(env.lib_dir))

    assert db.session.get(Files, changed_id).hash_valid is None
    assert db.session.get(Files, untouched_id).hash_valid is True


def test_a_missing_file_is_left_for_remove_missing_files_not_reset_here(env):
    """A file that's gone from disk right now isn't "changed" in the sense this check
    cares about - that's remove_missing_files_from_db's job (and it's guarded
    separately against a merely-offline library, see test_missing_files_guard.py)."""
    f = env.seed(signature_valid=True, hash_valid=True)
    fid, path = f.id, f.filepath
    os.remove(path)

    tasks.scan_library_task(library_path=str(env.lib_dir))

    f = db.session.get(Files, fid)
    assert f.signature_valid is True and f.hash_valid is True  # untouched by this pass

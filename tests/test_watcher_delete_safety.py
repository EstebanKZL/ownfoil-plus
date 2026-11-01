"""A disconnected disk (unplugged USB drive, dropped network share) reaches the file
watcher as a flood of 'deleted' / 'dir_deleted' events, and handle_file_deleted /
handle_dir_deleted used to delete the matching rows unconditionally - wiping a whole
library's identification and verification state (reported directly: everything had to
be re-scanned and re-verified). Real deletions - via the web UI or straight off the
disk - must still clean the registry; an offline library must not."""
import os
import shutil
import types

import pytest

import tasks
from app import create_app
from db import db, Files, Libraries


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
    monkeypatch.setattr(tasks, "enqueue_task", lambda *a, **k: None)

    def seed(name, subdir=None):
        folder = lib_dir / subdir if subdir else lib_dir
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(b"DATA")
        f = Files(filepath=str(path), library_id=library.id, folder=str(folder),
                  filename=name, extension="nsp", size=4, identified=True)
        db.session.add(f)
        db.session.commit()
        return f

    yield types.SimpleNamespace(lib_dir=lib_dir, seed=seed)
    ctx.pop()


def _count():
    return Files.query.count()


def test_a_real_file_deletion_still_removes_the_row(env):
    keep = env.seed("keep.nsp")
    gone = env.seed("gone.nsp")
    os.remove(gone.filepath)
    tasks.handle_file_deleted_task(gone.filepath)
    assert [f.filename for f in Files.query.all()] == ["keep.nsp"]
    assert os.path.exists(keep.filepath)


def test_a_real_folder_deletion_still_removes_its_rows(env):
    env.seed("a.nsp")
    env.seed("b.nsp", subdir="Folder")
    shutil.rmtree(env.lib_dir / "Folder")
    tasks.handle_dir_deleted_task(str(env.lib_dir / "Folder"))
    assert [f.filename for f in Files.query.all()] == ["a.nsp"]


def test_unplugged_disk_with_vanished_root_keeps_every_row(env):
    files = [env.seed(f"g{i}.nsp") for i in range(3)]
    paths = [f.filepath for f in files]
    shutil.rmtree(env.lib_dir)  # root gone, like an unmounted drive
    for p in paths:
        tasks.handle_file_deleted_task(p)
    tasks.handle_dir_deleted_task(str(env.lib_dir))
    assert _count() == 3


def test_unplugged_disk_with_empty_bind_mount_keeps_every_row(env):
    files = [env.seed(f"g{i}.nsp", subdir="sub") for i in range(3)]
    paths = [f.filepath for f in files]
    shutil.rmtree(env.lib_dir / "sub")  # root dir remains, but empty (docker bind mount)
    for p in paths:
        tasks.handle_file_deleted_task(p)
    tasks.handle_dir_deleted_task(str(env.lib_dir / "sub"))
    assert _count() == 3


def test_a_delete_event_for_a_file_that_still_exists_is_ignored(env):
    f = env.seed("still.nsp")
    tasks.handle_file_deleted_task(f.filepath)
    assert _count() == 1


def test_reconnecting_and_rescanning_finds_rows_untouched(env):
    f = env.seed("game.nsp")
    original = (f.id, f.identified)
    saved = env.lib_dir.with_name("saved")
    shutil.move(str(env.lib_dir), str(saved))  # disk unplugged
    tasks.handle_file_deleted_task(f.filepath)
    shutil.move(str(saved), str(env.lib_dir))  # plugged back in
    row = Files.query.one()
    assert (row.id, row.identified) == original

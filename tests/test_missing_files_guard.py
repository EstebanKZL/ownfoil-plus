"""remove_missing_files_from_db must not wipe a library's tracked files just because its
root is temporarily unreachable (drive unplugged, Docker bind mount gone empty). It should
still clean up individually-deleted files within libraries that are actually online."""
import os
import types

import pytest

from db import Apps, Files, Libraries, Titles, db, remove_missing_files_from_db

from app import create_app


@pytest.fixture
def env(tmp_path):
    """App + DB with two libraries on disk, and a helper to seed a file row."""
    app = create_app(f"sqlite:///{tmp_path/'test.db'}")
    lib_a_dir = tmp_path / "library_a"
    lib_b_dir = tmp_path / "library_b"
    lib_a_dir.mkdir()
    lib_b_dir.mkdir()
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    library_a = Libraries(path=str(lib_a_dir))
    library_b = Libraries(path=str(lib_b_dir))
    db.session.add_all([library_a, library_b])
    db.session.commit()

    def seed(library, name="Game.nsp", write=True):
        path = os.path.join(library.path, name)
        if write:
            with open(path, "wb") as fh:
                fh.write(b"RAWDATA")
        f = Files(filepath=path, library_id=library.id, folder=library.path,
                  filename=name, extension=name.rsplit(".", 1)[-1], size=7,
                  identified=True, hash_valid=True, signature_valid=True)
        db.session.add(f)
        db.session.commit()
        return f

    yield types.SimpleNamespace(
        app=app, library_a=library_a, library_b=library_b, seed=seed,
    )
    ctx.pop()


def test_offline_library_keeps_its_files(env):
    """Library A's directory is deleted outright (the 'real unmount' shape). Scanning
    library B, which is online, must not delete library A's rows."""
    file_a = env.seed(env.library_a)
    env.seed(env.library_b)

    os.remove(file_a.filepath)
    os.rmdir(env.library_a.path)  # simulate the drive disappearing

    remove_missing_files_from_db()

    assert Files.query.get(file_a.id) is not None
    # Verification state survives untouched, so a later scan won't re-verify it.
    assert Files.query.get(file_a.id).hash_valid is True


def test_empty_but_present_library_keeps_its_files(env):
    """Library A's directory still exists but is completely empty (the Docker bind-mount
    shape a host-side unmount commonly leaves behind). Same guard applies."""
    file_a = env.seed(env.library_a)
    env.seed(env.library_b)

    os.remove(file_a.filepath)  # the dir is still there, just empty now

    remove_missing_files_from_db()

    assert Files.query.get(file_a.id) is not None


def test_online_library_still_cleans_up_individually_deleted_files(env):
    """A library that is online and has other files present should still lose the row
    for a file that was genuinely deleted."""
    kept = env.seed(env.library_b, name="Kept.nsp")
    deleted = env.seed(env.library_b, name="Deleted.nsp")

    os.remove(deleted.filepath)

    remove_missing_files_from_db()

    assert Files.query.get(kept.id) is not None
    assert Files.query.get(deleted.id) is None


def test_removal_updates_app_ownership(env):
    """Cleaning up a genuinely deleted file still flips ownership on any app it carried."""
    kept = env.seed(env.library_b, name="Kept.nsp")
    deleted = env.seed(env.library_b, name="Deleted.nsp")

    title = Titles(title_id="0100000000000000")
    db.session.add(title)
    db.session.commit()
    app = Apps(title_id=title.id, app_id="0100000000000000", app_version="0",
               app_type="base", owned=True)
    app.files.append(deleted)
    db.session.add(app)
    db.session.commit()

    os.remove(deleted.filepath)

    remove_missing_files_from_db()

    db.session.refresh(app)
    assert app.owned is False
    assert Files.query.get(kept.id) is not None

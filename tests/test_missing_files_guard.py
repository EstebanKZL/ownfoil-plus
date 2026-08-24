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


# --- A library that still looks "online" (its root isn't empty) but most of its
# individually-tracked files fail their own existence check - the shape a flaky or
# partially-reconnected network mount (a Samba share dropping mid-listing) produces,
# distinct from the two "root itself is gone/empty" cases above. -------------------

def test_a_library_where_most_tracked_files_come_back_missing_at_once_is_left_alone(env):
    """752 files, and a network hiccup makes ~80% of their individual existence checks
    fail while the root directory itself still lists something (so it doesn't trip the
    offline guard above) - this must not be read as "the user deleted most of their
    library." All ten rows must survive, verification state included."""
    files = [env.seed(env.library_b, name=f"Game{i}.nsp") for i in range(10)]
    # One file stays on disk so the root isn't empty (doesn't trip _library_looks_offline).
    for f in files[1:]:
        os.remove(f.filepath)

    remove_missing_files_from_db()

    for f in files:
        row = Files.query.get(f.id)
        assert row is not None, f"{f.filename} should have survived - most of the " \
            "library looking missing at once should be treated as suspicious"
        assert row.hash_valid is True


def test_a_library_where_only_a_small_fraction_is_missing_still_cleans_up_normally(env):
    """The threshold is a *proportion*, not a hard count - the same library, but only
    a small minority of its files are gone, is exactly the ordinary "user deleted a
    couple of games" case and must still clean up as normal."""
    files = [env.seed(env.library_b, name=f"Game{i}.nsp") for i in range(10)]
    os.remove(files[0].filepath)  # only 1 of 10 (10%) - well under the threshold

    remove_missing_files_from_db()

    assert Files.query.get(files[0].id) is None
    for f in files[1:]:
        assert Files.query.get(f.id) is not None


def test_the_sanity_guard_is_per_library_not_global(env):
    """Library A looks like a flaky mount (most of it missing at once); library B has
    an ordinary handful of real deletions. B must still clean up correctly regardless
    of what's happening in A - the two are evaluated independently."""
    a_files = [env.seed(env.library_a, name=f"A{i}.nsp") for i in range(10)]
    for f in a_files[1:]:
        os.remove(f.filepath)  # 90% of A missing at once - suspicious

    b_kept = env.seed(env.library_b, name="Kept.nsp")
    b_deleted = env.seed(env.library_b, name="Deleted.nsp")
    os.remove(b_deleted.filepath)  # an ordinary single deletion in B

    remove_missing_files_from_db()

    for f in a_files:
        assert Files.query.get(f.id) is not None, "library A should be left untouched"
    assert Files.query.get(b_kept.id) is not None
    assert Files.query.get(b_deleted.id) is None, "library B should still clean up normally"

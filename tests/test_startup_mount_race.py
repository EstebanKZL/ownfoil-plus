"""Regression test for the exact bug reported: on container restart, process_library
enqueues at startup with zero wait for a network mount (Samba, in the report) to
finish reconnecting. Every file still needing organize/verify got walked into
_drive_file, which - before this fix - deleted its row outright the moment
os.path.exists() came back False, with no protection at all against "the mount just
isn't ready yet" being the actual reason. Already-verified files were never affected
either way, since they're not selected by process_library's file list in the first
place - which is exactly why the reported symptom was "verified files survive,
everything else vanishes and gets rediscovered as new by the next scan."
"""
import types

import pytest

import db as db_mod
import tasks
from app import create_app
from db import Files, Libraries, db, init_db
from worker import TaskWorker


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    # The library directory is deliberately never created here - this is the disk
    # itself being the thing that's not mounted yet, the shape a not-yet-reconnected
    # Samba share or a not-yet-attached USB drive both take.
    lib_dir = tmp_path / "games"
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))

    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    init_db(app)
    with app.app_context():
        library = Libraries(path=str(lib_dir))
        db.session.add(library)
        db.session.commit()

        def seed_tracked_but_unmounted(name, *, identified=True, organized=False):
            """A file the DB already tracks from before the restart - but its path
            lives under lib_dir, which doesn't exist right now (mount not back yet)."""
            path = lib_dir / name
            f = Files(filepath=str(path), library_id=library.id, folder=str(lib_dir),
                     filename=name, extension="nsp", size=7,
                     identified=identified, organized=organized)
            db.session.add(f)
            db.session.commit()
            return f

        yield types.SimpleNamespace(app=app, lib_dir=lib_dir, library=library,
                                    seed_tracked_but_unmounted=seed_tracked_but_unmounted)


def _settings():
    return {
        "library": {
            "management": {
                "compression": {"enabled": False},
                "verification": {"enabled": True, "depth": "signature"},
                "delete_older_updates": False,
                "organizer": {"enabled": True, "remove_empty_folders": False,
                             "clean_names": False, "windows_compatible": False,
                             "name_region": "", "name_language": "",
                             "templates": {"base": "{titleName}", "update": "{titleName}",
                                          "dlc": "{titleName}", "multi": "{titleName}"}},
            },
        },
        "worker": {"group_limits": {}},
    }


def _run_all_pending(app, max_steps=50):
    worker = TaskWorker(app, worker_id=1)
    for _ in range(max_steps):
        task_id = worker.claim_task()
        if task_id is None:
            return
        worker.execute_task(task_id)


def test_process_library_at_startup_does_not_wipe_unverified_files_when_the_mount_is_not_back_yet(env, monkeypatch):
    """Exactly the reported scenario: several files still need organizing (i.e. they
    were never fully verified before the restart), and the library's disk isn't
    mounted yet when process_library runs - all of them must survive, tracked state
    intact, ready for a later scan (once the mount is actually back) to pick up
    unchanged rather than starting over as brand new files."""
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings())

    unverified = [env.seed_tracked_but_unmounted(f"Unverified{i}.nsp")
                 for i in range(5)]

    with env.app.app_context():
        tasks.enqueue_task("process_library")
        _run_all_pending(env.app)

        for f in unverified:
            row = db.session.get(Files, f.id)
            assert row is not None, (
                f"{f.filename} should have survived - the mount not being back yet "
                "must not be treated as the file having been deleted"
            )
            assert row.organized is False  # untouched, not silently marked done either


def test_a_previously_verified_file_is_unaffected_either_way(env, monkeypatch):
    """The other half of the reported symptom: an already-organized/verified file is
    never selected by process_library's file list at all, mount back or not - so it
    was never actually at risk, which is exactly why it "survived" in the report
    while everything else vanished."""
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings())

    verified = env.seed_tracked_but_unmounted(
        "AlreadyDone.nsp", identified=True, organized=True)

    with env.app.app_context():
        tasks.enqueue_task("process_library")
        _run_all_pending(env.app)

        assert db.session.get(Files, verified.id) is not None

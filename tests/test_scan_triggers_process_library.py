"""A manual/scheduled library Scan only discovers files not yet tracked in the
database - it never re-examines files already there, even when one of them has pending
work (a settings change reset its `organized` flag, for instance). Finishing a scan
must also enqueue `process_library` so that pending work gets picked up, instead of
only surfacing on the next titledb update or container restart.
"""
import pytest

import db as db_mod
import tasks
from app import create_app
from db import Libraries, Task, db, init_db


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    lib_dir = tmp_path / "games"
    lib_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))

    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    init_db(app)
    with app.app_context():
        library = Libraries(path=str(lib_dir))
        db.session.add(library)
        db.session.commit()
        yield library


def _pending_task_names():
    return sorted(t.task_name for t in Task.query.filter_by(status="pending").all())


def test_finishing_a_scan_enqueues_process_library(env):
    tasks._scan_library_done(library_path=env.path)

    assert "process_library" in _pending_task_names()


def test_finishing_a_scan_still_enqueues_remove_missing_files_too(env):
    """The pre-existing cleanup pass must not be dropped by this change."""
    tasks._scan_library_done(library_path=env.path)

    assert "remove_missing_files" in _pending_task_names()


def test_process_library_is_deduped_across_multiple_libraries(env, monkeypatch):
    """Several libraries finishing their scans (the normal multi-library case) must not
    queue up several redundant process_library runs."""
    second = Libraries(path=str(env.path) + "-2")
    db.session.add(second)
    db.session.commit()

    tasks._scan_library_done(library_path=env.path)
    tasks._scan_library_done(library_path=second.path)

    process_library_tasks = [t for t in Task.query.all() if t.task_name == "process_library"]
    assert len(process_library_tasks) == 1

"""There's no separate "pause" button in ownfoil - the existing generic Cancel action
on any running task (the Tasks page already exposes this for every task, including
verify_library) already IS pause: cancelling a `waiting_for_children` parent deletes
its not-yet-started children and lets any currently-running one finish naturally,
never touching a file that's already been verified. Because `_needs_verify` only
selects files with no recorded verdict, simply re-running verify_library later (via
Scan, a settings save, a titledb update, or startup) resumes exactly where the
cancelled run left off - it re-checks nothing that already has an answer.

This test drives real Task rows through TaskWorker rather than mocking the queue, to
prove the actual continuation/cancellation machinery behaves this way end to end.
"""
import types

import pytest

import db as db_mod
import tasks
from app import create_app
from db import Files, Libraries, Task, db, init_db
from worker import TaskWorker


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

        def seed(name, size=7):
            path = lib_dir / name
            path.write_bytes(b"X" * size)
            f = Files(filepath=str(path), library_id=library.id, folder=str(lib_dir),
                     filename=name, extension=name.rsplit(".", 1)[-1], size=size,
                     identified=True, organized=True)
            db.session.add(f)
            db.session.commit()
            return f

        yield types.SimpleNamespace(app=app, lib_dir=lib_dir, library=library, seed=seed)


def _settings(verify=True):
    return {
        "library": {
            "management": {
                "compression": {"enabled": False},
                "verification": {"enabled": verify, "depth": "signature"},
                "delete_older_updates": False,
                "organizer": {"enabled": False, "remove_empty_folders": False,
                              "clean_names": False, "windows_compatible": False,
                              "name_region": "", "name_language": "",
                              "templates": {"base": "{titleName}", "update": "{titleName}",
                                            "dlc": "{titleName}", "multi": "{titleName}"}},
            },
        },
        "worker": {"group_limits": {}},
    }


def test_cancelling_verify_library_preserves_finished_verdicts_and_resuming_skips_them(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(verify=True))
    monkeypatch.setattr(tasks.titles_lib.Keys, "keys_loaded", True, raising=False)

    verify_calls = []

    def fake_verify_file(file_id, **kw):
        verify_calls.append(file_id)
        f = db.session.get(Files, file_id)
        f.signature_valid = True
        f.hash_valid = True
        f.verified_at = tasks.datetime.datetime.now()
        db.session.commit()

    monkeypatch.setitem(tasks.TASK_REGISTRY, "verify_file", fake_verify_file)

    files = [env.seed(f"Game{i}.nsp") for i in range(4)]

    with env.app.app_context():
        tasks.enqueue_task("verify_library")
        worker = TaskWorker(env.app, worker_id=1)

        # Drive the queue until a couple of files have actually finished verifying (not
        # just been dispatched), then "pause": cancel the verify_library parent while
        # it's still waiting on the rest.
        for _ in range(30):
            done_count = sum(1 for f in files if db.session.get(Files, f.id).hash_valid)
            if done_count >= 2:
                break
            task_id = worker.claim_task()
            assert task_id is not None, "queue ran dry before any file finished verifying"
            worker.execute_task(task_id)

        parent = Task.query.filter_by(task_name="verify_library").first()
        assert parent is not None and parent.status == "waiting_for_children"
        assert tasks.cancel_task(parent.id) is True

        # Nothing left runnable - the pause actually stopped new work, it didn't just
        # let everything finish anyway.
        assert Task.query.count() == 0

        verified_now = {f.id for f in files if db.session.get(Files, f.id).hash_valid}
        unverified_now = {f.id for f in files} - verified_now
        assert 0 < len(verified_now) < len(files), (
            "test setup problem: need a real partial run to prove pause matters")
        calls_at_pause = list(verify_calls)

        # "Resume": just run verify_library again, the same way Scan/startup/a
        # settings save already do automatically.
        tasks.enqueue_task("verify_library")
        for _ in range(20):
            task_id = worker.claim_task()
            if task_id is None:
                break
            worker.execute_task(task_id)

        # Every file ends up verified...
        for f in files:
            assert db.session.get(Files, f.id).hash_valid is True

        # ...but the ones already done before the pause were never asked to verify
        # again - resuming picked up only the remaining work.
        assert set(calls_at_pause).issubset(set(verify_calls))
        recalled = [fid for fid in calls_at_pause if verify_calls.count(fid) > 1]
        assert recalled == [], f"these files were re-verified after resuming: {recalled}"
        assert verified_now.isdisjoint(set(verify_calls[len(calls_at_pause):]))

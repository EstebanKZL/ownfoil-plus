"""End-to-end coverage for the organize-then-verify phase split: process_library
(organize phase) must fully settle - including its per-file identify/organize work -
before verify_library (the verify phase) starts, rather than the two running at the
same time across different files. Drives real Task rows through TaskWorker.execute_task
rather than mocking the queue, so this exercises the actual continuation chain
(`_process_library_organize_done`) that wires the two phases together.
"""
import os
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

        def seed(name, *, identified=True, organized=True, size=7):
            path = lib_dir / name
            path.write_bytes(b"X" * size)
            f = Files(filepath=str(path), library_id=library.id, folder=str(lib_dir),
                     filename=name, extension=name.rsplit(".", 1)[-1], size=size,
                     identified=identified, organized=organized)
            db.session.add(f)
            db.session.commit()
            return f

        yield types.SimpleNamespace(app=app, lib_dir=lib_dir, library=library, seed=seed)


def _settings(*, organizer_enabled, verify_enabled):
    return {
        "library": {
            "management": {
                "compression": {"enabled": False},
                "verification": {"enabled": verify_enabled, "depth": "signature"},
                "delete_older_updates": False,
                "organizer": {
                    "enabled": organizer_enabled, "remove_empty_folders": False,
                    "clean_names": False, "windows_compatible": False,
                    "name_region": "", "name_language": "",
                    "templates": {
                        "base": "{titleName}/{titleName} [{appId}][v{appVersion}]",
                        "update": "{titleName}/{titleName} [{appId}][v{appVersion}]",
                        "dlc": "{titleName}/{appName} [{appId}][v{appVersion}]",
                        "multi": "{titleName}/{titleName} [{titleId}]",
                    },
                },
            },
        },
        "worker": {"group_limits": {}},
    }


def _run_all_pending(app, max_steps=50):
    """Drive every pending/waiting task to completion with a single real worker,
    exactly the way one worker process would, one claim-and-execute at a time."""
    worker = TaskWorker(app, worker_id=1)
    for _ in range(max_steps):
        task_id = worker.claim_task()
        if task_id is None:
            if not Task.query.filter(Task.status.in_(["pending", "waiting_for_children"])).all():
                return
            raise AssertionError("Pending work exists but nothing claimable - stuck task?")
        worker.execute_task(task_id)


def test_organize_phase_fully_settles_before_verify_phase_starts(env, monkeypatch):
    """The concrete scenario the phase split exists for: a file that still needs
    identifying+organizing, alongside one that's already settled and only needs
    verifying. Verification doesn't itself require a file to be identified (signature
    checks work on the raw container either way), so both end up eligible for verify -
    the invariant to prove is *ordering*: every organize-phase identify attempt must
    have already happened before the first verify_file dispatch, not that one file gets
    excluded from verify."""
    monkeypatch.setattr(tasks, "get_settings",
                        lambda: _settings(organizer_enabled=True, verify_enabled=True))
    monkeypatch.setattr(tasks.titles_lib.Keys, "keys_loaded", True, raising=False)

    events = []

    def fake_identify(filepath):
        events.append(("identify", filepath))
        return None, False, None, "stubbed: no real container"

    def fake_verify_file(file_id, **kw):
        events.append(("verify", file_id))

    monkeypatch.setattr(tasks.titles_lib, "identify_file", fake_identify)
    monkeypatch.setattr(tasks, "organize_file", lambda *a, **k: True)
    monkeypatch.setitem(tasks.TASK_REGISTRY, "verify_file", fake_verify_file)

    needs_organize = env.seed("Unidentified.nsp", identified=False, organized=False)
    env.seed("Ready.nsp", identified=True, organized=True)

    with env.app.app_context():
        tasks.enqueue_task("process_library")
        _run_all_pending(env.app)

        identify_indices = [i for i, (kind, _) in enumerate(events) if kind == "identify"]
        verify_indices = [i for i, (kind, _) in enumerate(events) if kind == "verify"]
        assert identify_indices and verify_indices
        assert max(identify_indices) < min(verify_indices), (
            f"a verify happened before organizing settled: {events}")

        f = db.session.get(Files, needs_organize.id)
        assert f.identification_attempts >= 1   # phase 1 actually tried it, not skipped


def test_a_settled_library_runs_only_the_verify_phase(env, monkeypatch):
    """No organize-phase work at all (already organized, or organizer off) must still
    let the verify phase run - process_library completing with zero children is not
    the same as the whole pipeline being skipped."""
    monkeypatch.setattr(tasks, "get_settings",
                        lambda: _settings(organizer_enabled=False, verify_enabled=True))
    monkeypatch.setattr(tasks.titles_lib.Keys, "keys_loaded", True, raising=False)

    verify_order = []
    monkeypatch.setitem(tasks.TASK_REGISTRY, "verify_file",
                        lambda file_id, **kw: verify_order.append(file_id))

    f = env.seed("Ready.nsp", identified=True, organized=True)

    with env.app.app_context():
        tasks.enqueue_task("process_library")
        _run_all_pending(env.app)

        assert verify_order == [f.id]


def test_no_pending_work_at_all_leaves_nothing_running(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings",
                        lambda: _settings(organizer_enabled=False, verify_enabled=False))

    env.seed("Settled.nsp", identified=True, organized=True)

    with env.app.app_context():
        tasks.enqueue_task("process_library")
        _run_all_pending(env.app)

        assert Task.query.all() == []

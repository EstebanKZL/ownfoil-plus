"""Startup task cleanup with SQLite's foreign keys on (as the server runs).

`tasks.parent_id` points at `tasks.id` with no ON DELETE rule. The old cleanup bulk-
deleted every completed (and pending) row; a completed parent with a failed child made
the statement fail with "FOREIGN KEY constraint failed" and the server restart-looped.
"""
import types

import pytest

import db as db_mod
import tasks
import titledb
from app import create_app
from db import Task, db, init_db


@pytest.fixture
def queue(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    init_db(app)
    ctx = app.app_context()
    ctx.push()
    assert db.session.execute(db.text("PRAGMA foreign_keys")).scalar() == 1

    def add(status, parent=None, name="t"):
        t = Task(task_name=name, status=status, input_json="{}", input_hash=f"h{status}{id(object())}",
                 parent_id=parent.id if parent else None)
        db.session.add(t)
        db.session.commit()
        return types.SimpleNamespace(id=t.id)

    yield add
    db.session.remove()
    ctx.pop()


def _ids():
    db.session.expire_all()
    return {t.id: t.status for t in Task.query.all()}


def test_completed_tasks_without_children_go(queue):
    a, b = queue("completed"), queue("completed")
    tasks.cleanup_tasks()
    assert a.id not in _ids() and b.id not in _ids()


def test_a_completed_parent_and_completed_child_both_go(queue):
    parent = queue("completed")
    child = queue("completed", parent)
    tasks.cleanup_tasks()
    assert _ids() == {}
    assert child.id  # created


@pytest.mark.parametrize("child_status", ["failed", "pending"])
def test_a_completed_parent_with_an_unfinished_child_stays(queue, child_status):
    """The real case: task 6881 (failed) under 5166 (completed). Both stay; a pending
    child is marked failed (interrupted by the restart) rather than left to run."""
    parent = queue("completed")
    child = queue(child_status, parent)
    tasks.cleanup_tasks()
    left = _ids()
    assert left[parent.id] == "completed"
    assert left[child.id] == "failed"


def test_a_pending_task_on_its_own_goes(queue):
    alone = queue("pending")
    tasks.cleanup_tasks()
    assert alone.id not in _ids()


def test_a_pending_task_with_work_under_it_is_failed_not_deleted(queue):
    parent = queue("pending")
    child = queue("failed", parent)
    tasks.cleanup_tasks()
    left = _ids()
    assert left[parent.id] == "failed" and left[child.id] == "failed"


def test_a_chain_keeps_every_ancestor_of_unfinished_work(queue):
    grandparent = queue("completed")
    parent = queue("completed", grandparent)
    child = queue("failed", parent)
    other = queue("completed")
    tasks.cleanup_tasks()
    left = _ids()
    assert grandparent.id in left and parent.id in left and child.id in left
    assert other.id not in left


def test_a_chain_down_to_a_pending_task_keeps_its_ancestors(queue):
    grandparent = queue("completed")
    parent = queue("completed", grandparent)
    child = queue("pending", parent)
    tasks.cleanup_tasks()
    left = _ids()
    assert left[grandparent.id] == "completed" and left[parent.id] == "completed"
    assert left[child.id] == "failed"


def test_running_tasks_become_failed(queue):
    running = queue("running")
    tasks.cleanup_tasks()
    assert _ids()[running.id] == "failed"


def test_a_cleanup_that_fails_never_stops_the_start(queue, monkeypatch, caplog):
    queue("completed")

    def boom():
        raise RuntimeError("database is locked")
    monkeypatch.setattr(tasks, "_cleanup_tasks", boom)
    tasks.cleanup_tasks()  # must not raise
    assert "Startup task cleanup failed" in caplog.text


def test_finishing_a_parent_takes_its_whole_subtree(queue):
    """_try_complete_parent's delete: a failed child with children of its own used to
    fail the foreign key and leave the completed parent behind."""
    parent = queue("waiting_for_children")
    child = queue("failed", parent)
    queue("failed", child)
    queue("completed", parent)
    tasks._try_complete_parent(parent.id)
    assert _ids() == {}


def test_startup_runs_the_library_pass_after_the_titledb_update(monkeypatch):
    """Run alongside the titledb update, the library pass named files from a titles.db
    being rebuilt and the next pass renamed them back: it is enqueued after it now."""
    order = []
    monkeypatch.setattr(tasks, "enqueue_task", lambda name, *a, **k: order.append(name))
    monkeypatch.setattr(tasks, "update_titledb_task", lambda **k: order.append("update_titledb"))
    for name in ("reschedule_maintenance", "_cleanup_stale_uploads", "_repair_file_names", "scan_libraries_task"):
        monkeypatch.setattr(tasks, name, lambda *a, **k: None)
    tasks.startup_task()
    assert order.index("update_titledb") < order.index("process_library")

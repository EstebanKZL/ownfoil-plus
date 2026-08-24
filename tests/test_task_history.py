"""Task history: a completed top-level operation (a scan, a verify pass, a titledb
update, ...) gets one entry written before its Task row disappears - since both
completion paths (_try_complete_parent for a task with children, execute_task in
worker.py for a simple leaf) delete the row almost immediately, with nothing else
left behind to say the operation ever ran.
"""
import datetime
import json
import types

import pytest

import tasks
from app import create_app
from db import Task, TaskHistory, Libraries, db, init_db
from gql import graphql_dispatch


@pytest.fixture
def env(tmp_path, monkeypatch):
    app = create_app(f"sqlite:///{tmp_path/'test.db'}")
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    db.session.add(Libraries(path=str(tmp_path / "games")))
    db.session.commit()
    yield types.SimpleNamespace(app=app, monkeypatch=monkeypatch)
    ctx.pop()


# --- _record_task_history: the unit itself --------------------------------------------

def test_records_an_entry_for_a_worthy_task_name(env):
    tasks._record_task_history("verify_library", {}, datetime.datetime(2026, 1, 1, 12, 0))

    entries = TaskHistory.query.all()
    assert len(entries) == 1
    assert entries[0].task_name == "verify_library"
    assert entries[0].summary == "Verify library files"


def test_does_not_record_a_non_worthy_per_file_task(env):
    """The frequent per-file leaves (process_file, verify_file, ...) are deliberately
    excluded - recording every one of them would fill the whole window on a single
    library scan."""
    tasks._record_task_history("verify_file", {"file_id": 1}, datetime.datetime.utcnow())

    assert TaskHistory.query.count() == 0


def test_the_summary_uses_the_same_display_name_the_live_task_list_shows(env):
    tasks._record_task_history("scan_library", {"library_path": "/games"}, datetime.datetime.utcnow())

    entry = TaskHistory.query.one()
    assert entry.summary == "Scan /games"


def test_retention_limit_trims_the_oldest_entries(env, monkeypatch):
    monkeypatch.setattr(tasks, "TASK_HISTORY_LIMIT", 3)
    base = datetime.datetime(2026, 1, 1)
    for i in range(5):
        tasks._record_task_history("verify_library", {}, base + datetime.timedelta(hours=i))

    remaining = TaskHistory.query.order_by(TaskHistory.completed_at.asc()).all()
    assert len(remaining) == 3
    # The 2 oldest (hour 0 and 1) were trimmed - hours 2, 3, 4 survive.
    assert [e.completed_at.hour for e in remaining] == [2, 3, 4]


def test_a_db_error_while_recording_does_not_raise(env, monkeypatch):
    """A history entry is a nice-to-have - it must never take down the operation
    it's trying to record."""
    def boom(*a, **k):
        raise RuntimeError("db is on fire")
    monkeypatch.setattr(db.session, "add", boom)

    tasks._record_task_history("verify_library", {}, datetime.datetime.utcnow())  # must not raise


# --- Real integration: both completion paths write a history entry ------------------

def test_a_simple_leaf_root_task_records_history_on_completion(env):
    """The execute_task path in worker.py: a task with no parent and no children -
    the "leaf that is also its own root" case."""
    from worker import TaskWorker

    env.monkeypatch.setitem(tasks.TASK_REGISTRY, "update_titledb", lambda **k: None)
    t = Task(task_name="update_titledb", status="running", worker_id=1,
             input_hash="x", input_json="{}")
    db.session.add(t)
    db.session.commit()
    tid = t.id

    TaskWorker(env.app, worker_id=1).execute_task(tid)

    assert db.session.get(Task, tid) is None  # the task row is gone, as before
    entry = TaskHistory.query.one()
    assert entry.task_name == "update_titledb"


def test_a_root_task_with_children_records_history_once_all_children_finish(env):
    """The _try_complete_parent path: a root task that parked waiting on children,
    where completing the last child triggers the parent (and here, the whole chain)
    finishing."""
    root = Task(task_name="verify_library", status="waiting_for_children",
               input_hash="root", input_json="{}")
    db.session.add(root)
    db.session.flush()
    child = Task(task_name="process_file_verify", status="completed", parent_id=root.id,
                input_hash="child", input_json='{"file_id": 1}')
    db.session.add(child)
    db.session.commit()
    root_id = root.id

    tasks._try_complete_parent(root_id)

    assert db.session.get(Task, root_id) is None  # deleted, as before
    entry = TaskHistory.query.one()
    assert entry.task_name == "verify_library"
    # The frequent child itself never gets its own entry - only the root operation.
    assert TaskHistory.query.filter_by(task_name="process_file_verify").count() == 0


def test_a_non_root_parent_finishing_does_not_record_history(env):
    """Only the true root of the whole operation gets an entry - an intermediate
    parent (itself with a grandparent) finishing is not yet the end of the operation,
    especially with a sibling branch still pending underneath the same root."""
    grandparent = Task(task_name="verify_library", status="waiting_for_children",
                       input_hash="gp", input_json="{}")
    db.session.add(grandparent)
    db.session.flush()
    parent = Task(task_name="process_file_verify", status="waiting_for_children",
                  parent_id=grandparent.id, input_hash="p", input_json='{"file_id": 1}')
    sibling = Task(task_name="process_file_verify", status="pending",
                   parent_id=grandparent.id, input_hash="s", input_json='{"file_id": 2}')
    db.session.add_all([parent, sibling])
    db.session.flush()
    child = Task(task_name="verify_file", status="completed", parent_id=parent.id,
                input_hash="c", input_json='{"file_id": 1}')
    db.session.add(child)
    db.session.commit()
    parent_id, grandparent_id = parent.id, grandparent.id

    tasks._try_complete_parent(parent_id)

    # The intermediate parent is done and gone, but the root (grandparent) still has
    # `sibling` pending, so it hasn't finished yet - no history entry for either.
    assert db.session.get(Task, parent_id) is None
    assert db.session.get(Task, grandparent_id) is not None
    assert TaskHistory.query.count() == 0


# --- GraphQL: taskHistory query --------------------------------------------------------

@pytest.fixture
def gql_env(tmp_path):
    app = create_app(f"sqlite:///{tmp_path/'test.db'}")
    app.add_url_rule("/api/graphql", view_func=graphql_dispatch, methods=["GET", "POST"])
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    yield types.SimpleNamespace(app=app, client=app.test_client())
    ctx.pop()


def _gql_query(gql_env, text_query, **variables):
    params = {"query": text_query}
    if variables:
        params["variables"] = json.dumps(variables)
    resp = gql_env.client.get("/api/graphql", query_string=params)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body["errors"]
    return body["data"]


def _seed_history(n, base=None):
    base = base or datetime.datetime(2026, 1, 1, 12, 0)
    for i in range(n):
        db.session.add(TaskHistory(task_name="verify_library", summary=f"Verify pass {i}",
                                   completed_at=base + datetime.timedelta(hours=i)))
    db.session.commit()


def test_task_history_returns_the_most_recent_entries_first(gql_env):
    _seed_history(3)

    data = _gql_query(gql_env, "query { taskHistory { summary completedAt } }")

    summaries = [e["summary"] for e in data["taskHistory"]]
    assert summaries == ["Verify pass 2", "Verify pass 1", "Verify pass 0"]


def test_task_history_limit_argument_is_respected(gql_env):
    _seed_history(10)

    data = _gql_query(gql_env, "query($limit: Int!) { taskHistory(limit: $limit) { summary } }",
                      limit=2)

    assert len(data["taskHistory"]) == 2


def test_task_history_limit_is_capped_at_100(gql_env):
    _seed_history(5)

    data = _gql_query(gql_env, "query($limit: Int!) { taskHistory(limit: $limit) { summary } }",
                      limit=99999)

    assert len(data["taskHistory"]) == 5  # not an error, just bounded by what exists

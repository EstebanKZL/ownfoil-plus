"""A big library's queue: tasks enqueued and files inserted in batches, a lighter live
Tasks view, and no library pass when nothing changed."""
import json

import pytest

import tasks
import task_events
from app import create_app
from db import db, Files, Libraries, Task
from test_compression import _settings


@pytest.fixture
def env(tmp_path, monkeypatch):
    app = create_app(f"sqlite:///{tmp_path/'q.db'}")
    lib_dir = tmp_path / "games"
    lib_dir.mkdir()
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    lib = Libraries(path=str(lib_dir))
    db.session.add(lib)
    db.session.commit()
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings())
    yield lib, lib_dir
    tasks._current_task_id = None
    ctx.pop()


def _running(name):
    t = Task(task_name=name, status='running', completion_pct=0, input_json='{}', input_hash=name)
    db.session.add(t)
    db.session.commit()
    return t


def test_children_go_in_one_batch_and_are_not_doubled(env):
    parent = _running('process_library')
    assert tasks.create_child_tasks(parent.id, 'process_file_organize',
                                    [{'file_id': 1}, {'file_id': 2}, {'file_id': 1}]) == 2
    # Asked again (a second pass): what the parent already has is not added twice.
    assert tasks.create_child_tasks(parent.id, 'process_file_organize', [{'file_id': 2}, {'file_id': 3}]) == 1
    assert Task.query.filter_by(parent_id=parent.id).count() == 3


def test_a_scan_inserts_files_and_queues_their_tasks_in_batches(env, monkeypatch):
    lib, lib_dir = env
    for i in range(450):
        (lib_dir / f"Game {i} [01{i:010d}0000][v0].nsp").write_bytes(b"x")
    commits = []
    real = db.session.commit
    monkeypatch.setattr(db.session, "commit", lambda: (commits.append(1), real())[1])
    scan = _running('scan_library')
    tasks._current_task_id = scan.id
    tasks.scan_library_task(library_path=str(lib_dir))
    assert Files.query.count() == 450
    assert Task.query.filter_by(parent_id=scan.id, task_name='process_file').count() == 450
    assert len(commits) < 10      # 450 files: a few batch commits, not one each


def test_the_live_tasks_view_reads_less_and_slows_down_on_a_long_queue(env):
    assert task_events.MAX_TASKS == 1000
    for i in range(task_events.BUSY_ROWS + 5):
        db.session.add(Task(task_name='download_title_media', status='pending', completion_pct=0,
                            input_json=json.dumps({'title_id': str(i)}), input_hash=f'h{i}'))
    db.session.commit()
    task_events._tasks_state = {}
    assert task_events.tasks_delay() == task_events.realtime.POLL_INTERVAL
    task_events.tasks_poll()
    assert task_events.tasks_delay() == 1.0
    task_events._tasks_state = {}


def test_a_scan_that_finds_nothing_sets_off_no_library_pass(env, monkeypatch):
    lib, lib_dir = env
    queued = []
    monkeypatch.setattr(tasks, "enqueue_task", lambda name, *a, **k: queued.append(name) or (None, True))
    monkeypatch.setattr(tasks, "_library_has_pending_work", lambda: False)
    tasks._scan_library_done(library_path=str(lib_dir), found=False)
    assert 'process_library' not in queued
    queued.clear()
    tasks._scan_library_done(library_path=str(lib_dir), found=True)
    assert 'process_library' in queued


def test_under_a_scan_of_all_libraries_the_pass_runs_once_at_the_end(env, monkeypatch):
    lib, lib_dir = env
    queued = []
    monkeypatch.setattr(tasks, "enqueue_task", lambda name, *a, **k: queued.append(name) or (None, True))
    monkeypatch.setattr(tasks, "_library_has_pending_work", lambda: False)
    parent = Task(task_name='scan_libraries', status='waiting_for_children', completion_pct=0,
                  input_json='{}', input_hash='all')
    db.session.add(parent)
    db.session.commit()
    tasks._scan_library_done(library_path=str(lib_dir), found=True)
    assert 'process_library' not in queued           # left to the scan of all
    parent.status = 'completed'
    db.session.commit()
    tasks._scan_libraries_done()
    assert queued.count('process_library') == 1


def test_an_unchanged_titledb_sets_off_no_library_pass(env, monkeypatch):
    queued = []
    monkeypatch.setattr(tasks, "enqueue_task", lambda name, *a, **k: queued.append(name) or (None, True))
    monkeypatch.setattr(tasks, "update_scheduled_task", lambda *a, **k: None)
    monkeypatch.setattr(tasks.titledb, "update_titledb", lambda s: False)
    monkeypatch.setattr(tasks, "get_settings", lambda: {'scheduler': {}})
    tasks.update_titledb_task()
    assert 'process_library' not in queued and 'download_media' not in queued
    assert 'update_series' in queued

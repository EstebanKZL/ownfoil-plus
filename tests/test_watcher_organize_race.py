"""The file watcher and Organize's own moves.

The watcher queued "New file" / "Add" for files Organize itself was moving; by the time
they ran the file had moved again and the task failed with [Errno 2]. Two causes: a disk
that reports a move as a delete plus a separate create (network shares), whose delete
half used up the move's ignore mark so the create half was queued; and no check that a
path still exists when its task runs.
"""
from types import SimpleNamespace

import tasks
from db import IgnoredEvent, add_ignored_event, db, pop_ignored_event, pop_ignored_move_source


def _event(kind, src, dest=None, directory="/lib"):
    return SimpleNamespace(type=kind, src_path=src, dest_path=dest, directory=directory)


def test_a_move_seen_as_delete_and_create_queues_nothing(shop_app, monkeypatch):
    import app as app_mod
    queued = []
    monkeypatch.setattr(app_mod.tasks_mod, "enqueue_task", lambda name, data=None, **k: queued.append(name))
    with shop_app.app.app_context():
        add_ignored_event("/lib/old/game.nsp", "/lib/New/Game.nsp")   # what Organize writes
    app_mod.on_library_change([_event("deleted", "/lib/old/game.nsp")])
    app_mod.on_library_change([_event("created", "/lib/New/Game.nsp")])
    assert queued == []
    with shop_app.app.app_context():
        assert IgnoredEvent.query.count() == 0     # no mark left behind


def test_a_real_move_still_uses_its_mark(shop_app):
    with shop_app.app.app_context():
        add_ignored_event("/lib/a.nsp", "/lib/b.nsp")
        assert pop_ignored_move_source("/lib/other.nsp") is None
        assert pop_ignored_event(src_path="/lib/a.nsp", dest_path="/lib/b.nsp") is True


def test_a_file_gone_before_its_task_runs_is_skipped_not_failed(shop_app, monkeypatch, tmp_path, caplog):
    queued = []
    monkeypatch.setattr(tasks, "enqueue_task", lambda name, data=None, **k: queued.append(name))
    missing = str(tmp_path / "moved-again.nsp")
    with shop_app.app.app_context():
        tasks.handle_file_added_task(str(tmp_path), missing)          # must not raise
        tasks.add_file_task(str(shop_app.library_root), missing)      # must not raise
        tasks.handle_file_moved_task(str(tmp_path), "/x/old.nsp", missing)
    assert queued == []
    assert "is no longer there" in caplog.text

"""Task queue model, registry, and helpers."""
import hashlib
import json
import datetime
import logging
import os
import time
from collections import namedtuple
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
import titles as titles_lib
import titledb
from titledb import images as images_lib
from containers import compression
from containers import verification as verification_lib
from constants import COMPRESS_EXT, DECOMPRESS_EXT
from db import (
    db, Task, TaskHistory, Files, Apps, Libraries, get_library_id, get_library_path, get_library_file_paths,
    get_libraries, add_title_id_in_db, get_title_id_db_id, add_file_to_app,
    file_exists_in_db, update_file_path, delete_file_by_filepath,
    delete_files_under_dir, add_ignored_event, pop_ignored_event,
    add_temp_file, remove_temp_file, claim_temp_file, get_temp_file_paths, purge_temp_files,
    set_library_scan_time, remove_missing_files_from_db,
    remove_file_from_apps, reset_file_identification, reset_file_verification, create_file,
    verification_status, _library_looks_offline,
)
from settings import get_settings
from utils import interval_string_to_timedelta, delete_empty_folders, human_size
from library import (
    add_missing_apps_for_title, update_title_flags,
    add_missing_apps_to_db, update_titles, organize_file,
    remove_outdated_update_files,
    duplicate_file_groups, automatic_duplicate_winner, resolve_duplicate_files,
    duplicate_winner_preferring_largest, duplicate_winner_with_preferences,
)

logger = logging.getLogger('main')

# How long to wait before retrying a titledb update that failed to reach the release
TITLEDB_RETRY_DELAY = datetime.timedelta(hours=1)

# --- Task Registry ---
TASK_REGISTRY = {}
TASK_CONTINUATIONS = {}
TASK_CLEANUP = {}
TASK_GROUPS = {}  # task_name -> concurrency-group name


def register_task(name, group=None):
    """Register a callable as a named task. `group` assigns it to a concurrency group whose
    parallelism is capped by worker.group_limits."""
    def decorator(func):
        TASK_REGISTRY[name] = func
        if group:
            TASK_GROUPS[name] = group
        return func
    return decorator


def blocked_task_names(running_task_names):
    """Task names that must not be claimed right now because their concurrency group is already
    at its configured limit, given the task_names currently running."""
    limits = get_settings().get('worker', {}).get('group_limits', {})
    if not limits:
        return set()
    running_per_group = {}
    for name in running_task_names:
        group = TASK_GROUPS.get(name)
        if group is not None:
            running_per_group[group] = running_per_group.get(group, 0) + 1
    full = {g for g, limit in limits.items() if running_per_group.get(g, 0) >= limit}
    return {name for name, group in TASK_GROUPS.items() if group in full}


def register_continuation(task_name):
    """Register a function to call when all children of a parent task complete."""
    def decorator(func):
        TASK_CONTINUATIONS[task_name] = func
        return func
    return decorator


def register_cleanup(task_name):
    """Register a function to call when a running task is cancelled.

    Receives the task's input_data as kwargs. Should be idempotent — the task
    may have been killed at any point, so any intermediate state (temp files,
    partial output) should be removed if present and ignored otherwise.
    """
    def decorator(func):
        TASK_CLEANUP[task_name] = func
        return func
    return decorator


def get_registered_task(name):
    return TASK_REGISTRY.get(name)


# --- Display names ---
def register_display(task_name):
    """Register a function building a task's human-readable label from its input kwargs."""
    def decorator(func):
        TASK_DISPLAY[task_name] = func
        return func
    return decorator


def _file_label(file_id=None, **kwargs):
    """Basename for a file task.

    A caller listing many tasks resolves the path in its own query and passes it in -
    including as None for a file that is gone, which is why the key being *present*
    is what suppresses the lookup here. Only the enqueue path, one task at a time,
    arrives without it.
    """
    if 'filepath' in kwargs:
        filepath = kwargs['filepath']
    else:
        file_obj = db.session.get(Files, file_id)
        filepath = file_obj.filepath if file_obj else None
    return os.path.basename(filepath) if filepath else f'file #{file_id}'


TASK_DISPLAY = {
    'startup': lambda **kw: 'Startup',
    'update_titledb': lambda **kw: 'Update TitleDB',
    'cache_titledb_images': lambda **kw: 'Cache title artwork',
    'resolve_duplicate_files': lambda **kw: 'Resolve duplicate files',
    'scan_libraries': lambda **kw: 'Scan all libraries',
    'scan_library': lambda library_path, **kw: f'Scan {library_path}',
    'add_file': lambda filepath, **kw: f'Add {os.path.basename(filepath)}',
    'process_file': lambda **kw: f'Process {_file_label(**kw)}',
    'process_file_organize': lambda **kw: f'Organize {_file_label(**kw)}',
    'process_file_verify': lambda **kw: f'Check {_file_label(**kw)}',
    'process_library': lambda **kw: 'Organize library files',
    'verify_library': lambda **kw: 'Verify library files',
    'library_maintenance': lambda library_path=None, **kw: (
        f'Maintain {library_path}' if library_path else 'Library maintenance'),
    'add_missing_apps_for_title': lambda title_id, **kw: f'Add missing content for {title_id}',
    'update_titles_for_title': lambda title_id, **kw: f'Update title {title_id}',
    'remove_outdated_updates': lambda **kw: 'Remove outdated updates',
    'verify_file': lambda **kw: f'Verify {_file_label(**kw)}',
    'compress_file': lambda **kw: f'Compress {_file_label(**kw)}',
    'decompress_file': lambda **kw: f'Decompress {_file_label(**kw)}',
    'add_missing_apps': lambda **kw: 'Add missing content',
    'remove_missing_files': lambda **kw: 'Remove missing files',
    'update_titles': lambda **kw: 'Update titles',
    'remove_library': lambda library_path, **kw: f'Remove library {library_path}',
    'handle_file_added': lambda filepath, **kw: f'New file {os.path.basename(filepath)}',
    'handle_file_moved': lambda src_path, dest_path, **kw: (
        f'Moved {os.path.basename(src_path)} to {os.path.basename(dest_path)}'),
    'handle_file_deleted': lambda filepath, **kw: f'Deleted {os.path.basename(filepath)}',
    'handle_dir_deleted': lambda dirpath, **kw: f'Deleted folder {os.path.basename(dirpath)}',
}


def task_display_name(task_name, input_data):
    """Human-readable label for a task, falling back to the humanised task name.

    input_json is persisted data that can outlive a change to a task's arguments, so a
    label that no longer builds must never break enqueueing, the worker loop or the UI.
    """
    build = TASK_DISPLAY.get(task_name)
    if build:
        try:
            return build(**(input_data or {}))
        except Exception as e:
            logger.debug(f"Could not build display name for '{task_name}': {e}")
    return task_name.replace('_', ' ').capitalize()


# How many completed operations to keep - a "what happened recently" log, not a full
# audit trail, so this stays a small bounded window rather than growing forever.
TASK_HISTORY_LIMIT = 100

# Root operations worth a history entry once they finish - the frequent per-file leaves
# (process_file, verify_file, ...) are deliberately left out, or every scan of a large
# library would fill the whole window with entries nobody would scroll through.
_TASK_HISTORY_WORTHY = {
    'scan_library', 'process_library', 'verify_library', 'library_maintenance',
    'update_titledb', 'resolve_duplicate_files', 'cache_titledb_images',
}


def _record_task_history(task_name, input_data, completed_at):
    """Write one history entry for a just-finished root operation, then trim the
    table back down to TASK_HISTORY_LIMIT rows. Called from both places a root task
    can finish - see _try_complete_parent and worker.py's execute_task."""
    if task_name not in _TASK_HISTORY_WORTHY:
        return
    try:
        db.session.add(TaskHistory(
            task_name=task_name,
            summary=task_display_name(task_name, input_data),
            completed_at=completed_at,
        ))
        db.session.commit()
        excess = TaskHistory.query.count() - TASK_HISTORY_LIMIT
        if excess > 0:
            stale_ids = [row.id for row in TaskHistory.query
                        .order_by(TaskHistory.completed_at.asc()).limit(excess)]
            TaskHistory.query.filter(TaskHistory.id.in_(stale_ids)).delete(synchronize_session=False)
            db.session.commit()
    except Exception as e:
        # A history entry is a nice-to-have, never worth failing the operation it's
        # recording over.
        logger.warning(f"Could not record task history for '{task_name}': {e}")
        db.session.rollback()


# --- Progress ---
_current_task_id = None


def _task_progress(task_id):
    """Return a callback that writes live percent to a task row, or None outside a task."""
    if task_id is None:
        return None
    engine = db.engine
    logged = [-1]

    def report(pct):
        connection = engine.raw_connection()
        try:
            cursor = connection.cursor()
            cursor.execute("UPDATE tasks SET completion_pct = ? WHERE id = ? AND status = 'running'",
                           (pct, task_id))
            connection.commit()
        finally:
            connection.close()
        if pct // 5 != logged[0]:
            logged[0] = pct // 5
            logger.debug(f"Task {task_id} progress: {pct}%")

    return report

# --- Child task helpers ---
def create_child_task(parent_id, task_name, input_data=None):
    """Create a child task, deduped against existing active children of the same parent."""
    if task_name not in TASK_REGISTRY:
        raise ValueError(f"Unknown task: {task_name}")
    input_data = input_data or {}
    input_json = json.dumps(input_data, sort_keys=True)
    input_hash = compute_input_hash(input_data)
    now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    connection = db.engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT id FROM tasks WHERE parent_id = ? AND task_name = ? AND input_hash = ? "
            "AND status IN ('pending', 'running', 'waiting_for_children', 'completed') LIMIT 1",
            (parent_id, task_name, input_hash)
        )
        row = cursor.fetchone()
        if row:
            connection.commit()
            return row[0]
        cursor.execute(
            "INSERT INTO tasks (parent_id, task_name, status, completion_pct, input_json, input_hash, created_at) "
            "VALUES (?, ?, 'pending', 0, ?, ?, ?)",
            (parent_id, task_name, input_json, input_hash, now)
        )
        child_id = cursor.lastrowid
        # logger.debug(f"Enqueued task child '{task_name}' (id={child_id}) of parent_id={parent_id}")
        connection.commit()
        return child_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def enqueue_or_child(task_name, input_data=None):
    """Create as child of the running task, or top-level if called outside a task."""
    if _current_task_id is not None:
        return create_child_task(_current_task_id, task_name, input_data)
    return enqueue_task(task_name, input_data)[0].id


def set_waiting_for_children():
    """Mark the current task as waiting for its children to complete."""
    task = db.session.get(Task, _current_task_id)
    task.status = 'waiting_for_children'
    task.worker_id = None
    db.session.commit()


def on_task_completed(task_id, parent_id):
    """Called by the worker after any task completes. Updates parent progress and checks for completion."""
    if not parent_id:
        return
    _try_complete_parent(parent_id)


def _try_complete_parent(parent_id):
    """Atomically update parent progress and complete if all children are done."""
    connection = db.engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute("SELECT status, task_name, input_json, parent_id FROM tasks WHERE id = ?", (parent_id,))
        row = cursor.fetchone()
        if not row or row[0] != 'waiting_for_children':
            connection.commit()
            return
        grandparent_id = row[3]

        # Count children atomically under the lock
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE parent_id = ?", (parent_id,))
        total = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM tasks WHERE parent_id = ? AND status IN ('completed', 'failed')",
            (parent_id,)
        )
        done = cursor.fetchone()[0]
        pct = int(done * 100 / total) if total else 0

        if done < total:
            cursor.execute("UPDATE tasks SET completion_pct = ? WHERE id = ?", (pct, parent_id))
            connection.commit()
            return

        # All children done — mark parent complete
        now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "UPDATE tasks SET status = 'completed', completion_pct = 100, exit_code = 0, completed_at = ? WHERE id = ?",
            (now, parent_id)
        )
        connection.commit()

        # Run continuation outside the transaction
        task_name = row[1]
        continuation = TASK_CONTINUATIONS.get(task_name)
        if continuation:
            input_data = json.loads(row[2])
            continuation(**input_data)

        # No grandparent means this was the root of the whole operation - worth a
        # history entry (see _record_task_history) before its row disappears below.
        if grandparent_id is None:
            _record_task_history(task_name, json.loads(row[2]), datetime.datetime.utcnow())

        # Delete parent and its children
        Task.query.filter_by(parent_id=parent_id).delete()
        Task.query.filter_by(id=parent_id).delete()
        db.session.commit()

        # Propagate completion up the chain
        if grandparent_id:
            _try_complete_parent(grandparent_id)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


# --- Cancellation ---

def _cancel_atomic(task_id, removable=('pending', 'running', 'waiting_for_children')):
    """Delete the task and any pending descendants under one transaction.
    Running descendants are orphaned (parent_id=NULL) so they finish naturally
    and self-delete on completion. Waiting descendants are recursed into.
    Failed descendants are deleted outright, same as pending ones - a failed task
    has nothing further running under it that could need orphaning.

    `removable` is which statuses may be taken out, so cancelling (live work) and
    dismissing (a failed row) share one transaction and one set of descendant rules.
    """
    connection = db.engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT status, task_name, input_json, parent_id, worker_id FROM tasks WHERE id = ?",
            (task_id,)
        )
        row = cursor.fetchone()
        if not row:
            connection.commit()
            return False, None, None, None, None
        status, task_name, input_json, parent_id, worker_id = row
        if status not in removable:
            connection.commit()
            return False, None, None, None, None

        running_worker_id = worker_id if status == 'running' else None
        cancelled_task_name = task_name if status == 'running' else None
        cancelled_input_json = input_json if status == 'running' else None

        def _walk(pid):
            cursor.execute("SELECT id, status FROM tasks WHERE parent_id = ?", (pid,))
            for child_id, child_status in cursor.fetchall():
                if child_status in ('pending', 'failed'):
                    _walk(child_id)  # a failed/pending row can itself have descendants left behind
                    cursor.execute("DELETE FROM tasks WHERE id = ?", (child_id,))
                elif child_status == 'running':
                    cursor.execute("UPDATE tasks SET parent_id = NULL WHERE id = ?", (child_id,))
                elif child_status == 'waiting_for_children':
                    _walk(child_id)
                    cursor.execute("DELETE FROM tasks WHERE id = ?", (child_id,))

        # Not just 'waiting_for_children': a task dismissed while 'failed' (the only
        # other case reaching here, via dismiss_task/purge_failed_tasks) can equally
        # have its own failed/pending descendants still sitting underneath it - e.g. a
        # "Scan" task interrupted mid-run leaves both itself and its still-pending or
        # already-failed "Process <file>" children marked failed by the same
        # crash-recovery pass, and deleting the parent first would otherwise violate
        # the parent_id foreign key those children still hold.
        if status in ('waiting_for_children', 'failed'):
            _walk(task_id)

        cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        connection.commit()
        return True, parent_id, running_worker_id, cancelled_task_name, cancelled_input_json
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def cancel_task(task_id):
    """Cancel a task. Returns True if cancelled, False if not found or already terminal.

    - pending: deleted.
    - running: worker is restarted (mid-task termination), cleanup hook runs.
    - waiting_for_children: pending descendants deleted, running descendants
      orphaned (allowed to finish), parent deleted.
    """
    found, parent_id, worker_id, task_name, input_json = _cancel_atomic(task_id)
    if not found:
        return False

    if worker_id is not None:
        import app as app_mod
        if app_mod.pool is not None:
            app_mod.pool.restart_worker(worker_id)

    if task_name is not None:
        _run_cleanup_hook(task_name, input_json)

    if parent_id:
        _try_complete_parent(parent_id)
    return True


def dismiss_task(task_id):
    """Remove a failed task. Returns True if a row was removed, False otherwise.

    Failed tasks are kept on purpose so a failure is not lost between page loads, which
    makes this the only way to clear one. Nothing is running by definition, so unlike
    cancel there is no worker to restart and no cleanup hook to run - the failure path
    in the worker already ran it.
    """
    found, parent_id, _worker_id, _task_name, _input_json = _cancel_atomic(
        task_id, removable=('failed',))
    if not found:
        return False
    if parent_id:
        _try_complete_parent(parent_id)
    return True


def purge_failed_tasks():
    """Remove every failed task. Returns how many were removed."""
    connection = db.engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM tasks WHERE status = 'failed'")
        task_ids = [r[0] for r in cursor.fetchall()]
    finally:
        connection.close()
    # One at a time rather than a bulk DELETE: each has descendants to unpick and a
    # parent that may now be able to complete, which dismiss_task already handles.
    return sum(1 for task_id in task_ids if dismiss_task(task_id))


def _run_cleanup_hook(task_name, input_json):
    """Run a task's registered @register_cleanup hook (idempotent) if it has one."""
    cleanup = TASK_CLEANUP.get(task_name)
    if not cleanup:
        return
    input_data = json.loads(input_json) if input_json else {}
    try:
        cleanup(**input_data)
    except Exception as e:
        logger.error(f"Cleanup hook for task '{task_name}' failed: {e}")


def reap_worker_task(worker_id):
    """Fail and clean up the task a worker was running when it was stopped mid-task."""
    task = Task.query.filter_by(status='running', worker_id=worker_id).first()
    if task is None:
        return
    task_name, input_json, parent_id = task.task_name, task.input_json, task.parent_id
    task.status = 'failed'
    task.error_message = 'Interrupted by worker stop'
    task.exit_code = 1
    task.completed_at = datetime.datetime.utcnow()
    db.session.commit()
    logger.info(f"Reaped task {task.id} ({task_name}) from stopped worker {worker_id}")
    _run_cleanup_hook(task_name, input_json)
    if parent_id:
        _try_complete_parent(parent_id)


# --- Startup cleanup ---

def cleanup_tasks():
    """Startup cleanup: clear the pending queue and fail interrupted tasks."""
    # Remove completed tasks
    Task.query.filter_by(status='completed').delete()

    # Clear the entire pending queue
    Task.query.filter_by(status='pending').delete()

    # Mark running/waiting tasks as failed — they can't survive a restart
    stale = Task.query.filter(Task.status.in_(['running', 'waiting_for_children'])).all()
    for task in stale:
        task.status = 'failed'
        task.error_message = 'Interrupted by application restart'
        task.exit_code = 1
        task.completed_at = datetime.datetime.utcnow()
        logger.info(f"Reset stale task {task.id} ({task.task_name})")

    db.session.commit()

    # Sweep leftover output from any (de)compression interrupted by the restart.
    purge_temp_files()


# --- Helpers ---

def compute_input_hash(input_data):
    canonical = json.dumps(input_data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def enqueue_task(task_name, input_data=None, run_after=None):
    """Enqueue a task. Returns (task, created) — created is False if a duplicate exists."""
    if task_name not in TASK_REGISTRY:
        raise ValueError(f"Unknown task: {task_name}")

    input_data = input_data or {}
    input_hash = compute_input_hash(input_data)
    input_json = json.dumps(input_data, sort_keys=True)

    # Scheduled tasks only dedup against pending; immediate tasks dedup against running too
    if run_after:
        dedup_statuses = "('pending', 'waiting_for_children')"
    else:
        dedup_statuses = "('pending', 'running', 'waiting_for_children')"

    connection = db.engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            f"SELECT id FROM tasks WHERE task_name = ? AND input_hash = ? AND status IN {dedup_statuses}",
            (task_name, input_hash)
        )
        existing = cursor.fetchone()

        if existing:
            connection.commit()
            task = db.session.get(Task, existing[0])
            return task, False

        now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        run_after_str = run_after.strftime('%Y-%m-%d %H:%M:%S') if run_after else None
        cursor.execute(
            "INSERT INTO tasks (task_name, status, completion_pct, input_json, input_hash, run_after, created_at) "
            "VALUES (?, 'pending', 0, ?, ?, ?, ?)",
            (task_name, input_json, input_hash, run_after_str, now)
        )
        new_id = cursor.lastrowid
        connection.commit()

        if run_after:
            local_run_after = run_after + (datetime.datetime.now() - datetime.datetime.utcnow())
            schedule_info = f", run_after={local_run_after.strftime('%Y-%m-%d %H:%M:%S')}"
        else:
            schedule_info = ""
        logger.debug(f"Enqueued task '{task_display_name(task_name, input_data)}' "
                     f"(id={new_id}{schedule_info})")
        task = db.session.get(Task, new_id)
        return task, True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def update_scheduled_task(task_name, run_after):
    """Update run_after on a pending scheduled task, delete if None, or create if missing."""
    connection = db.engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        if run_after is None:
            cursor.execute(
                "DELETE FROM tasks WHERE task_name = ? AND status = 'pending' AND run_after IS NOT NULL",
                (task_name,)
            )
            logger.debug(f"Deleted scheduled task '{task_name}' (disabled)")
        else:
            cursor.execute(
                "UPDATE tasks SET run_after = ? WHERE task_name = ? AND status = 'pending' AND run_after IS NOT NULL",
                (run_after.strftime('%Y-%m-%d %H:%M:%S'), task_name)
            )
            if cursor.rowcount == 0:
                # No existing scheduled task — create one
                now = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                input_hash = compute_input_hash({})
                cursor.execute(
                    "INSERT INTO tasks (task_name, status, completion_pct, input_json, input_hash, run_after, created_at) "
                    "VALUES (?, 'pending', 0, '{}', ?, ?, ?)",
                    (task_name, input_hash, run_after.strftime('%Y-%m-%d %H:%M:%S'), now)
                )
                local_ra = run_after + (datetime.datetime.now() - datetime.datetime.utcnow())
                logger.debug(f"Created scheduled task '{task_name}' run_after={local_ra.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                local_ra = run_after + (datetime.datetime.now() - datetime.datetime.utcnow())
                # logger.debug(f"Updated scheduled task '{task_name}' run_after={local_ra.strftime('%Y-%m-%d %H:%M:%S')}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_task(task_id):
    return db.session.get(Task, task_id)



@register_task('startup')
def startup_task(**kwargs):
    """Startup task: resume interrupted per-file work, then kick off the titledb update."""
    # Enqueued here rather than only from update_titledb_task, whose network fetch can fail:
    # recovery of an interrupted pipeline must not wait for the next scheduled titledb run.
    enqueue_task('process_library')
    enqueue_task('cache_titledb_images')
    try:
        update_titledb_task()
    except Exception:
        # A retry is already scheduled; scanning must not be held hostage to the network
        logger.exception('titledb update failed at startup')
    scan_libraries_task()

# --- Periodic tasks ---
@register_task('update_titledb')
def update_titledb_task(**kwargs):
    settings = get_settings()
    try:
        titledb.update_titledb(settings)
        enqueue_task('process_library')
        add_missing_apps_to_db()
        update_titles()
        enqueue_task('cache_titledb_images')
    except Exception:
        # Without this the chain simply stops: nothing re-enqueues a failed task, so a single
        # network blip would leave titledb frozen until the next restart.
        update_scheduled_task('update_titledb', datetime.datetime.utcnow() + TITLEDB_RETRY_DELAY)
        raise
    # Re-enqueue for next scheduled run
    interval_str = settings.get('scheduler', {}).get('titledb_update_interval', '12h')
    delta = interval_string_to_timedelta(interval_str)
    if delta:
        update_scheduled_task('update_titledb', datetime.datetime.utcnow() + delta)


@register_task('cache_titledb_images')
def cache_titledb_images_task(**kwargs):
    """Download banner/icon artwork for every title (and DLC) the library page can
    currently show into a local cache - see titledb/images.py - so those images keep
    working even if the remote host titledb points them at is unreachable. Runs after
    every titledb update and at startup; skips whatever is already cached, so a normal
    run only fetches what's actually new.

    A short pause follows each real download (not a cache hit) - a first run against a
    large library can mean hundreds of requests to the same third-party image host in
    quick succession, which is the kind of burst that gets an IP rate-limited or
    blocked. Spacing them out costs a fresh library a few extra minutes once, in
    exchange for not hammering someone else's server."""
    if not get_settings().get('titles', {}).get('cache_images', True):
        return
    title_ids = images_lib.titles_needing_images()
    cached = attempted = 0
    for title_id in title_ids:
        info = titles_lib.get_game_info(title_id)
        if not info:
            continue
        for kind, url in (('banner', info.get('bannerUrl')), ('icon', info.get('iconUrl'))):
            if not url or not url.startswith('http'):
                continue
            attempted += 1
            already_cached = images_lib.image_cache_path(title_id, kind) is not None
            if images_lib.cache_image(title_id, kind, url):
                cached += 1
            if not already_cached:
                time.sleep(images_lib.DOWNLOAD_DELAY)
    logger.info(f'Cached {cached}/{attempted} titledb image(s) for {len(title_ids)} title(s).')


# --- Scan pipeline ---
@register_task('scan_libraries')
def scan_libraries_task(**kwargs):
    """Scan all library paths for new files."""
    libraries = get_libraries()
    if not libraries:
        logger.info('No libraries to scan.')
        return
    for lib in libraries:
        enqueue_or_child('scan_library', {'library_path': lib.path})
    set_waiting_for_children()

@register_task('scan_library')
def scan_library_task(library_path, **kwargs):
    """Scan a library path: discover new files, and re-check already-tracked files
    for on-disk drift (content replaced while the live watcher wasn't running - e.g.
    ownfoil was stopped, or a network mount whose polling interval hasn't caught up
    yet). A file whose size and mtime match what's on record is left completely
    alone - re-running Scan is never by itself a reason to re-verify anything; only an
    actual change on disk is."""
    library_id = get_library_id(library_path)
    if not os.path.isdir(library_path):
        logger.warning(f'Library path {library_path} does not exist.')
        return

    logger.info(f'Scanning library path {library_path} ...')
    _, files = titles_lib.getDirsAndFiles(library_path)
    on_disk = set(files)
    temp_paths = get_temp_file_paths()
    tracked = {f.filepath: f for f in Files.query.filter_by(library_id=library_id).all()}
    new_files = [f for f in files if f not in tracked and f not in temp_paths]

    to_process = []
    for fp in new_files:
        new_file = _insert_file(library_path, library_id, fp)
        if new_file is not None:
            to_process.append(new_file.id)

    changed = 0
    for filepath, file in tracked.items():
        if filepath in temp_paths or filepath not in on_disk:
            continue  # missing right now is remove_missing_files' job, not this one's
        if _reconcile_existing_file(file, filepath):
            to_process.append(file.id)
            changed += 1
    if changed:
        logger.info(f'{changed} tracked file(s) changed on disk in {library_path}.')

    if not to_process:
        logger.info(f'No new or changed files found in {library_path}.')
        _scan_library_done(library_path=library_path)
        return

    for file_id in to_process:
        enqueue_or_child('process_file', {'file_id': file_id})
    set_waiting_for_children()


@register_continuation('scan_library')
def _scan_library_done(library_path, **kwargs):
    set_library_scan_time(get_library_id(library_path))
    enqueue_task('remove_missing_files')
    # A manual/scheduled Scan only discovers files not yet tracked - it never
    # re-examines files that are already in the database. Anything left pending from a
    # settings change (a naming language just enabled, Clean Names toggled, a template
    # edited, ...) resets each affected file's `organized` flag but otherwise sits idle
    # until something re-drives the per-file pipeline. Piggybacking here makes "Scan"
    # also catch up on that pending identify/organize/verify/compress work, instead of
    # only surfacing it on the next titledb update or container restart.
    enqueue_task('process_library')


def _insert_file(library_path, library_id, filepath):
    """Read file info from disk and insert a Files row. Returns the row, or None on failure."""
    file_display = filepath.replace(library_path, "").lstrip("/")
    logger.info(f'Getting file info: {file_display}')
    file_info = titles_lib.get_file_info(filepath)
    if file_info is None:
        logger.error(f'Failed to get info for file: {file_display}')
        return None
    return create_file(library_id, filepath, file_info)


@register_task('add_file')
def add_file_task(library_path, filepath, **kwargs):
    """Add a single file to the library DB."""
    library_id = get_library_id(library_path)
    if filepath in get_library_file_paths(library_id):
        return

    new_file = _insert_file(library_path, library_id, filepath)
    if new_file is None:
        raise ValueError(f'Failed to add file: {filepath}')

    enqueue_task('process_file', {'file_id': new_file.id})


# --- Per-file pipeline ---
#
# Every stage a file can need, in the order it needs them. A stage either runs inline in
# the driver (`run`) or is delegated to a registered task (`task`) that re-drives the file
# when it finishes — delegation is what buys a concurrency group, a cancel hook and a
# progress bar, so it is reserved for the stages that want them.
Stage = namedtuple('Stage', 'name applies run task')


def _needs_identify(file, mgmt):
    """The per-file form of library.get_files_to_identify."""
    if not file.identified and not file.identification_attempts:
        return True
    return bool(titles_lib.Keys.keys_loaded) and file.identification_type == 'filename'


def _identify(file, mgmt):
    """Identify one file and upsert its Apps/Titles."""
    identified_title_ids = []
    filepath = file.filepath
    logger.info(f'Identifying file: {file.filename}')
    identification, success, file_contents, error = titles_lib.identify_file(filepath)

    if success and file_contents and not error:
        title_ids = list(dict.fromkeys([c['title_id'] for c in file_contents]))
        for title_id in title_ids:
            add_title_id_in_db(title_id)

        nb_content = 0
        for file_content in file_contents:
            logger.info(f'Found content Title ID: {file_content["title_id"]} App ID: {file_content["app_id"]} Type: {file_content["type"]} Version: {file_content["version"]}')
            title_id_in_db = get_title_id_db_id(file_content["title_id"])

            # Atomic owned-OR upsert: on conflict, flip owned=True without
            # clobbering an existing row's title_id/app_type.
            stmt = sqlite_insert(Apps.__table__).values(
                app_id=file_content["app_id"],
                app_version=file_content["version"],
                app_type=file_content["type"],
                owned=True,
                title_id=title_id_in_db,
            ).on_conflict_do_update(
                index_elements=['app_id', 'app_version'],
                set_={'owned': True},
            )
            db.session.execute(stmt)
            db.session.commit()

            add_file_to_app(file_content["app_id"], file_content["version"], file.id)
            nb_content += 1

        if nb_content > 1:
            file.multicontent = True
        file.nb_content = nb_content
        file.identified = True
        identified_title_ids = title_ids
    else:
        logger.warning(f"Error identifying file {file.filename}: {error}")
        file.identification_error = error
        file.identified = False

    file.identification_type = identification
    file.identification_attempts += 1
    file.last_attempt = datetime.datetime.now()
    db.session.commit()

    for title_id in identified_title_ids:
        enqueue_task('add_missing_apps_for_title', {'title_id': title_id})


def _verify_eligible(file, mgmt):
    """Whether a file could ever be verified at all, independent of its current
    verdict: extension is one verification covers, verification is turned on, and
    keys are loaded. Shared by _needs_verify (only the still-unverified subset of
    this) and force mode in verify_library_task (every eligible file, verified or
    not) - so a force re-verify still correctly skips a file type verification
    doesn't cover, exactly as a normal pass would, rather than trying to verify
    literally everything."""
    verification = mgmt['verification']
    return (verification['enabled'] and file.extension in verification_lib.VERIFY_EXT
            and titles_lib.Keys.keys_loaded)


def _needs_verify(file, mgmt):
    if not _verify_eligible(file, mgmt):
        return False
    verification = mgmt['verification']
    if verification['depth'] == verification_lib.DEPTH_HASH:
        return file.hash_valid is None or (file.hash_valid is False
                                           and file.hash_modified is None)
    return file.signature_valid is None


def _needs_organize(file, mgmt):
    return mgmt['organizer']['enabled'] and file.identified and not file.organized


def _organize(file, mgmt):
    """Place one file under the organizer templates, holding the path claim across the move."""
    if not mgmt['organizer']['enabled']:
        return
    claimed = file.filepath
    if not claim_temp_file(claimed):
        return
    library_path = get_library_path(file.library_id)
    try:
        if organize_file(file, library_path, mgmt['organizer']):
            file.organized = True
            db.session.commit()
    finally:
        remove_temp_file(claimed)
    enqueue_task('library_maintenance', {'library_path': library_path})


def _needs_compress(file, mgmt):
    if not mgmt['compression']['enabled'] or file.compressed or file.extension not in COMPRESS_EXT:
        return False
    if verification_status(file) == verification_lib.STATUS_CORRUPT:
        return False
    target = compression.conversion_target(file)
    return Files.query.filter(Files.filepath == target, Files.id != file.id).first() is None


STAGES = [
    Stage('identify', _needs_identify, _identify, None),
    Stage('organize', _needs_organize, _organize, None),
    Stage('verify', _needs_verify, None, 'verify_file'),
    Stage('compress', _needs_compress, None, 'compress_file'),
]

# The identify/organize stages are fast and run inline; verify/compress are slower and
# delegated. Splitting the two out lets a library-wide pass finish every rename/move
# before verification starts on any file, instead of the two racing each other file by
# file across the library when multiple workers run concurrently.
ORGANIZE_STAGES = STAGES[:2]
VERIFY_STAGES = STAGES[2:]


def _drive_file(file_id, stages, force_verify=False):
    """Shared driver: walk one file down `stages`, inline stages here, delegated
    stages by task.

    A delegated stage becomes a child task (`enqueue_or_child`) and this driver parks
    itself waiting on it, rather than firing it off as an unrelated top-level task and
    immediately reporting done. That parking is what makes cancelling an ancestor -
    verify_library, an organize pass, or a single file's own process_file - correctly
    cascade down to the delegated work still in flight: `_cancel_atomic` already
    recurses into a `waiting_for_children` child, but has nothing to walk into for a
    detached top-level task an unparked driver would otherwise have left behind.

    `force_verify` (only ever true for an explicit forced re-verify pass) makes the
    'verify' stage specifically use `_verify_eligible` instead of its normal
    `_needs_verify` - so a file already carrying a verdict is still walked into
    verify_file rather than skipped as "nothing to do here". No other stage is
    affected: organize/identify/compress still only run when they normally would.
    """
    done = set()
    while True:
        file = db.session.get(Files, file_id)
        if file is None:
            return
        if not os.path.exists(file.filepath):
            # Same guard as remove_missing_files_from_db's own offline check, and for
            # the same reason: this is exactly the check that was deleting a whole
            # library's worth of not-yet-verified rows at container startup whenever
            # process_library ran before a network mount had finished reconnecting -
            # every file still needing verify/organize got walked in here individually
            # and wiped, while already-verified ones were never looked at again and so
            # silently survived. A library that looks offline gets left alone here
            # too; a scan picks the file back up unchanged once the mount is back,
            # rather than reprocessing it as new.
            library_path = get_library_path(file.library_id)
            if library_path and _library_looks_offline(library_path):
                logger.warning(
                    f"Library for file {file.filename} looks offline (path missing "
                    "or empty) - not deleting its tracked row; a scan will pick it "
                    "back up once the mount is back."
                )
                return
            logger.warning(f'File {file.filename} no longer exists, deleting from database.')
            remove_file_from_apps(file_id)
            Files.query.filter_by(id=file_id).delete(synchronize_session=False)
            db.session.commit()
            return
        mgmt = get_settings()['library']['management']

        def _stage_applies(s):
            if force_verify and s.name == 'verify':
                return _verify_eligible(file, mgmt)
            return s.applies(file, mgmt)

        stage = next((s for s in stages if s.name not in done and _stage_applies(s)), None)
        if stage is None:
            return
        done.add(stage.name)
        if stage.task:
            enqueue_or_child(stage.task, {'file_id': file_id})
            set_waiting_for_children()
            return
        stage.run(file, mgmt)


@register_task('process_file')
def process_file_task(file_id, **kwargs):
    """Drive one file down the full stage list. Used outside a whole-library pass - a
    single newly added file, a watcher event, a manual re-check - where there is no
    library-wide organize phase to keep separate from verification."""
    _drive_file(file_id, STAGES)


@register_task('process_file_organize')
def process_file_organize_task(file_id, **kwargs):
    """Library-wide organize phase: identify+organize one file, nothing else."""
    _drive_file(file_id, ORGANIZE_STAGES)


@register_task('process_file_verify')
def process_file_verify_task(file_id, force=False, **kwargs):
    """Library-wide verify phase: verify/compress one file, nothing else. `force` (see
    verify_library_task) makes the verify stage specifically re-run even on an already-
    verified file, instead of only ones still missing a verdict."""
    _drive_file(file_id, VERIFY_STAGES, force_verify=force)


@register_task('process_library')
def process_library_task(**kwargs):
    """Phase 1 of 2: organize every file that still needs identifying or organizing.

    Verification (phase 2, `verify_library_task` below) only starts once this settles -
    see `_process_library_organize_done` - so a whole-library pass finishes
    renaming/moving files to where the current settings say they belong before the
    slower verify/compress work begins, rather than the two happening at the same time
    across different files."""
    mgmt = get_settings()['library']['management']
    files = [f for f in Files.query.all() if any(s.applies(f, mgmt) for s in ORGANIZE_STAGES)]
    logger.info(f'Processing library (organize phase): {len(files)} file(s).')
    for f in files:
        enqueue_or_child('process_file_organize', {'file_id': f.id})
    # Unconditional: with zero children this still completes immediately and runs the
    # continuation below, which is what kicks off the verify phase - process_library
    # must not just return when there's nothing to organize, or verification (the far
    # more common case once a library is already organized) would never run from here.
    set_waiting_for_children()


@register_continuation('process_library')
def _process_library_organize_done(**kwargs):
    enqueue_task('library_maintenance')
    enqueue_task('update_titles')
    enqueue_task('verify_library')


@register_task('verify_library')
def verify_library_task(force=False, **kwargs):
    """Phase 2 of 2: verify/compress every file that needs it, now that this pass's
    organizing has settled.

    `force` (only ever set by an explicit "Verify library now, force" admin action,
    never by the automatic pipeline) re-verifies every eligible file regardless of
    its current verdict, including ones already Valid - see _verify_eligible for what
    "eligible" still means even in force mode. Ordinarily (force left off, which is
    what every automatic trigger and a plain "Verify library now" both use), a file
    that already has a verdict is left completely alone: re-running this is never by
    itself a reason to redo work verification already settled.
    """
    mgmt = get_settings()['library']['management']
    if force:
        files = [f for f in Files.query.all()
                if _verify_eligible(f, mgmt) or _needs_compress(f, mgmt)]
    else:
        files = [f for f in Files.query.all() if any(s.applies(f, mgmt) for s in VERIFY_STAGES)]
    logger.info(f'Processing library (verify phase{", forced" if force else ""}): {len(files)} file(s).')
    for f in files:
        enqueue_or_child('process_file_verify', {'file_id': f.id, 'force': force} if force else {'file_id': f.id})
    set_waiting_for_children()


@register_continuation('verify_library')
def _verify_library_done(**kwargs):
    # Duplicate resolution depends on having a definitive verdict for every copy, so
    # it only ever makes sense to run once a verify pass has actually settled -
    # never speculatively against files that might still be mid-verification.
    enqueue_task('resolve_duplicate_files')


@register_task('resolve_duplicate_files')
def resolve_duplicate_files_task(**kwargs):
    """Opt-in (library.management.duplicates.auto_resolve, off by default): for every
    app with more than one physical file attached, automatically keep the healthiest
    one and delete the rest - but only when every copy already has a complete,
    unambiguous Valid/Repack/Corrupt verdict. A group containing an unverified,
    modified, or signature-only file is left alone entirely regardless of the settings
    below - see library.automatic_duplicate_winner for that rule, which always applies.

    A genuine tie between two files at the same (best) rank is, by default, also left
    alone - but two independent, opt-in preferences (both off by default, and each
    only takes effect when auto_resolve is also on) can break it instead:

    - library.management.duplicates.compression_preference ('compressed' or
      'uncompressed'): applied first. A compressed file is inherently smaller than the
      same content uncompressed, so leaving this off and relying on size alone would
      always penalize compression even for someone who has deliberately turned it on.
    - library.management.duplicates.prefer_larger_on_tie: applied to whatever's left
      after the above (or the full tied set, if compression didn't distinguish
      anything) - the larger file wins.

    At that point every tied file has already independently passed the same
    verification the sole winner would have, so either preference is just a choice
    between equally-legitimate copies, never a guess about which is real. See
    library.duplicate_winner_with_preferences for the exact rule.

    Enqueued after every verify_library pass settles, and at startup.
    """
    duplicates_settings = get_settings().get('library', {}).get('management', {}).get('duplicates', {})
    if not duplicates_settings.get('auto_resolve', False):
        return
    prefer_larger = duplicates_settings.get('prefer_larger_on_tie', False)
    compression_preference = duplicates_settings.get('compression_preference', 'none')

    if not prefer_larger and compression_preference not in ('compressed', 'uncompressed'):
        pick_winner = automatic_duplicate_winner
    else:
        def pick_winner(group_files):
            return duplicate_winner_with_preferences(
                group_files, prefer_larger_on_tie=prefer_larger,
                compression_preference=compression_preference)

    resolved = 0
    for app, files in duplicate_file_groups():
        winner = pick_winner(files)
        if winner is None:
            continue
        loser_ids = [f.id for f in files if f.id != winner.id]
        logger.info(f"Auto-resolving {len(files)} duplicate file(s) for app {app.app_id} "
                    f"v{app.app_version}: keeping file {winner.id}, dropping {loser_ids}.")
        resolve_duplicate_files(winner.id, [f.id for f in files])
        resolved += 1
    if resolved:
        logger.info(f'Automatically resolved {resolved} duplicate file group(s).')


@register_task('library_maintenance')
def library_maintenance_task(library_path=None, **kwargs):
    """Post-organization GC: prune empty folders and outdated updates."""
    settings = get_settings()
    organizer = settings['library']['management']['organizer']
    if organizer.get('enabled') and organizer.get('remove_empty_folders'):
        paths = [library_path] if library_path else [lib.path for lib in get_libraries()]
        for path in paths:
            delete_empty_folders(path)
    if settings['library']['management']['delete_older_updates']:
        enqueue_task('remove_outdated_updates')


@register_task('add_missing_apps_for_title')
def add_missing_apps_for_title_task(title_id, **kwargs):
    """Per-title: expand missing base/update/DLC apps for one title, then enqueue update_titles_for_title."""
    add_missing_apps_for_title(title_id)
    enqueue_or_child('update_titles_for_title', {'title_id': title_id})
    set_waiting_for_children()


@register_task('update_titles_for_title')
def update_titles_for_title_task(title_id, **kwargs):
    """Per-title: recompute have_base / up_to_date / complete under BEGIN IMMEDIATE."""
    update_title_flags(title_id)


@register_task('remove_outdated_updates')
def remove_outdated_updates_task(**kwargs):
    """Remove outdated update files."""
    remove_outdated_update_files()
    enqueue_task('update_titles')


# --- Verification ---
@register_task('verify_file', group='io')
def verify_file_task(file_id, **kwargs):
    """Verify one file's signatures and, at hash depth, its NCA content hashes."""
    file_obj = db.session.get(Files, file_id)
    if not file_obj or file_obj.extension not in verification_lib.VERIFY_EXT:
        return
    if not os.path.exists(file_obj.filepath):
        return
    opts = get_settings()['library']['management']['verification']
    if not opts['enabled']:
        return
    depth = opts['depth']
    logger.info(f'Verifying file ({depth}): {file_obj.filename}')
    signature_valid, hash_valid, hash_modified, error = verification_lib.verify(
        file_obj.filepath, depth, progress=_task_progress(_current_task_id))

    file_obj.signature_valid = signature_valid
    if hash_valid is not None:
        file_obj.hash_valid = hash_valid
        file_obj.hash_modified = hash_modified
    file_obj.verification_error = error
    file_obj.verified_at = datetime.datetime.now()
    db.session.commit()

    if error:
        logger.warning(f'Verification failed for {file_obj.filename}: {error}')
    enqueue_task('process_file', {'file_id': file_id})


# --- Compression pipeline ---
def _finalize_conversion(file_obj, target, new_extension, compressed):
    """Flip the Files row onto the verified output, then drop the now-redundant source."""
    source = file_obj.filepath
    add_ignored_event(source, '')  # our own deletion of the source
    file_obj.filepath = target
    file_obj.extension = new_extension
    file_obj.size = os.path.getsize(target)
    file_obj.mtime = os.path.getmtime(target)
    file_obj.compressed = compressed
    db.session.commit()
    if os.path.abspath(source) != os.path.abspath(target):
        os.remove(source)


def _convert_file(file_obj, produce, new_extension, compressed):
    """Run a (de)compression: produce the verified output at its final path, then finalize.
    Returns whether the row was flipped onto the new file - a caller that re-drives the
    pipeline must not do so after a no-op, or it delegates the same stage forever."""
    source = file_obj.filepath
    target = compression.conversion_target(file_obj)
    if Files.query.filter(Files.filepath == target, Files.id != file_obj.id).first() is not None:
        logger.warning(f'Skipping conversion of {os.path.basename(source)}: '
                       f'{os.path.basename(target)} is already in the library.')
        return False
    if not claim_temp_file(source):
        logger.debug(f'Skipping conversion of {os.path.basename(source)}: file is busy.')
        return False
    before = file_obj.size
    add_temp_file(target)
    try:
        out = str(produce(source, os.path.dirname(source)))
        _finalize_conversion(file_obj, out, new_extension, compressed)
    finally:
        remove_temp_file(target)
        remove_temp_file(source)
    after = file_obj.size
    ratio = after / before if before else 0
    verb = 'compressing' if compressed else 'decompressing'
    logger.info(f'Finished {verb} {os.path.basename(target)}: '
                f'{human_size(before)} -> {human_size(after)} (ratio {ratio:.1%})')
    return True


@register_task('compress_file', group='io')
def compress_file_task(file_id, **kwargs):
    """Compress a single file in place: NSP->NSZ / XCI->XCZ, preserving its DB row."""
    file_obj = db.session.get(Files, file_id)
    if not file_obj or file_obj.compressed or file_obj.extension not in COMPRESS_EXT:
        return
    if not os.path.exists(file_obj.filepath):
        return
    logger.info(f'Compressing file: {file_obj.filename}')
    opts = get_settings()['library']['management']['compression']
    if not opts['enabled']:
        return
    progress = _task_progress(_current_task_id)
    if _convert_file(file_obj,
                     lambda source, out_dir: compression.compress_to(source, out_dir, opts, progress=progress),
                     COMPRESS_EXT[file_obj.extension], True):
        enqueue_task('process_file', {'file_id': file_id})


@register_task('decompress_file', group='io')
def decompress_file_task(file_id, **kwargs):
    """Decompress a single file in place: NSZ->NSP / XCZ->XCI, preserving its DB row."""
    file_obj = db.session.get(Files, file_id)
    if not file_obj or not file_obj.compressed or file_obj.extension not in DECOMPRESS_EXT:
        return
    if not os.path.exists(file_obj.filepath):
        return
    progress = _task_progress(_current_task_id)
    _convert_file(file_obj,
                  lambda source, out_dir: compression.decompress_to(source, out_dir, progress=progress),
                  DECOMPRESS_EXT[file_obj.extension], False)


@register_cleanup('compress_file')
@register_cleanup('decompress_file')
def _compression_cleanup(file_id, **kwargs):
    """Idempotent cancel/crash cleanup: clear the in-progress mark, remove the partial
    output if it isn't a committed file, and pop the source-deletion ignored event."""
    file_obj = db.session.get(Files, file_id)
    if not file_obj:
        return
    remove_temp_file(file_obj.filepath)  # release the source in-progress claim
    target = compression.conversion_target(file_obj)
    if target:
        if Files.query.filter_by(filepath=target).first() is None and os.path.exists(target):
            add_ignored_event(target, '')  # our own deletion of the partial output
            os.remove(target)
        remove_temp_file(target)
    pop_ignored_event(src_path=file_obj.filepath, dest_path='')

# --- Batch maintenance ---
@register_task('add_missing_apps')
def add_missing_apps_task(**kwargs):
    """Batch: expand missing apps for every title. Used post-titledb-update."""
    add_missing_apps_to_db()
    enqueue_task('update_titles')


@register_task('remove_missing_files')
def remove_missing_files_task(**kwargs):
    """Delete DB entries for files missing from disk, then recompute all title flags."""
    remove_missing_files_from_db()
    enqueue_task('update_titles')


@register_task('update_titles')
def update_titles_task(**kwargs):
    """Batch: recompute flags for every title. Used post-titledb-update."""
    update_titles()


# --- Library lifecycle ---
@register_task('remove_library')
def remove_library_task(library_path, **kwargs):
    """Delete a library and its files (flipping app ownership), then recompute titles."""
    library = Libraries.query.filter_by(path=library_path).first()
    if not library:
        return
    for file_id in [f.id for f in library.files]:
        remove_file_from_apps(file_id)
    db.session.delete(library)
    db.session.commit()
    logger.info(f"Removed library: {library_path}")
    enqueue_task('update_titles')


# --- Watcher event handlers ---

def _reconcile_existing_file(file, filepath):
    """Check one already-tracked file against what's currently on disk. Resets its
    identification/organization/verification state only if the size or mtime actually
    changed - the same signal the live watcher uses for a real-time change event, so a
    Scan and a filesystem event agree on what counts as "modified." Returns True if
    the file needed resetting (the caller still owns re-queuing it).

    Deliberately size+mtime rather than a content hash: that is what git, rsync and
    most sync tools already rely on to say "probably identical" without reading the
    whole file, and hashing an entire library on every scan would defeat the point of
    a scan that found nothing new costing nothing.
    """
    try:
        new_size = titles_lib.get_file_size(filepath)
        new_mtime = os.path.getmtime(filepath)
    except OSError:
        return False  # gone between the directory walk and this check; not this function's job
    if file.size == new_size and file.mtime == new_mtime:
        return False

    logger.info(f'File changed on disk, re-identifying: {file.filename}')
    remove_file_from_apps(file.id)
    file.size = new_size
    file.mtime = new_mtime
    file.organized = False
    reset_file_identification(file)
    reset_file_verification(file)
    db.session.commit()
    return True


@register_task('handle_file_added')
def handle_file_added_task(library_path, filepath, **kwargs):
    file = Files.query.filter_by(filepath=filepath).first()
    if file is None:
        enqueue_task('add_file', {'library_path': library_path, 'filepath': filepath})
        return
    if _reconcile_existing_file(file, filepath):
        enqueue_task('process_file', {'file_id': file.id})


@register_task('handle_file_moved')
def handle_file_moved_task(library_path, src_path, dest_path, **kwargs):
    if file_exists_in_db(src_path):
        update_file_path(library_path, src_path, dest_path)
    else:
        enqueue_task('add_file', {'library_path': library_path, 'filepath': dest_path})


@register_task('handle_file_deleted')
def handle_file_deleted_task(filepath, **kwargs):
    delete_file_by_filepath(filepath)
    enqueue_task('update_titles')


@register_task('handle_dir_deleted')
def handle_dir_deleted_task(dirpath, **kwargs):
    """A folder was moved out/removed: delete all its files from the library."""
    if delete_files_under_dir(dirpath):
        enqueue_task('update_titles')

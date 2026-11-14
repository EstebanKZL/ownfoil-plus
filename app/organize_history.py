"""The last Organize runs and the moves each made, so one can be put back.

A run is what one top-level task organized - a library pass, the new files of a scan, a
file organized on its own - and its moves are every file it moved: the game files and
their companions (NFO, SFV, proof images). Putting a run back moves its files, newest
first, to the names and folders they had: one whose new place is gone, or whose old name
is taken, is skipped and said so - nothing is ever written over. Only the last
ORGANIZE_RUNS_KEPT runs are kept.
"""
import datetime
import logging
import os
import shutil

from db import (ORGANIZE_RUNS_KEPT, Files, OrganizeMove, OrganizeRun, add_ignored_event,
                db, get_library_path, pop_ignored_event, update_file_path)

logger = logging.getLogger('main')

# Why a move can't be put back.
SKIP_GONE = 'gone'          # the file is no longer where Organize put it
SKIP_TAKEN = 'taken'        # something already has its old name
SKIP_MOVED = 'moved'        # the game file was moved again since


def record(run_key, moves):
    """Add `moves` - (file_id or None, old path, new path) - to the run `run_key`."""
    if not moves:
        return
    run = OrganizeRun.query.filter_by(key=run_key).first()
    if run is None:
        run = OrganizeRun(key=run_key, started_at=datetime.datetime.utcnow())
        db.session.add(run)
        db.session.flush()
        _prune(keep_id=run.id)
    now = datetime.datetime.utcnow()
    for file_id, old, new in moves:
        db.session.add(OrganizeMove(run_id=run.id, file_id=file_id, old_path=old,
                                    new_path=new, moved_at=now))
    db.session.commit()


def _prune(keep_id):
    runs = OrganizeRun.query.order_by(OrganizeRun.started_at.desc(), OrganizeRun.id.desc()).all()
    for old in runs[ORGANIZE_RUNS_KEPT:]:
        if old.id == keep_id:
            continue
        OrganizeMove.query.filter_by(run_id=old.id).delete()
        db.session.delete(old)


def runs():
    """The kept runs, newest first: when, how many games and files, and whether put back."""
    out = []
    for run in OrganizeRun.query.order_by(OrganizeRun.started_at.desc(), OrganizeRun.id.desc()).all():
        moves = OrganizeMove.query.filter_by(run_id=run.id).all()
        out.append({
            'id': run.id,
            'started_at': run.started_at.isoformat() + 'Z',
            'undone_at': run.undone_at.isoformat() + 'Z' if run.undone_at else None,
            'games': sum(1 for m in moves if m.file_id is not None),
            'files': len(moves),
            'pending': sum(1 for m in moves if not m.undone),
        })
    return out


def _check(move):
    """None when the move can be put back, else why not."""
    if not os.path.exists(move.new_path):
        return SKIP_GONE
    if os.path.exists(move.old_path):
        return SKIP_TAKEN
    if move.file_id is not None:
        file = db.session.get(Files, move.file_id)
        if file is not None and file.filepath != move.new_path:
            return SKIP_MOVED
    return None


def preview(run_id):
    """What putting the run back would do: each move, newest first, with whether it goes
    back or why it's skipped."""
    run = db.session.get(OrganizeRun, run_id)
    if run is None:
        return None
    items = []
    for move in _pending(run_id):
        items.append({'old_path': move.old_path, 'new_path': move.new_path,
                      'game': move.file_id is not None, 'skip': _check(move)})
    return {'id': run.id, 'started_at': run.started_at.isoformat() + 'Z', 'items': items}


def _pending(run_id):
    return (OrganizeMove.query.filter_by(run_id=run_id, undone=False)
            .order_by(OrganizeMove.moved_at.desc(), OrganizeMove.id.desc()).all())


def undo(run_id):
    """Put the run's files back, newest first. Returns (moved back, skipped)."""
    run = db.session.get(OrganizeRun, run_id)
    if run is None:
        return 0, 0
    back = skipped = 0
    for move in _pending(run_id):
        reason = _check(move)
        if reason:
            logger.info(f'Organize history: {os.path.basename(move.new_path)} stays ({reason}).')
            skipped += 1
            continue
        try:
            os.makedirs(os.path.dirname(move.old_path), exist_ok=True)
            add_ignored_event(move.new_path, move.old_path)
            shutil.move(move.new_path, move.old_path)
        except (shutil.Error, OSError) as e:
            pop_ignored_event(src_path=move.new_path, dest_path=move.old_path)
            logger.warning(f'Organize history: could not put back {move.new_path}: {e}')
            skipped += 1
            continue
        if move.file_id is not None:
            file = db.session.get(Files, move.file_id)
            if file is not None:
                update_file_path(get_library_path(file.library_id), move.new_path, move.old_path)
        move.undone = True
        back += 1
        db.session.commit()
    run.undone_at = datetime.datetime.utcnow()
    db.session.commit()
    logger.info(f'Organize history: run {run_id} put back - {back} moved back, {skipped} skipped.')
    return back, skipped

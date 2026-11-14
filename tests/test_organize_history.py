"""The last Organize runs are kept with their moves, and one can be put back: newest
first, to the names and folders the files had - never writing over a file."""
import os

import pytest

import organize_history
from app import create_app
from db import ORGANIZE_RUNS_KEPT, Files, Libraries, OrganizeMove, OrganizeRun, db


@pytest.fixture
def lib(tmp_path):
    app = create_app(f"sqlite:///{tmp_path/'h.db'}")
    games = tmp_path / "games"
    games.mkdir()
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    library = Libraries(path=str(games))
    db.session.add(library)
    db.session.commit()
    yield library, games
    ctx.pop()


def _organized(library, games, name='Game.nsp', moved_to='Game [0100][v0]/Game [0100].nsp'):
    """A file Organize moved: on disk at its new place, its record there too."""
    old, new = games / name, games / moved_to
    new.parent.mkdir(parents=True, exist_ok=True)
    new.write_bytes(b'x')
    f = Files(filepath=str(new), library_id=library.id, folder=str(new.parent), filename=new.name,
              extension='nsp', size=1, identified=True, organized=True)
    db.session.add(f)
    db.session.commit()
    return f, str(old), str(new)


def test_a_run_is_put_back_and_the_record_follows(lib):
    library, games = lib
    f, old, new = _organized(library, games)
    nfo_old, nfo_new = str(games / 'Game.nfo'), str(games / 'Game [0100][v0]' / 'Game [0100].nfo')
    open(nfo_new, 'w').close()
    organize_history.record('task-1', [(f.id, old, new), (None, nfo_old, nfo_new)])
    [run] = organize_history.runs()
    assert run['games'] == 1 and run['files'] == 2 and run['pending'] == 2

    preview = organize_history.preview(run['id'])
    assert [i['skip'] for i in preview['items']] == [None, None]

    assert organize_history.undo(run['id']) == (2, 0)
    assert os.path.exists(old) and not os.path.exists(new) and os.path.exists(nfo_old)
    assert db.session.get(Files, f.id).filepath == old
    assert organize_history.runs()[0]['pending'] == 0


def test_nothing_is_written_over(lib):
    library, games = lib
    f, old, new = _organized(library, games)
    open(old, 'w').close()                  # something has its old name now
    organize_history.record('task-2', [(f.id, old, new)])
    run_id = organize_history.runs()[0]['id']
    assert organize_history.preview(run_id)['items'][0]['skip'] == organize_history.SKIP_TAKEN
    assert organize_history.undo(run_id) == (0, 1)
    assert os.path.exists(new)              # left where it was


def test_a_file_moved_again_or_gone_is_skipped(lib):
    library, games = lib
    f, old, new = _organized(library, games)
    f.filepath = str(games / 'elsewhere.nsp')
    db.session.commit()
    organize_history.record('task-3', [(f.id, old, new), (None, str(games / 'a.nfo'), str(games / 'gone.nfo'))])
    skips = [i['skip'] for i in organize_history.preview(organize_history.runs()[0]['id'])['items']]
    assert sorted(skips) == sorted([organize_history.SKIP_MOVED, organize_history.SKIP_GONE])


def test_only_the_last_runs_are_kept(lib):
    library, games = lib
    for n in range(ORGANIZE_RUNS_KEPT + 3):
        organize_history.record(f'task-{n}', [(None, f'/a/{n}', f'/b/{n}')])
    assert OrganizeRun.query.count() == ORGANIZE_RUNS_KEPT
    assert OrganizeMove.query.count() == ORGANIZE_RUNS_KEPT


def test_moves_of_one_task_go_in_one_run(lib):
    organize_history.record('task-9', [(None, '/a/1', '/b/1')])
    organize_history.record('task-9', [(None, '/a/2', '/b/2')])
    assert OrganizeRun.query.count() == 1 and OrganizeMove.query.count() == 2

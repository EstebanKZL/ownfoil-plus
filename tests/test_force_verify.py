"""verify_library_task(force=True): re-verify every eligible file regardless of its
current verdict, for the explicit "Verify library now, force" admin action - as
opposed to a plain call (or the automatic pipeline), which only ever picks up files
still missing a verdict. The critical thing to prove: force must actually reach all
the way down to _drive_file, which itself re-checks "does this file need verify" - a
force flag that stopped at verify_library_task's own file selection wouldn't be
enough, since _drive_file would independently skip an already-verified file anyway.
"""
import types

import pytest

import db as db_mod
import tasks
from app import create_app
from db import Files, Libraries, db, init_db
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

        def seed(name, **verdict):
            path = lib_dir / name
            path.write_bytes(b"X" * 7)
            f = Files(filepath=str(path), library_id=library.id, folder=str(lib_dir),
                     filename=name, extension=name.rsplit(".", 1)[-1], size=7,
                     identified=True, organized=True, **verdict)
            db.session.add(f)
            db.session.commit()
            return f

        yield types.SimpleNamespace(app=app, lib_dir=lib_dir, library=library, seed=seed)


def _settings(depth="signature"):
    return {
        "library": {
            "management": {
                "compression": {"enabled": False},
                "verification": {"enabled": True, "depth": depth},
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


def _run_all_pending(app, max_steps=50):
    worker = TaskWorker(app, worker_id=1)
    for _ in range(max_steps):
        task_id = worker.claim_task()
        if task_id is None:
            return
        worker.execute_task(task_id)


def test_a_plain_verify_pass_leaves_an_already_valid_file_alone(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings())
    monkeypatch.setattr(tasks.titles_lib.Keys, "keys_loaded", True, raising=False)
    verified = []
    monkeypatch.setitem(tasks.TASK_REGISTRY, "verify_file",
                        lambda file_id, **kw: verified.append(file_id))

    env.seed("AlreadyValid.nsp", signature_valid=True, hash_valid=True)

    with env.app.app_context():
        tasks.enqueue_task("verify_library")
        _run_all_pending(env.app)

    assert verified == [], "a file that already has a verdict must not be re-verified"


def test_force_re_verifies_an_already_valid_file(env, monkeypatch):
    """The whole point of the feature - and the part that would silently no-op if
    force only reached verify_library_task's own file selection and not the deeper
    per-file check in _drive_file."""
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings())
    monkeypatch.setattr(tasks.titles_lib.Keys, "keys_loaded", True, raising=False)
    verified = []
    monkeypatch.setitem(tasks.TASK_REGISTRY, "verify_file",
                        lambda file_id, **kw: verified.append(file_id))

    f = env.seed("AlreadyValid.nsp", signature_valid=True, hash_valid=True)

    with env.app.app_context():
        tasks.enqueue_task("verify_library", {"force": True})
        _run_all_pending(env.app)

    assert verified == [f.id]


def test_force_still_skips_a_file_verification_does_not_cover(env, monkeypatch):
    """Force bypasses "already has a verdict", not the real eligibility gates - an
    extension verification doesn't check at all is still left alone."""
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings())
    monkeypatch.setattr(tasks.titles_lib.Keys, "keys_loaded", True, raising=False)
    verified = []
    monkeypatch.setitem(tasks.TASK_REGISTRY, "verify_file",
                        lambda file_id, **kw: verified.append(file_id))

    env.seed("Readme.txt", signature_valid=None, hash_valid=None)

    with env.app.app_context():
        tasks.enqueue_task("verify_library", {"force": True})
        _run_all_pending(env.app)

    assert verified == []


def test_force_still_skips_everything_when_keys_are_not_loaded(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings())
    monkeypatch.setattr(tasks.titles_lib.Keys, "keys_loaded", False, raising=False)
    verified = []
    monkeypatch.setitem(tasks.TASK_REGISTRY, "verify_file",
                        lambda file_id, **kw: verified.append(file_id))

    env.seed("AlreadyValid.nsp", signature_valid=True, hash_valid=True)

    with env.app.app_context():
        tasks.enqueue_task("verify_library", {"force": True})
        _run_all_pending(env.app)

    assert verified == []


def test_force_still_skips_everything_when_verification_is_disabled(env, monkeypatch):
    settings = _settings()
    settings["library"]["management"]["verification"]["enabled"] = False
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks.titles_lib.Keys, "keys_loaded", True, raising=False)
    verified = []
    monkeypatch.setitem(tasks.TASK_REGISTRY, "verify_file",
                        lambda file_id, **kw: verified.append(file_id))

    env.seed("AlreadyValid.nsp", signature_valid=True, hash_valid=True)

    with env.app.app_context():
        tasks.enqueue_task("verify_library", {"force": True})
        _run_all_pending(env.app)

    assert verified == []


def test_force_re_verifies_a_mix_of_verified_and_unverified_files(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings())
    monkeypatch.setattr(tasks.titles_lib.Keys, "keys_loaded", True, raising=False)
    verified = []
    monkeypatch.setitem(tasks.TASK_REGISTRY, "verify_file",
                        lambda file_id, **kw: verified.append(file_id))

    already_valid = env.seed("Valid.nsp", signature_valid=True, hash_valid=True)
    never_checked = env.seed("New.nsp", signature_valid=None, hash_valid=None)

    with env.app.app_context():
        tasks.enqueue_task("verify_library", {"force": True})
        _run_all_pending(env.app)

    assert set(verified) == {already_valid.id, never_checked.id}

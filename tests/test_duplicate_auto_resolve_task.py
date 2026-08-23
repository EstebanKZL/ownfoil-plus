"""resolve_duplicate_files_task: the opt-in automatic pass that keeps the healthiest
copy of a duplicated file and drops the rest, only ever acting when every copy already
has a complete Valid/Repack/Corrupt verdict. Off by default; wired to run once a
verify_library pass settles, since it depends on having that verdict in hand.
"""
import os
import types
from unittest.mock import call, patch

import pytest

import tasks
from app import create_app
from constants import APP_TYPE_BASE
from db import Apps, Files, Libraries, Titles, db


VALID = dict(signature_valid=True, hash_valid=True)
REPACK = dict(signature_valid=False, hash_valid=True)
CORRUPT = dict(signature_valid=True, hash_valid=False, hash_modified=False)
UNVERIFIED = dict(signature_valid=None, hash_valid=None)


@pytest.fixture
def env(tmp_path):
    app = create_app(f"sqlite:///{tmp_path/'test.db'}")
    lib_dir = tmp_path / "games"
    lib_dir.mkdir()
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    library = Libraries(path=str(lib_dir))
    db.session.add(library)
    title = Titles(title_id="0100000000010000", have_base=True)
    db.session.add(title)
    db.session.flush()
    app_row = Apps(title_id=title.id, app_id="0100000000010000", app_version="0",
                   app_type=APP_TYPE_BASE, owned=True)
    db.session.add(app_row)
    db.session.commit()

    def seed(name, content=b"RAWDATA", **columns):
        path = lib_dir / name
        path.write_bytes(content)
        f = Files(filepath=str(path), library_id=library.id, folder=str(lib_dir),
                 filename=name, extension="nsp", size=len(content), identified=True, **columns)
        db.session.add(f)
        db.session.flush()
        app_row.files.append(f)
        db.session.commit()
        return f

    yield types.SimpleNamespace(app=app, lib_dir=lib_dir, seed=seed, app_row=app_row)
    ctx.pop()


def _settings(auto_resolve, prefer_larger_on_tie=False, compression_preference="none"):
    return {"library": {"management": {"duplicates": {
        "auto_resolve": auto_resolve, "prefer_larger_on_tie": prefer_larger_on_tie,
        "compression_preference": compression_preference,
    }}}}


def test_does_nothing_when_the_setting_is_off(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(False))
    winner = env.seed("Game.nsp", **VALID)
    loser = env.seed("Game(2).nsp", content=b"X", **CORRUPT)

    tasks.resolve_duplicate_files_task()

    assert os.path.exists(winner.filepath)
    assert os.path.exists(loser.filepath)  # untouched - the setting is off


def test_deletes_the_worse_copy_when_enabled_and_unambiguous(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(True))
    winner = env.seed("Game.nsp", **VALID)
    loser = env.seed("Game(2).nsp", content=b"X", **CORRUPT)
    loser_path = loser.filepath

    tasks.resolve_duplicate_files_task()

    assert os.path.exists(winner.filepath)
    assert not os.path.exists(loser_path)


def test_a_group_with_an_unverified_file_is_left_alone_even_when_enabled(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(True))
    valid = env.seed("Game.nsp", **VALID)
    unverified = env.seed("Game(2).nsp", content=b"X", **UNVERIFIED)

    tasks.resolve_duplicate_files_task()

    assert os.path.exists(valid.filepath)
    assert os.path.exists(unverified.filepath)  # still there - not enough information


def test_a_tie_is_left_alone_even_when_enabled(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(True))
    a = env.seed("Game.nsp", **VALID)
    b = env.seed("Game(2).nsp", content=b"X", **VALID)

    tasks.resolve_duplicate_files_task()

    assert os.path.exists(a.filepath)
    assert os.path.exists(b.filepath)


def test_prefer_larger_on_tie_is_off_by_default_even_with_auto_resolve_on(env, monkeypatch):
    """The two settings are independent: turning on auto_resolve alone must not
    silently start guessing on ties too - prefer_larger_on_tie is its own opt-in."""
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(True, prefer_larger_on_tie=False))
    small = env.seed("Game.nsp", content=b"SMALL", **VALID)
    big = env.seed("Game(2).nsp", content=b"A LOT BIGGER CONTENT", **VALID)

    tasks.resolve_duplicate_files_task()

    assert os.path.exists(small.filepath)
    assert os.path.exists(big.filepath)


def test_prefer_larger_on_tie_resolves_a_valid_valid_tie_by_size(env, monkeypatch):
    """The exact case reported: two files both Valid, differing only in size."""
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(True, prefer_larger_on_tie=True))
    small = env.seed("Game.nsp", content=b"SMALL", **VALID)
    small_path = small.filepath  # captured before resolution deletes this row
    big_content = b"A LOT BIGGER CONTENT"
    big = env.seed("Game(2).nsp", content=big_content, **VALID)
    big_path = big.filepath

    tasks.resolve_duplicate_files_task()

    # The bigger file survives and takes over the plain name once the smaller loser
    # is gone (see library.resolve_duplicate_files) - so "Game.nsp" exists again, but
    # with the bigger file's own content, not the original small one's.
    assert not os.path.exists(big_path)  # its old "(2)" path is gone, it moved
    assert open(small_path, "rb").read() == big_content


def test_prefer_larger_on_tie_has_no_effect_when_auto_resolve_itself_is_off(env, monkeypatch):
    """prefer_larger_on_tie alone (without auto_resolve) must not do anything - it's
    explicitly documented as only taking effect when auto_resolve is also on."""
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(False, prefer_larger_on_tie=True))
    small = env.seed("Game.nsp", content=b"SMALL", **VALID)
    big = env.seed("Game(2).nsp", content=b"A LOT BIGGER CONTENT", **VALID)

    tasks.resolve_duplicate_files_task()

    assert os.path.exists(small.filepath)
    assert os.path.exists(big.filepath)


def test_prefer_larger_on_tie_still_refuses_an_unverified_group(env, monkeypatch):
    """The safety gate is unaffected by this setting - an unverified file in the group
    still blocks resolution entirely, even with prefer_larger_on_tie enabled."""
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(True, prefer_larger_on_tie=True))
    small = env.seed("Game.nsp", content=b"SMALL", **VALID)
    big = env.seed("Game(2).nsp", content=b"A LOT BIGGER CONTENT", **VALID)
    unverified = env.seed("Game(3).nsp", content=b"Z", **UNVERIFIED)

    tasks.resolve_duplicate_files_task()

    assert os.path.exists(small.filepath)
    assert os.path.exists(big.filepath)
    assert os.path.exists(unverified.filepath)


def test_an_app_with_only_one_file_is_not_touched(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(True))
    only = env.seed("Game.nsp", **VALID)

    tasks.resolve_duplicate_files_task()  # must not raise on an empty duplicate set

    assert os.path.exists(only.filepath)


def test_verify_library_continuation_enqueues_duplicate_resolution(env, monkeypatch):
    enqueued = []
    monkeypatch.setattr(tasks, "enqueue_task", lambda name, data=None, **k: enqueued.append(name))

    tasks._verify_library_done()

    assert enqueued == ["resolve_duplicate_files"]


def test_compression_preference_alone_resolves_a_mixed_format_tie(env, monkeypatch):
    """The exact case that motivated this setting: a compressed and an uncompressed
    copy of the same content both verify Valid. compression_preference alone (no
    prefer_larger_on_tie needed) settles it correctly, keeping the compressed one even
    though it's the smaller file."""
    monkeypatch.setattr(tasks, "get_settings",
                        lambda: _settings(True, compression_preference="compressed"))
    uncompressed = env.seed("Game.nsp", content=b"BIGGER-UNCOMPRESSED", compressed=False, **VALID)
    compressed_content = b"SMALL"
    compressed = env.seed("Game.nsz", content=compressed_content, compressed=True, **VALID)
    uncompressed_path = uncompressed.filepath

    tasks.resolve_duplicate_files_task()

    assert not os.path.exists(uncompressed_path)
    # The compressed file survives - possibly renamed if it had a "(n)" suffix, but
    # here neither file had one, so its own path is untouched.
    assert open(compressed.filepath, "rb").read() == compressed_content


def test_compression_preference_off_by_default_even_with_auto_resolve_and_prefer_larger_on(env, monkeypatch):
    """compression_preference is independent of prefer_larger_on_tie - turning the
    latter on must not silently activate the former."""
    monkeypatch.setattr(tasks, "get_settings",
                        lambda: _settings(True, prefer_larger_on_tie=True, compression_preference="none"))
    uncompressed = env.seed("Game.nsp", content=b"BIGGER-UNCOMPRESSED", compressed=False, **VALID)
    compressed = env.seed("Game.nsz", content=b"SMALL", compressed=True, **VALID)
    compressed_path = compressed.filepath

    tasks.resolve_duplicate_files_task()

    # With no compression preference, prefer_larger_on_tie alone picks the bigger
    # (uncompressed) file - the documented, expected nuance.
    assert not os.path.exists(compressed_path)
    assert os.path.exists(uncompressed.filepath)

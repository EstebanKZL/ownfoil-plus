"""Every extension check throughout this session (ALLOWED_EXTENSIONS, COMPRESS_EXT,
VERIFY_EXT) covers all four formats - nsp, xci, nsz, xcz - and none of the newer code
(organize_file's collision handling, duplicate resolution) hardcodes ".nsp" anywhere;
it all reads `file_obj.extension` off the row. Most of this session's own tests still
default to nsp fixtures for brevity, so this file specifically re-runs a few of the
same real scenarios against xci/xcz to have concrete, executed proof - not just code
inspection - that the format doesn't matter to any of it.
"""
import os
import types

import pytest

import db as db_mod
import titledb
from app import create_app
from constants import (ALLOWED_EXTENSIONS, COMPRESS_EXT, DECOMPRESS_EXT,
                       APP_TYPE_BASE, APP_TYPE_DLC)
from containers.verification import VERIFY_EXT
from db import Apps, Files, Libraries, Titles, db, init_db
from library import (automatic_duplicate_winner, duplicate_winner_preferring_largest,
                     organize_file, resolve_duplicate_files)

TITLE_ID = "0100000000010000"

ORGANIZER_SETTINGS = {
    "templates": {
        "base": "{titleName}/{titleName} [{appId}][v{appVersion}]",
        "update": "{titleName}/{titleName} [{appId}][v{appVersion}]",
        "dlc": "{titleName}/DLC/{appName} [{appId}][v{appVersion}]",
        "multi": "{titleName}/{titleName} [{titleId}]",
    },
    "windows_compatible": False,
    "clean_names": False,
    "name_region": "",
    "name_language": "",
}


def test_all_four_formats_are_allowed_for_scanning():
    assert set(ALLOWED_EXTENSIONS) == {"nsp", "nsz", "xci", "xcz"}


def test_compress_and_decompress_maps_cover_both_container_types():
    assert COMPRESS_EXT == {"nsp": "nsz", "xci": "xcz"}
    assert DECOMPRESS_EXT == {"nsz": "nsp", "xcz": "xci"}


def test_verify_ext_covers_all_four_formats():
    """The set verification actually applies to - not just what gets discovered."""
    assert VERIFY_EXT == {"nsp", "xci", "nsz", "xcz"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    lib_dir = tmp_path / "games"
    lib_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))

    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    ctx = app.app_context()
    ctx.push()
    init_db(app)

    import json
    region_file = titledb_dir / "titles.US.en.json"
    region_file.write_text(json.dumps({TITLE_ID: {"id": TITLE_ID, "name": "Game"}}))
    (titledb_dir / "cnmts.json").write_text("{}")
    (titledb_dir / "versions.json").write_text("{}")
    titledb.store.import_from_json(str(region_file), "US.en")

    library_row = Libraries(path=str(lib_dir))
    db.session.add(library_row)
    db.session.flush()
    title_row = Titles(title_id=TITLE_ID, have_base=True)
    db.session.add(title_row)
    db.session.flush()
    app_row = Apps(title_id=title_row.id, app_id=TITLE_ID, app_version="0",
                   app_type=APP_TYPE_BASE, owned=True)
    db.session.add(app_row)
    db.session.commit()

    def seed(filename, content=b"CONTENT", **columns):
        path = lib_dir / filename
        path.write_bytes(content)
        extension = filename.rsplit(".", 1)[-1]
        f = Files(library_id=library_row.id, filepath=str(path), folder=str(lib_dir),
                 filename=filename, extension=extension, size=len(content),
                 identified=True, **columns)
        db.session.add(f)
        db.session.flush()
        app_row.files.append(f)
        db.session.commit()
        return f

    yield types.SimpleNamespace(app=app, lib_dir=lib_dir, seed=seed)
    ctx.pop()


VALID = dict(signature_valid=True, hash_valid=True)
CORRUPT = dict(signature_valid=True, hash_valid=False, hash_modified=False)


@pytest.mark.parametrize("extension", ["nsp", "xci", "nsz", "xcz"])
def test_collision_handling_gets_a_numbered_suffix_for_every_format(env, extension):
    """The exact "don't silently delete a new file on a same-size collision" fix from
    earlier in this session, re-run for each format - the collision logic reads
    file_obj.extension, so it must behave identically regardless of container type."""
    target_dir = env.lib_dir / "Game"
    target_dir.mkdir()
    correct_name = f"Game [0100000000010000][v0].{extension}"
    (target_dir / correct_name).write_bytes(b"CORRUPT!!")  # 9 bytes, already there

    new_file = env.seed(f"Incoming.{extension}", content=b"HEALTHY!!")  # also 9 bytes

    result = organize_file(new_file, str(env.lib_dir), ORGANIZER_SETTINGS)

    assert result is True
    db.session.refresh(new_file)
    assert new_file.filepath == str(target_dir / f"Game [0100000000010000][v0](2).{extension}")
    assert (target_dir / correct_name).read_bytes() == b"CORRUPT!!"  # untouched
    assert db.session.get(Files, new_file.id) is not None  # never deleted


@pytest.mark.parametrize("extension", ["nsp", "xci", "nsz", "xcz"])
def test_duplicate_resolution_keeps_the_valid_copy_for_every_format(env, extension):
    valid = env.seed(f"Good.{extension}", content=b"GOOD", **VALID)
    corrupt = env.seed(f"Bad.{extension}", content=b"BADBAD", **CORRUPT)
    corrupt_path = corrupt.filepath

    winner = automatic_duplicate_winner([valid, corrupt])
    assert winner.id == valid.id

    resolve_duplicate_files(valid.id, [valid.id, corrupt.id])

    assert os.path.exists(valid.filepath)
    assert not os.path.exists(corrupt_path)


def test_a_mixed_nsp_and_nsz_duplicate_group_is_handled_but_size_favors_the_bigger_uncompressed_one(env):
    """Documents a real, worth-knowing nuance: if the exact same game legitimately
    exists as both an uncompressed and a compressed copy (not created by this app's
    own compression, which always reuses the same row - see compress_file_task's own
    docstring - but e.g. a separately-downloaded release), both independently verifying
    as Valid makes them a tie. `duplicate_winner_preferring_largest` breaks a tie by
    raw byte size, and a compressed .nsz is inherently smaller than the equivalent
    .nsp - so a pure size tiebreak keeps the *uncompressed* copy, not necessarily the
    one a person with compression enabled would actually want. This is expected
    behavior for a byte-size-only tiebreak, not a bug - and it's exactly why
    `duplicate_winner_with_preferences` (see test_duplicate_resolution.py) exists: a
    person who cares about this uses `compression_preference` instead, which settles
    it correctly regardless of which side is bigger."""
    uncompressed = env.seed("Game.nsp", content=b"UNCOMPRESSED-BUT-BIGGER", **VALID)
    compressed = env.seed("Game.nsz", content=b"SMALL", **VALID)  # smaller, same content

    winner = duplicate_winner_preferring_largest([uncompressed, compressed])

    assert winner.id == uncompressed.id  # the size-only tiebreak is compression-blind


def test_compression_preference_resolves_the_same_mixed_group_correctly(env):
    """The actual fix for the nuance above: with compression_preference set, the same
    mixed NSP+NSZ group resolves to whichever side is preferred, regardless of size."""
    from library import duplicate_winner_with_preferences

    uncompressed = env.seed("Game.nsp", content=b"UNCOMPRESSED-BUT-BIGGER",
                            compressed=False, **VALID)
    compressed = env.seed("Game.nsz", content=b"SMALL", compressed=True, **VALID)

    winner = duplicate_winner_with_preferences(
        [uncompressed, compressed], compression_preference="compressed")

    assert winner.id == compressed.id

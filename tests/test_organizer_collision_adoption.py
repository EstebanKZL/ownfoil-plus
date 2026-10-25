"""organize_file()'s collision handling used to treat a same-size file already sitting
at the target path as "this is the same content" and silently delete/merge based on
that alone. That was unsafe: a freshly re-downloaded, healthy file can easily match a
corrupt file's declared size (corruption often doesn't change the container's expected
byte count), and the size-based logic would delete the new, good file and keep the old,
corrupt one - the exact scenario a user reported actually happening.

The fix removes that logic entirely. Every collision - regardless of whether the sizes
happen to match - now always gets a numbered "(n)" suffix, so nothing is ever deleted
or silently merged at organize time. Consolidating genuine duplicates afterward is the
job of the separate, verification-based duplicate-resolution system (see
test_duplicate_resolution.py), which never guesses from size alone and never acts
until both copies have a real verdict.
"""
import json
import types

import pytest

import db as db_mod
import titledb
from app import create_app
from constants import APP_TYPE_DLC
from db import Apps, Files, Libraries, Titles, db, init_db
from library import organize_file

TITLE_ID = "0100000000010000"
DLC_A_ID = "0100000000010001"

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

    region_file = titledb_dir / "titles.US.en.json"
    region_file.write_text(json.dumps({
        TITLE_ID: {"id": TITLE_ID, "name": "Game"},
        DLC_A_ID: {"id": DLC_A_ID, "name": "Costume Pack A"},
    }))
    (titledb_dir / "cnmts.json").write_text("{}")
    (titledb_dir / "versions.json").write_text("{}")
    titledb.store.import_from_json(str(region_file), "US.en")

    library_row = Libraries(path=str(lib_dir))
    db.session.add(library_row)
    db.session.flush()
    title_row = Titles(title_id=TITLE_ID, have_base=True)
    db.session.add(title_row)
    db.session.flush()

    def seed_dlc(app_id, filename, content=b"CONTENT", app_row=None, **columns):
        if app_row is None:
            app_row = Apps(title_id=title_row.id, app_id=app_id, app_version="0",
                           app_type=APP_TYPE_DLC, owned=True)
            db.session.add(app_row)
        path = lib_dir / filename
        path.write_bytes(content)
        file_row = Files(library_id=library_row.id, filepath=str(path), folder=str(lib_dir),
                         filename=filename, extension="nsp", size=len(content),
                         identified=True, **columns)
        db.session.add(file_row)
        db.session.flush()
        app_row.files.append(file_row)
        db.session.commit()
        return file_row

    yield types.SimpleNamespace(app=app, lib_dir=lib_dir, seed_dlc=seed_dlc)
    ctx.pop()


def test_a_same_size_collision_gets_suffixed_not_deleted(env):
    """The exact bug reported: a corrupt file already sits under the correct name. A
    freshly re-downloaded, healthy file happens to be the exact same declared size
    (unsurprising - corruption rarely changes the container's expected byte count).
    The new file must survive as a numbered-suffix sibling, never be deleted."""
    target_dir = env.lib_dir / "Game" / "DLC"
    target_dir.mkdir(parents=True)
    correct_name = "Costume Pack A [0100000000010001][v0].nsp"
    (target_dir / correct_name).write_bytes(b"CORRUPT!!")  # 9 bytes, already Corrupt

    new_file = env.seed_dlc(DLC_A_ID, "FreshDownload.nsp", content=b"HEALTHY!!")  # also 9 bytes

    result = organize_file(new_file, str(env.lib_dir), ORGANIZER_SETTINGS)

    assert result is True
    db.session.refresh(new_file)
    # Both files survive - the new one under a suffix, the old one untouched.
    assert (target_dir / correct_name).read_bytes() == b"CORRUPT!!"
    assert new_file.filepath == str(target_dir / "Costume Pack A [0100000000010001][v0](2).nsp")
    assert (target_dir / "Costume Pack A [0100000000010001][v0](2).nsp").read_bytes() == b"HEALTHY!!"
    # And the Files row for the new file was never deleted.
    assert db.session.get(Files, new_file.id) is not None


def test_a_same_size_collision_does_not_touch_the_existing_files_row(env):
    """The old file's own Files row (and its verification verdict) must be completely
    unaffected by a same-size collision - no repointing, no deletion."""
    target_dir = env.lib_dir / "Game" / "DLC"
    target_dir.mkdir(parents=True)
    correct_name = "Costume Pack A [0100000000010001][v0].nsp"
    existing_path = target_dir / correct_name
    existing_path.write_bytes(b"CORRUPT!!")
    existing = env.seed_dlc(DLC_A_ID, "placeholder-never-used.nsp",
                            content=b"CORRUPT!!", signature_valid=True, hash_valid=False)
    existing.filepath, existing.filename, existing.folder = str(existing_path), correct_name, str(target_dir)
    db.session.commit()
    existing_id = existing.id

    from db import Apps as ApsModel
    same_app = ApsModel.query.filter_by(app_id=DLC_A_ID).first()
    new_file = env.seed_dlc(DLC_A_ID, "FreshDownload.nsp", content=b"HEALTHY!!", app_row=same_app)

    organize_file(new_file, str(env.lib_dir), ORGANIZER_SETTINGS)

    still_there = db.session.get(Files, existing_id)
    assert still_there.filepath == str(existing_path)
    assert still_there.hash_valid is False  # untouched - still correctly marked Corrupt


def test_repeated_organize_of_a_genuinely_unique_file_stays_stable(env):
    """The unaffected, still-important case: a file with no collision at all must
    settle on its plain name and stay there across repeated organize calls."""
    f = env.seed_dlc(DLC_A_ID, "Original.nsp")

    for _ in range(5):
        assert organize_file(f, str(env.lib_dir), ORGANIZER_SETTINGS) is True
        db.session.refresh(f)

    target_dir = env.lib_dir / "Game" / "DLC"
    assert sorted(p.name for p in target_dir.iterdir()) == [
        "Costume Pack A [0100000000010001][v0].nsp"
    ]


def test_a_second_scan_of_an_already_suffixed_file_does_not_pile_on_another_suffix(env):
    """Once a file has settled at "(2)", re-running organize_file on it again (e.g. a
    later rescan) must recognize it's already exactly where it belongs and stop -
    never grow to "(2)(3)" or similar."""
    target_dir = env.lib_dir / "Game" / "DLC"
    target_dir.mkdir(parents=True)
    correct_name = "Costume Pack A [0100000000010001][v0].nsp"
    (target_dir / correct_name).write_bytes(b"OTHER-CONTENT")

    f = env.seed_dlc(DLC_A_ID, "Incoming.nsp", content=b"MY-CONTENT")
    organize_file(f, str(env.lib_dir), ORGANIZER_SETTINGS)
    db.session.refresh(f)
    assert f.filepath == str(target_dir / "Costume Pack A [0100000000010001][v0](2).nsp")

    # Re-running must be a stable no-op from here.
    result = organize_file(f, str(env.lib_dir), ORGANIZER_SETTINGS)
    db.session.refresh(f)

    assert result is True
    assert f.filepath == str(target_dir / "Costume Pack A [0100000000010001][v0](2).nsp")
    assert sorted(p.name for p in target_dir.iterdir()) == sorted([
        "Costume Pack A [0100000000010001][v0].nsp",
        "Costume Pack A [0100000000010001][v0](2).nsp",
    ])


def test_genuinely_different_size_content_still_gets_a_suffix(env):
    """The always-correct baseline case, unchanged by this fix: different content at
    the target name gets suffixed, not overwritten."""
    target_dir = env.lib_dir / "Game" / "DLC"
    target_dir.mkdir(parents=True)
    correct_name = "Costume Pack A [0100000000010001][v0].nsp"
    (target_dir / correct_name).write_bytes(b"DIFFERENT-CONTENT-LONGER")

    f = env.seed_dlc(DLC_A_ID, "Incoming.nsp", content=b"CONTENT")

    result = organize_file(f, str(env.lib_dir), ORGANIZER_SETTINGS)

    assert result is True
    db.session.refresh(f)
    assert f.filepath == str(target_dir / "Costume Pack A [0100000000010001][v0](2).nsp")
    assert (target_dir / correct_name).exists()
    assert (target_dir / "Costume Pack A [0100000000010001][v0](2).nsp").exists()

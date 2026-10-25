"""organize_file() renaming under an alternate naming language, independent of the
library's display locale. Builds a real titles.db (display locale) plus a real
organizer_names import (naming locale), then runs the actual organizer against them.
"""
import json
import os
import types

import pytest

import db as db_mod
import titledb
import titles as titles_lib
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC
from db import Apps, Files, Libraries, Titles, db, init_db
from library import organize_file, organizer_name_locale

TITLE_ID = "0100000000010000"
DLC_ID = "0100000000010001"

DEFAULT_ORGANIZER_SETTINGS = {
    "templates": {
        "base": "{titleName}/{titleName} [{appId}][v{appVersion}]",
        "update": "{titleName}/{titleName} [{appId}][v{appVersion}]",
        "dlc": "{titleName}/{appName} [{appId}][v{appVersion}]",
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

    # Display locale (Spanish name), imported the normal way.
    region_file = titledb_dir / "titles.ES.es.json"
    region_file.write_text(json.dumps({
        TITLE_ID: {"id": TITLE_ID, "name": "Kirby y la Tierra Olvidada"},
        DLC_ID: {"id": DLC_ID, "name": "Kirby y la Tierra Olvidada: DLC"},
    }))
    (titledb_dir / "cnmts.json").write_text("{}")
    (titledb_dir / "versions.json").write_text("{}")
    titledb.store.import_from_json(str(region_file), "ES.es")

    library_row = Libraries(path=str(lib_dir))
    db.session.add(library_row)
    db.session.flush()
    title_row = Titles(title_id=TITLE_ID, have_base=True)
    db.session.add(title_row)
    db.session.flush()

    def seed_base_app(filename="Game.nsp"):
        app_row = Apps(title_id=title_row.id, app_id=TITLE_ID, app_version="0",
                       app_type=APP_TYPE_BASE, owned=True)
        db.session.add(app_row)
        path = lib_dir / filename
        path.write_bytes(b"RAWDATA")
        file_row = Files(library_id=library_row.id, filepath=str(path), folder=str(lib_dir),
                         filename=filename, extension="nsp", size=7, identified=True)
        db.session.add(file_row)
        db.session.flush()
        app_row.files.append(file_row)
        db.session.commit()
        return file_row

    def seed_dlc_app(filename="GameDLC.nsp"):
        app_row = Apps(title_id=title_row.id, app_id=DLC_ID, app_version="0",
                       app_type=APP_TYPE_DLC, owned=True)
        db.session.add(app_row)
        path = lib_dir / filename
        path.write_bytes(b"RAWDATA")
        file_row = Files(library_id=library_row.id, filepath=str(path), folder=str(lib_dir),
                         filename=filename, extension="nsp", size=7, identified=True)
        db.session.add(file_row)
        db.session.flush()
        app_row.files.append(file_row)
        db.session.commit()
        return file_row

    def import_organizer_locale(region, language, names):
        path = titledb_dir / f"titles.{region}.{language}.json"
        path.write_text(json.dumps(names))
        titledb.store.import_organizer_names(str(path), f"{region}.{language}")

    yield types.SimpleNamespace(
        app=app, lib_dir=lib_dir, seed_base_app=seed_base_app, seed_dlc_app=seed_dlc_app,
        import_organizer_locale=import_organizer_locale,
    )
    ctx.pop()


def test_disabled_by_default_uses_the_display_language_name(env):
    file_row = env.seed_base_app()

    organize_file(file_row, str(env.lib_dir), DEFAULT_ORGANIZER_SETTINGS)

    assert "Kirby y la Tierra Olvidada" in file_row.filepath


def test_configured_naming_language_overrides_the_display_name(env):
    env.import_organizer_locale("GB", "en", {
        TITLE_ID: {"id": TITLE_ID, "name": "Kirby and the Forgotten Land"},
    })
    file_row = env.seed_base_app()
    settings = dict(DEFAULT_ORGANIZER_SETTINGS, name_region="GB", name_language="en")

    organize_file(file_row, str(env.lib_dir), settings)

    assert "Kirby and the Forgotten Land" in file_row.filepath
    assert "Kirby y la Tierra Olvidada" not in file_row.filepath


def test_dlc_uses_its_own_alternate_name_not_the_titles(env):
    env.import_organizer_locale("GB", "en", {
        TITLE_ID: {"id": TITLE_ID, "name": "Kirby and the Forgotten Land"},
        DLC_ID: {"id": DLC_ID, "name": "Kirby and the Forgotten Land: Bonus Pack"},
    })
    file_row = env.seed_dlc_app()
    settings = dict(DEFAULT_ORGANIZER_SETTINGS, name_region="GB", name_language="en")

    organize_file(file_row, str(env.lib_dir), settings)

    # dlc template: {titleName}/{appName} [...] - title folder in the alt title name,
    # filename in the DLC's own alt name.
    assert "Kirby and the Forgotten Land" in file_row.filepath
    assert "Bonus Pack" in file_row.filepath


def test_falls_back_to_display_name_when_alternate_locale_not_yet_imported(env):
    """The setting is configured but titledb hasn't imported that locale yet (or the
    import failed) - must not error, and must not risk an empty/wrong name."""
    file_row = env.seed_base_app()
    settings = dict(DEFAULT_ORGANIZER_SETTINGS, name_region="GB", name_language="en")

    organize_file(file_row, str(env.lib_dir), settings)

    assert "Kirby y la Tierra Olvidada" in file_row.filepath


def test_falls_back_when_stored_locale_does_not_match_requested(env):
    """organizer_names holds a stale locale (e.g. settings changed since the last
    titledb update) - must not apply that mismatched locale's name."""
    env.import_organizer_locale("FR", "fr", {
        TITLE_ID: {"id": TITLE_ID, "name": "Kirby et la Terre Oubliee"},
    })
    file_row = env.seed_base_app()
    settings = dict(DEFAULT_ORGANIZER_SETTINGS, name_region="GB", name_language="en")

    organize_file(file_row, str(env.lib_dir), settings)

    assert "Kirby y la Tierra Olvidada" in file_row.filepath
    assert "Kirby et la Terre Oubliee" not in file_row.filepath


def test_only_region_or_only_language_set_is_treated_as_disabled(env):
    env.import_organizer_locale("GB", "en", {
        TITLE_ID: {"id": TITLE_ID, "name": "Kirby and the Forgotten Land"},
    })
    file_row = env.seed_base_app()
    settings = dict(DEFAULT_ORGANIZER_SETTINGS, name_region="GB", name_language="")

    organize_file(file_row, str(env.lib_dir), settings)

    assert "Kirby y la Tierra Olvidada" in file_row.filepath


# ------------- organizer_name_locale() unit tests -------------

@pytest.mark.parametrize("region, language, expected", [
    ("GB", "en", "GB.en"),
    ("", "en", None),
    ("GB", "", None),
    ("", "", None),
    (None, None, None),
])
def test_organizer_name_locale(region, language, expected):
    settings = {"name_region": region, "name_language": language}
    assert organizer_name_locale(settings) == expected


def test_organizer_name_locale_defaults_to_disabled_when_keys_absent():
    assert organizer_name_locale({}) is None

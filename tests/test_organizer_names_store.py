"""Real end-to-end tests for `organizer_names`: importing a second locale's JSON and
reading it back, including the locale-mismatch guard that keeps a caller from getting a
stale/wrong-language name while a background titledb update catches up.
"""
import json
import types

import pytest

import db as db_mod
import titledb
from app import create_app
from db import init_db

TITLE_ID = "0100000000010000"


@pytest.fixture
def install(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    with app.app_context():
        init_db(app)
    return types.SimpleNamespace(app=app, titledb_dir=titledb_dir)


def _write_region_file(install, name, records):
    path = install.titledb_dir / name
    path.write_text(json.dumps(records))
    return str(path)


def test_import_and_lookup_round_trip(install):
    path = _write_region_file(install, "titles.GB.en.json", {
        TITLE_ID: {"id": TITLE_ID, "name": "Kirby and the Forgotten Land"},
    })
    with install.app.app_context():
        titledb.store.import_organizer_names(path, "GB.en")
        assert titledb.store.get_organizer_names_locale() == "GB.en"
        assert titledb.store.get_organizer_name(TITLE_ID, "GB.en") == "Kirby and the Forgotten Land"


def test_lookup_returns_none_for_a_different_locale_than_requested(install):
    """Guards against a stale import: the caller asked for a locale that isn't what's
    actually stored, so it must fall back rather than risk a wrong-language name."""
    path = _write_region_file(install, "titles.GB.en.json", {
        TITLE_ID: {"id": TITLE_ID, "name": "Kirby and the Forgotten Land"},
    })
    with install.app.app_context():
        titledb.store.import_organizer_names(path, "GB.en")
        assert titledb.store.get_organizer_name(TITLE_ID, "FR.fr") is None


def test_lookup_returns_none_before_anything_is_imported(install):
    with install.app.app_context():
        assert titledb.store.get_organizer_names_locale() is None
        assert titledb.store.get_organizer_name(TITLE_ID, "GB.en") is None


def test_lookup_returns_none_for_an_id_not_in_the_imported_file(install):
    path = _write_region_file(install, "titles.GB.en.json", {
        TITLE_ID: {"id": TITLE_ID, "name": "Kirby and the Forgotten Land"},
    })
    with install.app.app_context():
        titledb.store.import_organizer_names(path, "GB.en")
        assert titledb.store.get_organizer_name("0100000000099999", "GB.en") is None


def test_reimporting_a_new_locale_replaces_the_previous_one(install):
    """organizer_names holds exactly one locale at a time - switching languages must not
    leave the old locale's rows queryable under the new locale's name."""
    path_gb = _write_region_file(install, "titles.GB.en.json", {
        TITLE_ID: {"id": TITLE_ID, "name": "English Name"},
    })
    path_fr = _write_region_file(install, "titles.FR.fr.json", {
        TITLE_ID: {"id": TITLE_ID, "name": "Nom Francais"},
    })
    with install.app.app_context():
        titledb.store.import_organizer_names(path_gb, "GB.en")
        titledb.store.import_organizer_names(path_fr, "FR.fr")

        assert titledb.store.get_organizer_names_locale() == "FR.fr"
        assert titledb.store.get_organizer_name(TITLE_ID, "FR.fr") == "Nom Francais"
        # Asking under the old locale correctly finds nothing - it is no longer stored.
        assert titledb.store.get_organizer_name(TITLE_ID, "GB.en") is None


def test_records_without_an_id_or_name_are_skipped(install):
    path = _write_region_file(install, "titles.GB.en.json", {
        TITLE_ID: {"id": TITLE_ID, "name": "Has A Name"},
        "broken1": {"id": "0100000000099999"},          # no name
        "broken2": {"name": "No Id"},                     # no id
        "not_a_dict": "garbage",
    })
    with install.app.app_context():
        titledb.store.import_organizer_names(path, "GB.en")
        assert titledb.store.get_organizer_name(TITLE_ID, "GB.en") == "Has A Name"
        assert titledb.store.get_organizer_name("0100000000099999", "GB.en") is None


def test_import_raises_for_a_missing_file(install):
    with install.app.app_context():
        with pytest.raises(FileNotFoundError):
            titledb.store.import_organizer_names(
                str(install.titledb_dir / "does-not-exist.json"), "GB.en")

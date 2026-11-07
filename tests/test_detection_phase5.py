"""Phase 5, part B: detection and counts as Switch Library Manager Web reads them.

- A file whose contents can't be read (a missing master key, a damaged header) is still
  identified by its name ([TitleID][vVersion]), as SLMW does, instead of staying
  unidentified.
- A DLC counts as missing only when no version of it is in the library; one with a
  newer version is a pending update, counted apart: "66 updates: 50 games and 16 DLC".
"""
import json
import types

import pytest

import db as db_mod
import titledb
import titles as titles_lib
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC, APP_TYPE_UPD
from db import Apps, Titles, db, init_db
from gql import graphql_dispatch

GAME = "0100AAAA00010000"
DLC_OLD = "0100AAAA00011001"      # owned at v0, v65536 exists: a DLC update pending
DLC_MISSING = "0100AAAA00011002"  # not owned at all
OTHER = "0100BBBB00010000"
OTHER_DLC = "0100BBBB00011001"    # owned at v0, v65536 exists - and nothing missing


# --- identification ------------------------------------------------------------------------

def _cnmt_fails(monkeypatch):
    monkeypatch.setattr(titles_lib.Keys, "keys_loaded", True, raising=False)

    def boom(fp):
        raise ValueError("Missing valid master_key_21")
    monkeypatch.setattr(titles_lib, "identify_file_from_cnmt", boom)


def test_a_file_whose_contents_cant_be_read_is_identified_by_its_name(monkeypatch):
    _cnmt_fails(monkeypatch)
    identification, success, contents, error = titles_lib.identify_file(
        f"/games/Game [{GAME}][v0].nsp")
    assert success and identification == "filename"
    assert contents[0]["app_id"] == GAME and contents[0]["version"] == "0"
    assert not error


def test_without_a_usable_name_the_contents_error_stays(monkeypatch):
    _cnmt_fails(monkeypatch)
    identification, success, contents, error = titles_lib.identify_file("/games/Some game.nsp")
    assert not success and not contents
    assert "master_key_21" in error


# --- counts ---------------------------------------------------------------------------------

@pytest.fixture
def library(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    app.add_url_rule("/api/graphql", view_func=graphql_dispatch, methods=["GET", "POST"])
    init_db(app)
    titledb.store.create_titledb(str(config / "titles.db"))
    rows = {
        GAME: [(GAME, "0", APP_TYPE_BASE, True), (GAME[:-3] + "800", "65536", APP_TYPE_UPD, False),
               (DLC_OLD, "0", APP_TYPE_DLC, True), (DLC_OLD, "65536", APP_TYPE_DLC, False),
               (DLC_MISSING, "0", APP_TYPE_DLC, False)],
        OTHER: [(OTHER, "0", APP_TYPE_BASE, True),
                (OTHER_DLC, "0", APP_TYPE_DLC, True), (OTHER_DLC, "65536", APP_TYPE_DLC, False)],
    }
    with app.app_context():
        for title_id, apps in rows.items():
            title = Titles(title_id=title_id, have_base=True)
            db.session.add(title)
            db.session.flush()
            for app_id, version, kind, owned in apps:
                db.session.add(Apps(title_id=title.id, app_id=app_id, app_version=version,
                                    app_type=kind, owned=owned))
        db.session.commit()
        from library import update_titles
        update_titles()
    return types.SimpleNamespace(app=app, client=app.test_client())


def test_a_dlc_with_a_newer_version_is_not_a_missing_dlc(library):
    with library.app.app_context():
        assert Titles.query.filter_by(title_id=OTHER).one().complete is True
        assert Titles.query.filter_by(title_id=GAME).one().complete is False   # DLC_MISSING


def test_the_stats_count_dlc_updates_and_missing_dlc(library):
    query = "{ stats { ownedTitles upToDateTitles completeTitles outdatedDlc missingDlc } }"
    resp = library.client.get("/api/graphql", query_string={"query": query})
    stats = resp.get_json()["data"]["stats"]
    assert stats["ownedTitles"] == 2 and stats["upToDateTitles"] == 1 and stats["completeTitles"] == 1
    assert stats["outdatedDlc"] == 2           # DLC_OLD and OTHER_DLC
    assert stats["missingDlc"] == 1            # DLC_MISSING


def test_the_library_tiles_count_updates_for_games_only():
    # Phase 7: "Pending updates" is base games only (owned - up to date), so it always
    # matches the "up to date" bar; DLC count only under missing DLC.
    import os
    root = os.path.join(os.path.dirname(__file__), "..")
    js = open(os.path.join(root, "app", "static", "js", "library.js"), encoding="utf-8").read()
    query = js[js.index("const LIBRARY_STATS_QUERY"):js.index("`;", js.index("const LIBRARY_STATS_QUERY"))]
    assert "missingDlc" in query and "outdatedDlc" not in query
    body = js[js.index("function renderLibraryStats("):js.index("function ", js.index("function renderLibraryStats(") + 10)]
    # No notes under the updates and missing-DLC figures (asked for: just the number).
    assert "tileUpdatesNote" not in body and "tileMissingDlcNote" not in body
    assert "[pending.toLocaleString(), I18N.tileUpdates, null," in body
    assert "'bi-controller', 'ok', 'all', null]" in body      # the Games tile applies "All"
    # Total size leads to Stats.
    assert "'/admin/stats']" in body and "'<a>'" in body
    from i18n import TRANSLATIONS
    for key in ("library.tile_dlc_missing",):
        assert TRANSLATIONS[key]["en"] and TRANSLATIONS[key]["es"], key

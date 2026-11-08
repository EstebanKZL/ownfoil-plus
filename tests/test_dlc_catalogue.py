"""A game's DLC come from the catalogue by title ID, not only from cnmts.json.

cnmts.json only has the DLC someone dumped: Biomutant's nine language packs are in
titles.json and none of them in cnmts.json, so the game read as "complete". A DLC's id
is its game's id plus 0x1000 plus an index (1-0xFFF) - the same grouping Switch Library
Manager Web uses - so every DLC titles.json lists is found, with what cnmts.json adds.
"""
import json
import types

import pytest

import db as db_mod
import titledb
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC
from db import Apps, Titles, db, init_db
from gql import graphql_dispatch

GAME = "0100AAAA00010000"
UPDATE = "0100AAAA00010800"
DLC_DUMPED = "0100AAAA00011001"       # in titles.json and in cnmts.json
DLC_LISTED = "0100AAAA00011002"       # in titles.json only (like Biomutant's)
OTHER_GAME = "0100AAAA00012000"
OTHER_DLC = "0100AAAA00013001"        # the next game's DLC, never this one's

TITLES = {
    GAME: {"id": GAME, "name": "Mutant Game", "releaseDate": "20240514"},
    UPDATE: {"id": UPDATE, "name": None},
    DLC_DUMPED: {"id": DLC_DUMPED, "name": "Dumped DLC", "releaseDate": "20240601", "size": 1000},
    DLC_LISTED: {"id": DLC_LISTED, "name": "Spanish Language DLC", "releaseDate": "20240514",
                 "description": "Adds Spanish.", "size": 2000},
    OTHER_GAME: {"id": OTHER_GAME, "name": "Other Game"},
    OTHER_DLC: {"id": OTHER_DLC, "name": "Other DLC"},
}
CNMTS = {
    DLC_DUMPED.lower(): {"65536": {"titleId": DLC_DUMPED.lower(), "titleType": 130, "version": 65536,
                                   "otherApplicationId": GAME.lower()}},
}


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    app.add_url_rule("/api/graphql", view_func=graphql_dispatch, methods=["GET", "POST"])
    init_db(app)
    region = titledb_dir / "titles.US.en.json"
    region.write_text(json.dumps(TITLES))
    (titledb_dir / "cnmts.json").write_text(json.dumps(CNMTS))
    (titledb_dir / "versions.json").write_text("{}")
    with app.app_context():
        titledb.store.import_from_json(str(region), "US.en")
        title = Titles(title_id=GAME, have_base=True, up_to_date=True, complete=True)
        db.session.add(title)
        db.session.flush()
        db.session.add(Apps(title_id=title.id, app_id=GAME, app_version="0", app_type=APP_TYPE_BASE, owned=True))
        db.session.commit()
    return types.SimpleNamespace(app=app, client=app.test_client())


def test_every_dlc_the_catalogue_lists_is_found(catalogue):
    with catalogue.app.app_context():
        assert sorted(titledb.store.get_all_existing_dlc(GAME)) == [DLC_DUMPED, DLC_LISTED]


def test_a_listed_dlc_has_version_zero_and_its_release_date(catalogue):
    with catalogue.app.app_context():
        found = {app_id: (int(version), date) for app_id, version, date in titledb.store.get_all_dlc_versions(GAME)}
    assert found == {DLC_DUMPED: (65536, "2024-06-01"), DLC_LISTED: (0, "2024-05-14")}


def test_the_update_and_other_games_dlc_never_count(catalogue):
    with catalogue.app.app_context():
        assert OTHER_DLC not in titledb.store.get_all_existing_dlc(GAME)
        assert titledb.store.get_all_existing_dlc(OTHER_GAME) == [OTHER_DLC]
        assert UPDATE not in titledb.store.get_all_existing_dlc(GAME)


def test_a_game_missing_a_listed_dlc_is_not_complete(catalogue):
    from library import add_missing_apps_for_title, update_titles
    with catalogue.app.app_context():
        add_missing_apps_for_title(GAME)
        dlc = {a.app_id for a in Apps.query.filter_by(app_type=APP_TYPE_DLC)}
        assert dlc == {DLC_DUMPED, DLC_LISTED}
        update_titles()
        assert Titles.query.filter_by(title_id=GAME).one().complete is False


def test_the_game_page_lists_every_dlc_with_its_metadata(catalogue):
    query = """query($id: ID!) { title(titleId: $id) {
        availableDlc { appId version titledb { name description releaseDate size } } } }"""
    resp = catalogue.client.get("/api/graphql", query_string={
        "query": query, "variables": json.dumps({"id": GAME})})
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    dlc = {d["appId"]: d for d in body["data"]["title"]["availableDlc"]}
    assert set(dlc) == {DLC_DUMPED, DLC_LISTED}
    assert dlc[DLC_LISTED]["version"] == 0
    assert dlc[DLC_LISTED]["titledb"]["name"] == "Spanish Language DLC"
    assert dlc[DLC_LISTED]["titledb"]["description"] == "Adds Spanish."
    assert dlc[DLC_DUMPED]["version"] == 65536


def test_the_first_catalogue_pass_does_not_announce_old_dlc(catalogue, monkeypatch):
    """The DLC the catalogue adds were always there: announcing them as new would send
    one notification per DLC of every game, once. Later passes announce as before."""
    import library
    import notifications
    from settings import get_settings
    sent = []
    monkeypatch.setattr(notifications, "is_enabled", lambda event: True)
    monkeypatch.setattr(notifications, "notify", lambda event, item, title_id=None: sent.append(item))
    with catalogue.app.app_context():
        library.add_missing_apps_to_db()
        assert sent == []
        assert get_settings()["server"]["catalogue_revision"] == library.CATALOGUE_REVISION
        # A DLC that really is new, on a later pass, is announced.
        new_dlc = "0100AAAA00011003"
        titles_db = titledb.store.TITLES_DB_FILE
        import sqlite3
        with sqlite3.connect(titles_db) as conn:
            conn.execute("INSERT INTO titles(id, name) VALUES (?, ?)", (new_dlc, "Brand new DLC"))
        library.add_missing_apps_to_db()
        assert len(sent) == 1 and "Brand new DLC" in sent[0]

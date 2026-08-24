"""The library page's List view (app/templates/index.html) always shows the full
catalogue picture for a title - every update and DLC ownfoil knows about, cross-
referenced against what's actually owned - rather than only owned content, and
regardless of the toolbar's ownership/up-to-date/complete filters (those only apply to
the Card/Icon views). This pins that query against the real schema so a future change
to `titles`/`apps`/`availableDlc` surfaces here instead of only as a silent blank page
in the browser.

Updates specifically are sourced from `apps(appType: [UPDATE])` - ownfoil's own tracked
apps, owned or not - rather than titledb's raw `availableVersions` catalogue. A user
reported the earlier `availableVersions`-based version showing a contradiction: a green
"up to date" checkmark next to an Updates section listing that same version as Missing,
because titledb's version catalogue sometimes lists a "v0" entry that's really just
documenting the base release's own version, not a separate update package that ownfoil
would ever track as its own App row. `Titles.up_to_date` (the source of that checkmark)
is computed purely from tracked Apps rows, so sourcing the Updates list from the same
place keeps the two from ever disagreeing again.
"""
import json
import types

import pytest

import db as db_mod
import titledb
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC, APP_TYPE_UPD
from db import Apps, Files, Libraries, Titles, db, init_db
from gql import graphql_dispatch

ALPHA = "0100000000AAAAA0"[:16]
ALPHA_UPD_OWNED = ALPHA[:-3] + "800"
ALPHA_UPD_MISSING = ALPHA[:-3] + "801"
ALPHA_DLC_OWNED = ALPHA[:-4] + "1001"
ALPHA_DLC_MISSING = ALPHA[:-4] + "1002"

BETA = "0100000000BBBBB0"[:16]  # the reported scenario: base-only, no real updates

TITLEDB_JSON = {
    ALPHA: {"id": ALPHA, "name": "Alpha Game", "intro": "A great game",
            "description": "Long description", "developer": "Dev Co", "publisher": "Pub Co",
            "bannerUrl": "https://img/banner.jpg", "iconUrl": "https://img/icon.jpg",
            "category": ["Action", "Adventure"], "numberOfPlayers": "1-4", "rating": "Teen",
            "languages": ["en", "es"], "screenshots": ["https://img/s1.jpg", "https://img/s2.jpg"],
            "size": "3.08 GB"},
    ALPHA_DLC_OWNED: {"id": ALPHA_DLC_OWNED, "name": "Owned DLC", "description": "DLC1 desc",
                      "category": ["Action"], "screenshots": ["https://img/dlc1.jpg"]},
    ALPHA_DLC_MISSING: {"id": ALPHA_DLC_MISSING, "name": "Missing DLC", "description": "DLC2 desc"},
    BETA: {"id": BETA, "name": "Darksiders-like Base-Only Game"},
}

# cnmts entries are what _hydrate_titledb_dlc joins on to find every DLC a title has,
# owned or not - keyed by app_id -> cnmt_version -> record, per the real import shape.
CNMTS_JSON = {
    ALPHA_DLC_OWNED.lower(): {
        "0": {"titleId": ALPHA_DLC_OWNED.lower(), "titleType": 130,
              "version": 0, "otherApplicationId": ALPHA.lower()},
    },
    ALPHA_DLC_MISSING.lower(): {
        "0": {"titleId": ALPHA_DLC_MISSING.lower(), "titleType": 130,
              "version": 0, "otherApplicationId": ALPHA.lower()},
    },
}

# BETA deliberately has a version 0 entry here (the same shape that caused the reported
# bug) but - just as deliberately - no corresponding Apps row is ever created for it in
# the fixture below, since real update packages come from cnmts, not versions.json.
VERSIONS_JSON = {
    ALPHA: {"65536": "2021-04-27"},
    BETA: {"0": "2019-04-02"},
}

LIST_QUERY = """
    query TitlesList($page: Int!, $pageSize: Int!, $search: String, $libraryHealth: LibraryHealth) {
        titles(owned: true, search: $search, libraryHealth: $libraryHealth, orderBy: {field: NAME}, page: $page, pageSize: $pageSize) {
            total
            items {
                titleId name intro description developer publisher releaseDate
                bannerUrl iconUrl size category numberOfPlayers rating languages screenshots
                ownership { haveBase upToDate complete }
                apps(owned: true) {
                    appId appType appVersion releaseDate
                    downloadableFile { id size verificationStatus }
                }
                updateApps: apps(appType: [UPDATE]) {
                    appId appVersion releaseDate owned
                    downloadableFile { id size verificationStatus }
                }
                availableDlc {
                    appId version
                    titledb {
                        name description developer publisher releaseDate bannerUrl iconUrl
                        size category numberOfPlayers rating languages screenshots
                    }
                }
            }
        }
    }"""


@pytest.fixture
def library(tmp_path, monkeypatch):
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

    region_file = titledb_dir / "titles.US.en.json"
    region_file.write_text(json.dumps(TITLEDB_JSON))
    (titledb_dir / "cnmts.json").write_text(json.dumps(CNMTS_JSON))
    (titledb_dir / "versions.json").write_text(json.dumps(VERSIONS_JSON))
    with app.app_context():
        titledb.store.import_from_json(str(region_file), "US.en")

        # ALPHA: base + one owned update + one real-but-not-owned update (both tracked
        # as actual Apps rows, as add_missing_apps_for_title would create from cnmts),
        # one owned DLC, one missing DLC.
        alpha = Titles(title_id=ALPHA, have_base=True, up_to_date=False, complete=False)
        # BETA: only a base game, no update ever tracked as a real App row - despite
        # titledb's versions.json listing a "v0" entry for it (the reported scenario).
        beta = Titles(title_id=BETA, have_base=True, up_to_date=True, complete=True)
        db.session.add_all([alpha, beta])
        library_row = Libraries(path=str(tmp_path / "games"))
        db.session.add(library_row)
        db.session.flush()

        alpha_base = Apps(title_id=alpha.id, app_id=ALPHA, app_version="0",
                          app_type=APP_TYPE_BASE, owned=True)
        alpha_update_owned = Apps(title_id=alpha.id, app_id=ALPHA_UPD_OWNED, app_version="65536",
                                  app_type=APP_TYPE_UPD, owned=True, release_date="2021-04-27")
        alpha_update_missing = Apps(title_id=alpha.id, app_id=ALPHA_UPD_MISSING, app_version="131072",
                                    app_type=APP_TYPE_UPD, owned=False, release_date="2022-01-01")
        alpha_dlc_owned = Apps(title_id=alpha.id, app_id=ALPHA_DLC_OWNED, app_version="0",
                               app_type=APP_TYPE_DLC, owned=True)
        beta_base = Apps(title_id=beta.id, app_id=BETA, app_version="0",
                         app_type=APP_TYPE_BASE, owned=True)
        db.session.add_all([alpha_base, alpha_update_owned, alpha_update_missing,
                            alpha_dlc_owned, beta_base])

        alpha_base_file = Files(library_id=library_row.id, filepath=str(tmp_path / "games" / "Alpha.nsp"),
                                filename="Alpha.nsp", extension="nsp", size=6500000, identified=True)
        alpha_update_file = Files(library_id=library_row.id, filepath=str(tmp_path / "games" / "AlphaUpd.nsp"),
                                  filename="AlphaUpd.nsp", extension="nsp", size=450000, identified=True)
        alpha_dlc_file = Files(library_id=library_row.id, filepath=str(tmp_path / "games" / "AlphaDLC.nsp"),
                               filename="AlphaDLC.nsp", extension="nsp", size=200000, identified=True)
        beta_base_file = Files(library_id=library_row.id, filepath=str(tmp_path / "games" / "Beta.nsp"),
                               filename="Beta.nsp", extension="nsp", size=13200000000, identified=True)
        db.session.add_all([alpha_base_file, alpha_update_file, alpha_dlc_file, beta_base_file])
        db.session.flush()
        alpha_base.files.append(alpha_base_file)
        alpha_update_owned.files.append(alpha_update_file)
        alpha_dlc_owned.files.append(alpha_dlc_file)
        beta_base.files.append(beta_base_file)
        db.session.commit()

    return types.SimpleNamespace(app=app, client=app.test_client())


def _run(library, **variables):
    params = {"query": LIST_QUERY, "variables": json.dumps(variables)}
    resp = library.client.get("/api/graphql", query_string=params)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    return body["data"]


def _title(library, name):
    data = _run(library, page=1, pageSize=10, search=name)
    items = data["titles"]["items"]
    assert len(items) == 1, f"expected exactly one title matching {name!r}, got {len(items)}"
    return items[0]


def test_title_level_metadata_and_ownership(library):
    title = _title(library, "Alpha")

    assert title["name"] == "Alpha Game"
    assert title["description"] == "Long description"
    assert title["developer"] == "Dev Co"
    assert title["publisher"] == "Pub Co"
    assert title["ownership"] == {"haveBase": True, "upToDate": False, "complete": False}


def test_owned_apps_carry_downloadable_file_size_and_id(library):
    """downloadableFile is what the download button now reads client-side - shop-safe
    unlike `files`, but should still carry the same id/size for the same app."""
    title = _title(library, "Alpha")

    apps_by_type = {}
    for app in title["apps"]:
        apps_by_type.setdefault(app["appType"], []).append(app)
    assert set(apps_by_type) == {"BASE", "UPDATE", "DLC"}
    base_file = apps_by_type["BASE"][0]["downloadableFile"]
    assert base_file["size"] == 6500000
    assert base_file["id"]  # present and truthy - what a download link targets


def test_update_apps_include_both_owned_and_missing(library):
    """The whole point of the catalogue-complete query: an update nobody owns yet
    still comes back, so the List view can show it as Missing rather than omit it -
    but only when it's a real, ownfoil-tracked update (see the BETA/phantom-v0 test
    below for the case that must NOT show up here)."""
    title = _title(library, "Alpha")

    versions = {a["appVersion"]: (a["releaseDate"], a["owned"]) for a in title["updateApps"]}
    assert versions == {
        65536: ("2021-04-27", True),
        131072: ("2022-01-01", False),
    }


def test_a_titledb_only_version_entry_with_no_tracked_app_does_not_appear(library):
    """The exact bug reported: titledb's versions.json lists a "v0" entry for a title
    that never actually got a separate update package (common - v0 usually just
    documents the base release's own version). Since no real Apps row was ever
    created for it, updateApps must come back empty here - matching
    ownership.upToDate, which is computed the same way and correctly says True."""
    title = _title(library, "Darksiders")

    assert title["updateApps"] == []
    assert title["ownership"]["upToDate"] is True


def test_available_dlc_include_both_owned_and_missing_with_their_own_names(library):
    title = _title(library, "Alpha")

    dlc_by_app_id = {d["appId"]: d["titledb"]["name"] for d in title["availableDlc"]}
    assert dlc_by_app_id == {ALPHA_DLC_OWNED: "Owned DLC", ALPHA_DLC_MISSING: "Missing DLC"}
    owned_dlc_app_ids = {a["appId"] for a in title["apps"] if a["appType"] == "DLC"}
    assert owned_dlc_app_ids == {ALPHA_DLC_OWNED}


def test_the_enriched_metadata_modal_fields_are_available_for_the_base_title(library):
    """The fields the metadata modal's detail rows (Players/Genre/Rating/Languages/
    File size/Screenshots) need, confirmed reachable through the exact List view
    query - not just defined on the GraphQL type."""
    title = _title(library, "Alpha")

    assert title["category"] == ["Action", "Adventure"]
    assert title["numberOfPlayers"] == "1-4"
    assert title["rating"] == "Teen"
    assert title["languages"] == ["en", "es"]
    assert title["screenshots"] == ["https://img/s1.jpg", "https://img/s2.jpg"]
    assert title["size"] == "3.08 GB"


def test_the_enriched_metadata_modal_fields_are_available_for_a_dlc(library):
    title = _title(library, "Alpha")
    owned_dlc = next(d for d in title["availableDlc"] if d["appId"] == ALPHA_DLC_OWNED)

    assert owned_dlc["titledb"]["category"] == ["Action"]
    assert owned_dlc["titledb"]["screenshots"] == ["https://img/dlc1.jpg"]


def test_search_still_narrows_the_list_view(library):
    """Search is the one toolbar control the List view keeps - everything else
    (ownership/up-to-date/complete/type) is deliberately not sent for this query."""
    data = _run(library, page=1, pageSize=10, search="Alpha")
    assert data["titles"]["total"] == 1

    data = _run(library, page=1, pageSize=10, search="Nonexistent")
    assert data["titles"]["total"] == 0


def test_an_owned_dlc_missing_from_titledbs_catalog_still_comes_back_via_apps(library):
    """The data dependency the List view's DLC merge relies on: `apps(owned: true)`
    must keep returning an owned DLC via ownfoil's own tracking (the file's own
    embedded CNMT identification) even when titledb's own catalogue (cnmts.json) has
    no entry linking it to the title at all - `availableDlc` coming back without it in
    that case is titledb's limitation, not a reason for `apps` to omit it too."""
    with library.app.app_context():
        from constants import APP_TYPE_DLC
        title = Titles.query.filter_by(title_id=ALPHA).first()
        library_row = Libraries.query.first()
        # No titledb entry at all for this id - deliberately absent from TITLEDB_JSON.
        unlisted_dlc_id = ALPHA[:-4] + "1099"
        unlisted_app = Apps(title_id=title.id, app_id=unlisted_dlc_id, app_version="0",
                            app_type=APP_TYPE_DLC, owned=True)
        db.session.add(unlisted_app)
        db.session.flush()
        f = Files(library_id=library_row.id, filepath=str(library_row.path) + "/Unlisted.nsp",
                  filename="Unlisted.nsp", extension="nsp", size=999, identified=True)
        db.session.add(f)
        db.session.flush()
        unlisted_app.files.append(f)
        db.session.commit()

    title = _title(library, "Alpha")
    owned_dlc_ids = {a["appId"] for a in title["apps"] if a["appType"] == "DLC"}
    catalogued_dlc_ids = {d["appId"] for d in title["availableDlc"]}

    assert unlisted_dlc_id in owned_dlc_ids       # ownfoil's own tracking has it
    assert unlisted_dlc_id not in catalogued_dlc_ids  # titledb genuinely doesn't


def test_query_has_no_up_to_date_or_complete_filter_arguments():
    """Guards the "always stable, filters don't apply" behavior at the query-shape
    level: the List view's query must not declare $upToDate/$complete at all, so a
    future edit can't accidentally reintroduce toolbar filtering here."""
    assert "$upToDate" not in LIST_QUERY
    assert "$complete" not in LIST_QUERY
    assert "$owned: Boolean" not in LIST_QUERY  # owned is hardcoded true, not a variable


def test_query_sources_updates_from_tracked_apps_not_the_raw_titledb_catalogue():
    """Guards the fix itself at the query-shape level: the Updates section must query
    `apps(appType: [UPDATE])`, never `availableVersions` (titledb's raw catalogue,
    which is what caused the reported contradiction in the first place)."""
    assert "updateApps: apps(appType: [UPDATE])" in LIST_QUERY
    assert "availableVersions" not in LIST_QUERY


def test_query_accepts_the_library_health_filter():
    """The List view's own filter - unlike Card/Icon's ownership/update/completion
    toggles, this one is a single argument evaluating every owned app together."""
    assert "$libraryHealth: LibraryHealth" in LIST_QUERY
    assert "libraryHealth: $libraryHealth" in LIST_QUERY

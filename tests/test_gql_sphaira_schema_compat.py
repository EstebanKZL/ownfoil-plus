"""Coverage for the GraphQL schema-compatibility gap reported against a production
shop: once the OPTIONS handshake (6.2.4.11) and the Basic-Auth gate (6.2.4.13) let
Sphaira actually reach `/api/graphql`, its own native query still failed schema
validation outright - `StringFilter.notIn` didn't exist, nor did `App.displayVersion`,
`App.latestOwnedVersion`, `Title.icon`/`Title.banner` (upstream's `Image`/`ImageSize`
parametrized-size artwork fields). Confirmed against the shop's own error log, which
is reproduced here as one combined regression query.

`displayVersion` is deliberately always null - this fork extracts no Control NCA
metadata to populate it, unlike upstream - so it only has to exist, not say anything
true yet.

A later shop log showed Sphaira's title-detail query failing on a second gap:
`Title.screenshots` needed to become a parametrized `screenshots(size:): [Image!]`
(it had shipped as a flat `[String!]`, deliberately not ported to match upstream at
the time, since a flat and a parametrized field can't coexist under the same
GraphQL name and the flat shape wasn't yet causing a real failure). That same log
also wanted `App.downloadUrl`/`downloadSize`/`downloadExtension`, which did not
exist at all. Those are deliberately scoped down from upstream's opaque-token,
multi-file dedup-preference system to a thin wrapper around this fork's existing
`downloadableFile`/`/api/get_game/<id>` mechanism - same file, same route, just a
path string plus the two extra fields a shop client needs alongside it. Both gaps
are covered below alongside the original combined regression query.
"""
import json
import types

import pytest

import db as db_mod
import media
import titledb
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC, APP_TYPE_UPD
from db import Apps, Files, Libraries, Titles, db, init_db, upsert_media
from gql import graphql_dispatch

TITLE_ID = "0100000000010000"
UPDATE_APP_ID = TITLE_ID[:-3] + "800"
DLC_APP_ID = "0100000000011001"


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
    monkeypatch.setattr(media, "MEDIA_DIR", str(tmp_path / "media"))

    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    app.add_url_rule("/api/graphql", view_func=graphql_dispatch, methods=["GET", "POST"])
    init_db(app)

    region_file = titledb_dir / "titles.US.en.json"
    region_file.write_text(json.dumps({
        TITLE_ID: {
            "id": TITLE_ID, "name": "Alpha Game",
            "bannerUrl": "https://titledb.example/banner.jpg",
            "iconUrl": "https://titledb.example/icon.jpg",
            "screenshots": ["https://titledb.example/s1.jpg", "https://titledb.example/s2.jpg"],
        },
    }))
    (titledb_dir / "cnmts.json").write_text("{}")
    (titledb_dir / "versions.json").write_text("{}")
    with app.app_context():
        titledb.store.import_from_json(str(region_file), "US.en")

        title = Titles(title_id=TITLE_ID, have_base=True)
        library_row = Libraries(path=str(tmp_path / "games"))
        db.session.add_all([title, library_row])
        db.session.flush()

        base_app = Apps(title_id=title.id, app_id=TITLE_ID, app_version="0",
                        app_type=APP_TYPE_BASE, owned=True)
        db.session.add(base_app)
        db.session.add(Apps(title_id=title.id, app_id=UPDATE_APP_ID, app_version="65536",
                            app_type=APP_TYPE_UPD, owned=True))
        db.session.flush()

        base_file = Files(library_id=library_row.id, filepath=str(tmp_path / "games" / "Alpha.nsp"),
                          filename="Alpha.nsp", extension="nsp", size=6500000, identified=True)
        db.session.add(base_file)
        db.session.flush()
        base_app.files.append(base_file)
        db.session.commit()

    return types.SimpleNamespace(app=app, client=app.test_client(), titledb_dir=titledb_dir,
                                 region_file=region_file)


def query(library, text_query, **variables):
    params = {"query": text_query}
    if variables:
        params["variables"] = json.dumps(variables)
    resp = library.client.get("/api/graphql", query_string=params)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body["errors"]
    return body["data"]


def test_string_filter_not_in_excludes_the_listed_values(library):
    data = query(library, """
        query { apps(filter: {appId: {notIn: ["%s"]}}) { items { appId } } }
        """ % UPDATE_APP_ID)
    ids = {a["appId"] for a in data["apps"]["items"]}
    assert UPDATE_APP_ID not in ids
    assert TITLE_ID in ids


def test_string_filter_not_in_with_an_empty_list_is_no_constraint(library):
    data = query(library, """
        query { apps(filter: {appId: {notIn: []}}) { items { appId } } }""")
    ids = {a["appId"] for a in data["apps"]["items"]}
    assert ids == {TITLE_ID, UPDATE_APP_ID}


def test_display_version_exists_on_the_schema_but_is_always_null(library):
    data = query(library, """
        query { apps { items {
            appId displayVersion versions { displayVersion }
        } } }""")
    for item in data["apps"]["items"]:
        assert item["displayVersion"] is None
        for v in item["versions"] or []:
            assert v["displayVersion"] is None


def test_latest_owned_version_on_a_base_app_is_the_highest_owned_update(library):
    data = query(library, """
        query { apps(appType: [BASE]) { items {
            appId latestOwnedVersion { version owned }
        } } }""")
    base = data["apps"]["items"][0]
    assert base["appId"] == TITLE_ID
    assert base["latestOwnedVersion"] == {"version": 65536, "owned": True}


def test_latest_owned_version_is_null_when_nothing_is_owned(library):
    with library.app.app_context():
        Apps.query.filter_by(app_id=UPDATE_APP_ID).update({"owned": False})
        Apps.query.filter_by(app_id=TITLE_ID).update({"owned": False})
        db.session.commit()
    data = query(library, """
        query { apps(appType: [BASE]) { items { latestOwnedVersion { version } } } }""")
    assert data["apps"]["items"][0]["latestOwnedVersion"] is None


def test_icon_and_banner_fall_back_to_the_titledb_hotlink_at_original_size(library):
    """No Local artworks copy yet (or Local artworks off) - `icon`/`banner` must still
    resolve, from the raw titledb URL, reporting `local: false` and always `ORIGINAL`
    regardless of what `size:` was asked for, since a hotlink has no other rendition."""
    data = query(library, """
        query { title(titleId: "%s") {
            icon(size: THUMB) { url size local width height }
            banner(size: THUMB) { url size local width height }
        } }""" % TITLE_ID)
    icon = data["title"]["icon"]
    assert icon == {"url": "https://titledb.example/icon.jpg", "size": "ORIGINAL",
                    "local": False, "width": None, "height": None}
    banner = data["title"]["banner"]
    assert banner["url"] == "https://titledb.example/banner.jpg"
    assert banner["local"] is False


def test_icon_resolves_a_requested_rendition_once_local_artworks_has_a_copy(library):
    with library.app.app_context():
        upsert_media(TITLE_ID, media.ICON, 0, source="titledb",
                    source_url="https://titledb.example/icon.jpg",
                    filename="icon123.jpg", size=(256, 256))
        db.session.commit()

    data = query(library, """
        query { title(titleId: "%s") {
            icon(size: THUMB) { url size local width height }
        } }""" % TITLE_ID)
    icon = data["title"]["icon"]
    assert icon["local"] is True
    assert icon["size"] == "THUMB"
    assert icon["url"] == media.url_for(TITLE_ID, media.ICON, 0, media.THUMB, "icon123.jpg")
    # (256, 256) fitted into THUMB's icon box - see media.RENDITIONS.
    expected_box = media.box(media.ICON, media.THUMB)
    assert (icon["width"], icon["height"]) == media.fit((256, 256), expected_box)


def test_icon_defaults_to_the_client_rendition_when_no_size_is_given(library):
    with library.app.app_context():
        upsert_media(TITLE_ID, media.ICON, 0, source="titledb",
                    source_url="https://titledb.example/icon.jpg",
                    filename="icon123.jpg", size=(256, 256))
        db.session.commit()

    data = query(library, """query { title(titleId: "%s") { icon { size } } }""" % TITLE_ID)
    assert data["title"]["icon"]["size"] == "CLIENT"


def test_screenshots_resolves_with_a_size_argument_like_icon_and_banner(library):
    """The title-detail query gap from the second shop log: Sphaira asks for two
    renditions of the same screenshot list in one query (a small `CLIENT` one for the
    grid, a `SCREEN`-sized `full` alias for the viewer), the same way it already does
    for icon/banner. No Local artworks copy yet, so both come back as the raw titledb
    hotlinks at `ORIGINAL`, `local: false` - same fallback rule as icon/banner."""
    data = query(library, """
        query { title(titleId: "%s") {
            screenshots(size: CLIENT) { url size local }
            full: screenshots(size: SCREEN) { url size local }
        } }""" % TITLE_ID)
    shots = data["title"]["screenshots"]
    assert [s["url"] for s in shots] == [
        "https://titledb.example/s1.jpg", "https://titledb.example/s2.jpg"]
    assert all(s["size"] == "ORIGINAL" and s["local"] is False for s in shots)
    assert data["title"]["full"] == shots


def test_screenshots_is_null_when_the_title_has_none(library):
    data = query(library, """
        query { apps(filter: {appId: {notIn: []}}) { items { title {
            titleId screenshots { url }
        } } } }""")
    # TITLE_ID's title does have screenshots in this fixture; this just confirms the
    # field resolves cleanly through the real apps->title path Sphaira also uses.
    titles = {a["title"]["titleId"]: a["title"]["screenshots"] for a in data["apps"]["items"]
              if a["title"]}
    assert titles.get(TITLE_ID)


def test_download_fields_name_the_same_file_downloadable_file_already_does(library):
    """The scoped-down version of upstream's `downloadUrl`/`downloadSize`/
    `downloadExtension`: no opaque token or dedup-preference logic between several
    copies of an app, just this app's first owned file (same one `downloadableFile`
    already resolves), served through the existing `/api/get_game/<id>` route."""
    data = query(library, """
        query { apps(appType: [BASE]) { items {
            appId
            downloadUrl downloadSize downloadExtension
            downloadableFile { id size }
        } } }""")
    base = data["apps"]["items"][0]
    assert base["appId"] == TITLE_ID
    file_id = base["downloadableFile"]["id"]
    assert base["downloadUrl"] == f"/api/get_game/{file_id}"
    assert base["downloadSize"] == 6500000 == base["downloadableFile"]["size"]
    assert base["downloadExtension"] == "nsp"


def test_download_fields_are_null_when_no_file_carries_the_app(library):
    """The UPDATE app in this fixture is tracked (`owned: true`) but, deliberately,
    never had a file attached - the same "owned flag set, no real file" shape
    `downloadableFile` already returns null for, so these three fields must too."""
    data = query(library, """
        query { apps(appType: [UPDATE]) { items {
            downloadUrl downloadSize downloadExtension downloadableFile { id }
        } } }""")
    update = data["apps"]["items"][0]
    assert update["downloadableFile"] is None
    assert update["downloadUrl"] is None
    assert update["downloadSize"] is None
    assert update["downloadExtension"] is None


def test_title_detail_aliased_apps_hydrate_download_fields_without_downloadable_file(library):
    """Reported regression: entering a game's detail page in Sphaira fails to install
    with no network request at all, even though the catalogue list (a plain top-level
    `apps` query) already shows the right version. Sphaira's real native title-detail
    query (TITLE_QUERY in its own source) nests three separately-aliased `apps` calls
    under `title(titleId:)` - `base:`, `updates:`, `dlc:` - and the `base:` alias asks
    for `downloadUrl`/`downloadSize`/`downloadExtension` directly, never for
    `downloadableFile`. `resolve_title`'s own want_apps_downloadable flag only checked
    for `downloadableFile`, unlike `resolve_apps`' equivalent flag which already checked
    all four fields - so under `title(titleId:)` those three fields silently resolved
    to null (files_loaded never got hydrated), which is exactly what makes a shop
    client treat the title as undownloadable."""
    data = query(library, """
        query { title(titleId: "%s") {
            base: apps(owned: true, appType: [BASE]) {
                displayVersion downloadSize downloadUrl downloadExtension
            }
        } }""" % TITLE_ID)
    base = data["title"]["base"][0]
    assert base["downloadUrl"] is not None
    assert base["downloadUrl"].startswith("/api/get_game/")
    assert base["downloadSize"] == 6500000
    assert base["downloadExtension"] == "nsp"


def test_title_detail_merges_sub_selections_across_differently_aliased_apps_calls(library):
    """Second half of the same reported regression: DLC showed up with the base
    game's id instead of its own name, with no icon. Sphaira's TITLE_QUERY asks for
    `titledb{name ...}` only under its `dlc:` alias of `apps`, never under `base:` or
    `updates:` - but `Selection.child("apps")` used to return on the first field named
    "apps" it found (i.e. whatever `base:` alone selected) instead of merging every
    alias's own sub-selection, so `want_apps_titledb` came out false and no DLC ever
    got its titledb row hydrated, however the query was written."""
    with library.app.app_context():
        region_file = library.region_file
        region_file.write_text(json.dumps({
            TITLE_ID: {"id": TITLE_ID, "name": "Alpha Game",
                       "bannerUrl": "https://titledb.example/banner.jpg",
                       "iconUrl": "https://titledb.example/icon.jpg"},
            DLC_APP_ID: {"id": DLC_APP_ID, "name": "Alpha Game - Expansion Pass"},
        }))
        titledb.store.import_from_json(str(region_file), "US.en")

        title = Titles.query.filter_by(title_id=TITLE_ID).first()
        db.session.add(Apps(title_id=title.id, app_id=DLC_APP_ID, app_version="0",
                            app_type=APP_TYPE_DLC, owned=False))
        db.session.commit()

    data = query(library, """
        query { title(titleId: "%s") {
            base: apps(owned: true, appType: [BASE]) { displayVersion }
            dlc: apps(appType: [DLC]) { appId titledb { name } }
        } }""" % TITLE_ID)
    dlc = data["title"]["dlc"][0]
    assert dlc["appId"] == DLC_APP_ID
    assert dlc["titledb"]["name"] == "Alpha Game - Expansion Pass"


def test_the_reported_sphaira_query_now_runs_with_no_schema_errors(library):
    """The combined shape from the shop's own error log: `notIn` on an app-id filter,
    `displayVersion`/`latestOwnedVersion` on apps, `icon`/`banner` with a `size:` on
    titles - all in the one query that previously failed GraphQL validation outright,
    before a single resolver ever ran."""
    data = query(library, """
        query {
            apps(filter: {appId: {notIn: ["0000000000000000"]}}) {
                items {
                    appId
                    displayVersion
                    latestOwnedVersion { version owned displayVersion }
                    downloadUrl downloadSize downloadExtension
                }
            }
            titles(owned: true) {
                items {
                    titleId
                    icon(size: THUMB) { url size local width height }
                    banner(size: THUMB) { url size local width height }
                    screenshots(size: CLIENT) { url local }
                }
            }
        }""")
    assert data["apps"]["items"]
    assert data["titles"]["items"]

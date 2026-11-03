"""Stage 3 design: a page per game at /game/<titleId> (templates/game.html +
static/js/game.js), sharing helpers with the Library through static/js/library-common.js."""
import json
import os
import re

import fixture
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OWNED = "0100000000010000"   # a game the shop fixture library holds


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _js(name):
    return _read("app", "static", "js", name)


def _function_body(js, name):
    start = re.search(rf"(async )?function {name}\(", js).start()
    depth, i = 0, js.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        i += 1
        if depth == 0:
            return js[start:i]


def _login(client, user):
    resp = client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    assert resp.status_code in (302, 303)
    return client


# --- shared helpers -------------------------------------------------------------------

SHARED = ("gqlFetch", "gqlMutate", "formatTitledbDate", "formatTitledbSize", "statusBadge",
          "verificationBadge")


def test_shared_helpers_live_in_library_common(shop_app):
    common, library = _js("library-common.js"), _js("library.js")
    for name in SHARED:
        assert re.search(rf"(async )?function {name}\(", common), name
        assert not re.search(rf"(async )?function {name}\(", library), name
    assert "const VERIFICATION_BADGES" in common and "const VERIFICATION_BADGES" not in library
    html = _login(shop_app.client, "shopper").get("/").get_data(as_text=True)
    assert html.index("js/library-common.js") < html.index("js/library.js")


# --- route, access and skeleton ------------------------------------------------------

def _page(client, title_id=OWNED):
    return client.get(f"/game/{title_id}")


def test_a_shopper_gets_the_page_for_a_game(shop_app):
    client = _login(shop_app.client, "shopper")
    for tid in (OWNED, OWNED.lower()):
        resp = _page(client, tid)
        assert resp.status_code == 200, tid
        html = resp.get_data(as_text=True)
        assert f'const TITLE_ID = "{OWNED}";' in html
        assert "const IS_ADMIN = false;" in html
        assert html.index("js/library-common.js") < html.index("js/game.js")
        assert len(re.findall(r"<script>", html)) == 1


def test_an_admin_gets_admin_values(shop_app):
    html = _page(_login(shop_app.client, "admin")).get_data(as_text=True)
    assert "const IS_ADMIN = true;" in html


@pytest.mark.parametrize("bad", ["xyz", "0100000000010", "010000000001000G", "0100000000010000a"])
def test_a_malformed_id_is_a_404_not_found_state(shop_app, bad):
    resp = _page(_login(shop_app.client, "shopper"), bad)
    assert resp.status_code == 404
    html = resp.get_data(as_text=True)
    assert "const TITLE_ID = null;" in html
    assert re.search(r'id="gameNotFound"(?![^>]*hidden)', html)


def test_a_private_shop_sends_anonymous_visitors_to_login(shop_app):
    admin = _login(shop_app.client, "admin")
    admin.post("/api/settings/shop", json={"public": False})
    anonymous = shop_app.app.test_client()
    resp = _page(anonymous)
    assert resp.status_code in (302, 401)
    if resp.status_code == 302:
        assert "/login" in resp.headers["Location"]


def test_a_public_shop_shows_the_page_to_anyone(shop_app):
    admin = _login(shop_app.client, "admin")
    admin.post("/api/settings/shop", json={"public": True})
    assert _page(shop_app.app.test_client()).status_code == 200


def test_skeleton_has_every_region(shop_app):
    html = _page(_login(shop_app.client, "shopper")).get_data(as_text=True)
    for region in ("gameBreadcrumb", "gameHero", "gameFacts", "gameSections", "gameLoading",
                   "gameNotFound", "gameError", "gameRetryBtn"):
        assert f'id="{region}"' in html, region


# --- the game query, hero, facts and states ---------------------------------------------

from test_card_icon_metadata_query import ALPHA, library  # noqa: E402,F401  (pytest fixture)


def _extract_query(js_source, const_name):
    m = re.search(rf"const {const_name} = `(.*?)`;", js_source, re.DOTALL)
    assert m, f"{const_name} not found"
    return m.group(1)


def _gql(client, query, **variables):
    resp = client.get("/api/graphql", query_string={"query": query, "variables": json.dumps(variables)})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    return body["data"]


def test_the_shipped_game_query_runs_for_an_owned_game(library):
    data = _gql(library.client, _extract_query(_js("game.js"), "GAME_QUERY"), titleId=ALPHA)
    t = data["title"]
    assert t["titleId"] == ALPHA and t["name"] == "Alpha Game"
    assert t["ownership"]["haveBase"] is True
    assert {a["appType"] for a in t["apps"]} == {"BASE", "DLC"}
    assert [d["appId"] for d in t["availableDlc"]]


def test_an_unknown_id_reads_null(library):
    data = _gql(library.client, _extract_query(_js("game.js"), "GAME_QUERY"), titleId="0100000000FFF000")
    assert data["title"] is None


def test_a_shopper_never_gets_files(shop_app):
    client = _login(shop_app.client, "shopper")
    t = _gql(client, _extract_query(_js("game.js"), "GAME_QUERY"), titleId=OWNED)["title"]
    assert t is not None
    assert all(a.get("files") is None for a in t["apps"])


def test_hero_and_facts_are_built_from_text():
    js = _js("game.js")
    hero, facts = _function_body(js, "renderHero"), _function_body(js, "renderFacts")
    assert "game-hero" in hero or "gameHero" in hero
    assert "statusBadge(" in hero and ".text(" in hero
    assert "game-fact" in facts and ".text(" in facts
    # A fact without a value is not drawn.
    assert "filter(" in facts


def test_load_handles_not_found_and_failure():
    body = _function_body(_js("game.js"), "loadGame")
    assert "gameNotFound" in body
    assert "gameError" in body.split("catch", 1)[1]


# --- sections ----------------------------------------------------------------------------

def test_sections_render_from_the_query():
    js = _js("game.js")
    body = _function_body(js, "renderSections")
    for fn in ("renderDescription", "renderScreenshots", "renderUpdates", "renderDlc", "renderFiles"):
        assert f"{fn}(" in body, fn
        _function_body(js, fn)  # defined


def test_downloads_follow_the_existing_gate():
    js = _js("game.js")
    assert "function canDownload" in js
    gate = _function_body(js, "canDownload")
    assert "IS_SHOP" in gate and "WEB_DOWNLOADS_ENABLED" in gate
    assert "function downloadButton" in _js("library-common.js")
    assert "function downloadButton" not in _js("library.js")


def test_files_are_for_admins_only():
    assert "IS_ADMIN" in _function_body(_js("game.js"), "renderFiles")


def test_dlc_link_is_validated_scrolled_and_highlighted():
    body = _function_body(_js("game.js"), "highlightDlcFromUrl")
    assert "[0-9A-F]{16}" in body
    assert "is-highlighted" in body and "scrollIntoView" in body


def test_screenshots_open_full_size(shop_app):
    html = _page(_login(shop_app.client, "shopper")).get_data(as_text=True)
    assert 'id="shotModal"' in html
    body = _function_body(_js("game.js"), "renderScreenshots")
    assert ".attr('src'" in body and "game-shots" in body


def test_section_strings_are_translated():
    import i18n
    for key in ("game.description", "game.screenshots", "game.updates", "game.update_missing",
                "game.dlc", "game.files", "game.owned", "game.missing", "game.no_updates",
                "game.file_format"):
        assert {"en", "es"} <= set(i18n.TRANSLATIONS[key]), key


# --- actions: download all, copy title ID, edit metadata --------------------------------

def test_edit_metadata_is_for_admins_only(shop_app):
    shopper = _page(_login(shop_app.client, "shopper")).get_data(as_text=True)
    assert 'id="gameEditModal"' not in shopper
    admin = _page(_login(shop_app.app.test_client(), "admin")).get_data(as_text=True)
    for needle in ('id="gameEditModal"', 'id="gameEditName"', 'id="gameEditDeveloper"',
                   'id="gameEditPublisher"', 'id="gameEditReleaseDate"', 'id="gameEditDescription"',
                   'id="gameEditSaveBtn"', 'id="gameEditResetBtn"'):
        assert needle in admin, needle


def test_actions_use_the_existing_mutations_and_gates():
    js = _js("game.js")
    assert "setTitleOverride(titleId: $id, record: $record)" in js
    assert "deleteTitleOverride(titleId: $id)" in js
    actions = _function_body(js, "renderActions")
    assert "canDownload()" in actions and "IS_ADMIN" in actions
    assert "navigator.clipboard" in _function_body(js, "copyTitleId")
    body = _function_body(js, "downloadAll")
    assert "/api/library/download/" in body


def test_action_strings_are_translated():
    import i18n
    for key in ("game.download_all", "game.edit_metadata", "game.copy_title_id", "game.copied",
                "game.save", "game.reset", "game.edit_hint", "game.save_failed"):
        assert {"en", "es"} <= set(i18n.TRANSLATIONS[key]), key


# --- the Library and Ctrl+K open the game page --------------------------------------------

def test_game_url_covers_games_dlc_and_orphan_dlc():
    body = _function_body(_js("library.js"), "gameUrl")
    assert "`/game/${" in body and "?dlc=" in body
    # A DLC whose game the library doesn't know links to its own id, never "undefined".
    assert "titleId ?" in body or "title.titleId ?" in body or "parentId ?" in body


def test_cards_icons_and_list_rows_are_links():
    js = _js("library.js")
    card = _function_body(js, "renderCardView")
    assert "<a" in card and "attr('href', game.url)" in card
    icons = _function_body(js, "renderIconView")
    assert "<a" in icons and "href" in icons
    details = _function_body(js, "metadataButton")
    assert "<a" in details and "href" in details
    assert "?dlc=" in _function_body(js, "renderListView")


def test_the_metadata_modal_is_gone_from_the_library(shop_app):
    html = _login(shop_app.client, "shopper").get("/").get_data(as_text=True)
    assert "metadataModal" not in html
    js = _js("library.js")
    for gone in ("function openMetadata", "function renderMetadataView", "function renderMetadataEditForm",
                 "SET_TITLE_OVERRIDE_MUTATION"):
        assert gone not in js, gone


def test_ctrl_k_opens_the_game_page():
    js = _js("search.js")
    assert "'/game/' + encodeURIComponent(g.title_id)" in js


# --- found in the browser check -----------------------------------------------------------

def test_hero_dlc_state_agrees_with_the_dlc_section():
    """The hero said "Complete" over a DLC section listing 3 missing DLC: it trusted the
    stored ownership.complete flag (stale until titles are re-checked) instead of the
    DLC list the page itself shows."""
    hero = _function_body(_js("game.js"), "renderHero")
    assert "own.complete" not in hero
    assert "missingDlcCount(t)" in hero
    body = _function_body(_js("game.js"), "missingDlcCount")
    assert "availableDlc" in body and "ownedDlcIds(t)" in body


def test_the_dlc_highlight_runs_once_the_sections_are_visible():
    """Found in the browser: the row was marked but never scrolled to - scrollIntoView ran
    while the sections were still hidden."""
    js = _js("game.js")
    load = _function_body(js, "loadGame")
    assert load.index("gameState('game')") < load.index("highlightDlcFromUrl()")
    assert "highlightDlcFromUrl()" not in _function_body(js, "renderSections")


def test_the_library_restores_its_scroll_when_coming_back():
    """Found in the browser: back from a game page kept filters and sort but landed at
    the top - the grid is drawn after its data arrives, too late for the browser's own
    scroll restoration."""
    js = _js("library.js")
    assert "pagehide" in js and "libraryScroll" in js
    assert "restoreLibraryScroll()" in _function_body(js, "loadPage")
    body = _function_body(js, "restoreLibraryScroll")
    assert "scrollTo" in body
    assert "sessionStorage.getItem('libraryScroll')" in js and "sessionStorage.setItem('libraryScroll'" in js

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
    for fn in ("renderDescription", "renderScreenshots", "renderUpdates", "renderDlc"):
        assert f"{fn}(" in body, fn
        _function_body(js, fn)  # defined
    # The files moved out of the page into the Files dialog.
    assert "renderFiles" not in js


def test_downloads_follow_the_existing_gate():
    js = _js("game.js")
    assert "function canDownload" in js
    gate = _function_body(js, "canDownload")
    assert "IS_SHOP" in gate and "WEB_DOWNLOADS_ENABLED" in gate
    assert "function downloadButton" in _js("library-common.js")
    assert "function downloadButton" not in _js("library.js")


def test_file_names_are_for_admins_only():
    body = _function_body(_js("game.js"), "gameFiles")
    # Admins and collaborators (who only look) see the files behind a game.
    assert "CAN_VIEW_ADMIN && a.files" in body and "downloadableFile" in body


def test_the_files_button_opens_a_dialog_with_native_downloads(shop_app):
    html = _page(_login(shop_app.client, "shopper")).get_data(as_text=True)
    for needle in ('id="gameFilesModal"', 'id="gameFilesList"', 'id="gameFilesDownloadAll"'):
        assert needle in html, needle
    js = _js("game.js")
    actions = _function_body(js, "renderActions")
    assert "I18N.files" in actions and "openFiles(" in actions
    assert "downloadAll(" not in actions
    dialog = _function_body(js, "openFiles")
    assert "download>" in dialog and "/api/library/download/" in dialog
    assert "downloadAll(" in dialog and "gameFilesModal" in dialog


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
    compact = _function_body(js, "renderCompactView")
    assert "<a" in compact and "attr('href', game.url)" in compact
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
    # A timer: requestAnimationFrame never runs in a background tab, so the restore
    # silently did nothing there.
    assert "requestAnimationFrame" not in body and "setTimeout(attempt" in body
    assert "sessionStorage.getItem('libraryScroll')" in js and "sessionStorage.setItem('libraryScroll'" in js


def test_scroll_is_only_restored_when_going_back():
    """Final review: the saved position was applied to any later fresh visit (nav link to
    the Library after a bfcache Back), jumping to the middle of the page."""
    js = _js("library.js")
    i = js.index("sessionStorage.getItem('libraryScroll')")
    setup = js[js.rindex("let scrollToRestore", 0, i):i + 600]
    assert "back_forward" in setup
    assert "sessionStorage.removeItem('libraryScroll')" in setup


def test_updates_read_both_versions_and_link_their_notes():
    """Switch Library Manager touches, on our shape: "3.0.0 · v1048576" for a version
    (the human name when the CNMT gave one), and a release-notes icon - only the icon,
    opening a web search in its own tab - right before the download arrow."""
    js = _js("game.js")
    updates = _function_body(js, "renderUpdates")
    assert "u.displayVersion ? `${u.displayVersion} · v${u.appVersion}`" in updates
    assert "newsUrl: updateNotesUrl(t, u)" in updates
    # contentRow destructures its params (the shared body extractor stops at the
    # destructuring brace), so these read against the file: the icon opens a new tab,
    # carries only its tooltip (never a label) and sits AFTER the download button
    # (asked for - it used to go before).
    assert 'target="_blank" rel="noopener"' in js and "bi-box-arrow-up-right" in js
    assert "I18N.updateNotes" in js
    assert js.index("tail.append(downloadButton(file.id, name))") < js.index("if (newsUrl) {")
    # Icon only: no text rides along.
    notes = _function_body(js, "updateNotesUrl")
    assert "google.com/search" in notes


def test_a_dlc_name_opens_its_own_card():
    """The DLC's name opens a window with the game's art and the DLC's facts; its id
    gets a copy button beside it, and the size rides in the row's pill once (not again
    under the name)."""
    js = _js("game.js")
    dlc = _function_body(js, "renderDlc")
    assert "onName: () => openDlcModal(" in dlc and "copyId: d.appId" in dlc
    assert "formatTitledbSize(meta.size)" not in dlc.split("const sub =")[1].split("join")[0]
    modal = _function_body(js, "openDlcModal")
    assert "dlcModalImg" in modal and "ownedBadge(owned)" in modal
    assert "copyIdButton(d.appId)" in modal
    html = _read("app", "templates", "game.html")
    assert 'id="dlcModal"' in html and 'id="dlcModalName"' in html
    # The row's size is a pill now, like the List view's.
    css = _read("app", "static", "style.css")
    assert "border-radius: 1rem" in re.search(r"\.game-row__size \{([^}]*)\}", css).group(1)


def test_the_dlc_card_puts_its_art_on_top():
    """Asked for: the art was a small thumbnail beside the text. It spans the window's
    width on top now, the name, facts and description underneath - both get room."""
    html = _read("app", "templates", "game.html")
    start = html.index('id="dlcModal"')
    modal = html[start:html.index("<script", start)]
    assert "modal-body d-flex" not in modal
    assert modal.index('id="dlcModalImg"') < modal.index('id="dlcModalName"')
    assert "dlc-modal__dialog" in modal
    css = _read("app", "static", "style.css")
    img = _rule(css, ".dlc-modal__img")
    assert "width: 100%" in img and "aspect-ratio" in img
    assert "grid-template-columns" in _rule(css, ".dlc-modal__facts")


def test_dates_read_the_same_way_whatever_shaped_they_come():
    """titledb ships YYYYMMDD, the apps table dashed ISO dates; both are the one
    DD/MM/YYYY every update and DLC row shows."""
    body = _function_body(_js("library-common.js"), "formatTitledbDate")
    assert r"/^(\d{4})-?(\d{2})-?(\d{2})$/" in body


def test_sections_and_rows_wear_the_type_colors():
    """The rows' glyphs inside the Updates and DLC sections carry their content type's
    fixed color; the sections' TITLE icons keep the web's own accent (asked for:
    that is design, the rows are the content)."""
    js = _js("game.js")
    assert "iconTone: 'update'" in js and "iconTone: 'dlc'" in js
    css = _read("app", "static", "style.css")
    for cls, token in ((".game-row__icon--update", "--op-wait"), (".game-row__icon--dlc", "--op-dlc")):
        assert token in re.search(rf"{re.escape(cls)} \{{([^}}]*)\}}", css).group(1), cls
    assert ".game-section__icon--" not in css


def _rule(css, selector):
    return re.search(rf"(?:^|\n){re.escape(selector)} \{{([^}}]*)\}}", css).group(1)


def test_a_marked_fact_keeps_its_title_plain():
    """The firmware fact turns violet when the console is too old, and "Latest version"
    turns the update's amber when the owned one is behind it - each with the color of
    what it tells (asked for: the two used to share the violet). Only the frame and
    the value take it: the title stays as plain as "Your version" or "Size"."""
    body = _function_body(_js("game.js"), "renderFacts")
    assert "latest > installed ? 'game-fact--update'" in body
    css = _read("app", "static", "style.css")
    assert "--op-firmware-rgb" in _rule(css, ".game-fact--firmware")
    assert "--op-wait-rgb" in _rule(css, ".game-fact--update")
    assert "--op-firmware" in _rule(css, ".game-fact--firmware .game-fact__value")
    assert "--op-wait" in _rule(css, ".game-fact--update .game-fact__value")
    assert ".game-fact--firmware .game-fact__label" not in css
    assert ".game-fact--update .game-fact__label" not in css

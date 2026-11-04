"""Stage 2 design: the Library page (templates/index.html + static/js/library.js) -
header and tiles, toolbar with sorting, filter pills with exact counts, cards, empty and
error states. Markup and JS are checked as source; the shipped GraphQL queries run
against the real schema on a seeded library."""
import json
import os
import re

import fixture
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _library_js():
    return _read("app", "static", "js", "library.js")


def _extract_query(js_source, const_name):
    m = re.search(rf"const {const_name} = `(.*?)`;", js_source, re.DOTALL)
    assert m, f"{const_name} not found in library.js"
    return m.group(1)


@pytest.fixture
def client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    assert resp.status_code in (302, 303)
    return shop_app.client


# --- code structure ------------------------------------------------------------------

def test_library_logic_lives_in_its_own_script(client):
    html = client.get("/").get_data(as_text=True)
    assert "/static/js/library.js" in html
    assert "function loadPage" not in html
    assert "const I18N = {" in html
    js = client.get("/static/js/library.js").get_data(as_text=True)
    assert "function loadPage" in js and "const CARDS_QUERY" in js


def test_library_page_has_one_bare_inline_script(client):
    html = client.get("/").get_data(as_text=True)
    assert len(re.findall(r"<script>", html)) == 1


# --- a real GraphQL run on a seeded library (fixture shared with the query tests) ----

from test_card_icon_metadata_query import library  # noqa: E402,F401  (pytest fixture)


def _gql(library, query, **variables):
    resp = library.client.get("/api/graphql", query_string={
        "query": query, "variables": json.dumps(variables)})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    return body["data"]


# --- sorting ---------------------------------------------------------------------------

def test_sort_controls_offer_name_and_release_date(client):
    html = client.get("/").get_data(as_text=True)
    sel = html.split('id="sortField"', 1)[1].split("</select>", 1)[0]
    assert re.findall(r'value="(\w+)"', sel) == ["NAME", "RELEASE_DATE"]
    assert 'id="sortDirection"' in html


def test_queries_take_order_by_and_stored_sort_is_validated():
    js = _library_js()
    for name in ("CARDS_QUERY", "ICONS_QUERY", "LIST_QUERY"):
        q = _extract_query(js, name)
        assert "$orderBy: OrderBy" in q and "orderBy: $orderBy" in q, name
    assert "SORT_FIELDS.includes(" in js and "SORT_DIRECTIONS.includes(" in js
    assert "orderBy: librarySort" in js


@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_shipped_queries_sort_by_release_date(library, direction):
    js = _library_js()
    order = {"field": "RELEASE_DATE", "direction": direction}
    cards = _gql(library, _extract_query(js, "CARDS_QUERY"), page=1, pageSize=20,
                 appType=["BASE", "DLC"], orderBy=order)
    assert cards["apps"]["total"] == 2
    listed = _gql(library, _extract_query(js, "LIST_QUERY"), page=1, pageSize=20, orderBy=order)
    assert listed["titles"]["total"] == 1


# --- header, stat tiles and progress ---------------------------------------------------

def _function_body(js, name):
    start = js.index(f"function {name}(")
    depth, i = 0, js.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        i += 1
        if depth == 0:
            return js[start:i]


def test_header_tiles_and_progress_replace_the_stats_line(client):
    html = client.get("/").get_data(as_text=True)
    assert 'class="page-head' in html and 'id="libraryCount"' in html
    assert re.search(r'id="libraryTiles"[^>]*hidden', html)
    assert re.search(r'id="libraryProgress"[^>]*hidden', html)
    assert 'id="libraryStats"' not in html


def test_tiles_are_computed_from_the_stats_query():
    body = _function_body(_library_js(), "renderLibraryStats")
    assert "ownedTitles - stats.upToDateTitles" in body
    assert "ownedTitles - stats.completeTitles" in body
    # The size tile is admin-only: totalFiles reads 0 for anyone else.
    assert "if (stats.totalFiles)" in body
    # Pending updates and missing DLC tiles apply their filter.
    assert 'data-pill' in body or "dataset.pill" in body


def test_library_header_strings_are_translated(client):
    import i18n
    for key in ("library.title", "library.subtitle", "library.tile_games", "library.tile_updates",
                "library.tile_missing_dlc", "library.tile_size", "library.progress"):
        assert {"en", "es"} <= set(i18n.TRANSLATIONS[key]), key


# --- toolbar, View and Filters menus ---------------------------------------------------

def test_toolbar_holds_search_sort_views_and_both_menus(client):
    html = client.get("/").get_data(as_text=True)
    bar = html.split('class="toolbar library-toolbar', 1)[1].split('<!-- Pagination controls (top)', 1)[0]
    for needle in ('id="textFilter"', 'id="sortField"', 'id="sortDirection"', 'data-view="card"',
                   'data-view="icon"', 'data-view="list"', 'id="viewMenuBtn"', 'id="filtersMenuBtn"',
                   'id="customItemsPerPage"', 'id="cardSizeRange"', 'id="filtersActiveDot"'):
        assert needle in bar, needle
    # Every filter group lives in the one Filters menu now; the list view's own group
    # is marked so the JS shows it only there.
    menu = bar.split('id="filtersMenuBtn"', 1)[1]
    for group in ("Ownership filter", "Update filter", "Completion filter",
                  "Library health filter"):
        assert f'aria-label="{group}"' in menu, group
    assert re.search(r'id="listHealthFilterCol" data-view-only="list"', menu)
    assert "filterDropdownBtn" not in html and "listHealthDropdownBtn" not in html


def test_filters_dot_follows_the_view():
    body = _function_body(_library_js(), "updateFiltersDot")
    assert "activeHealthFilter" in body and "activeCompletionFilter" in body
    assert "currentView === 'list'" in body


# --- filter pills with exact counts ---------------------------------------------------

CARD_PILL_FILTERS = (("all", {}), ("outdated", {"upToDate": False}),
                     ("missingDlc", {"complete": False}), ("upToDate", {"upToDate": True}))
HEALTH = (("all", None), ("complete", "COMPLETE"), ("incomplete", "INCOMPLETE"),
          ("corrupt", "CORRUPT"), ("repack", "REPACK"))


@pytest.mark.parametrize("app_type,search", [(["BASE", "DLC"], None), (["BASE"], None),
                                             (["BASE", "DLC"], "alpha"), (["DLC"], "nothing-matches")])
def test_card_pill_counts_equal_the_grid_totals(library, app_type, search):
    js = _library_js()
    counts = _gql(library, _extract_query(js, "CARD_COUNTS_QUERY"),
                  appType=app_type, search=search, owned=None)
    for alias, extra in CARD_PILL_FILTERS:
        grid = _gql(library, _extract_query(js, "CARDS_QUERY"), page=1, pageSize=1,
                    appType=app_type, search=search, owned=None,
                    upToDate=extra.get("upToDate"), complete=extra.get("complete"),
                    orderBy={"field": "NAME", "direction": "ASC"})
        assert counts[alias]["total"] == grid["apps"]["total"], alias


@pytest.mark.parametrize("search", [None, "alpha"])
def test_list_pill_counts_equal_the_list_totals(library, search):
    js = _library_js()
    counts = _gql(library, _extract_query(js, "LIST_COUNTS_QUERY"), search=search)
    for alias, health in HEALTH:
        listed = _gql(library, _extract_query(js, "LIST_QUERY"), page=1, pageSize=1, search=search,
                      libraryHealth=health, orderBy={"field": "NAME", "direction": "ASC"})
        assert counts[alias]["total"] == listed["titles"]["total"], alias


def test_pills_are_one_request_and_follow_the_grid_variables(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="libraryPills"' in html
    js = _library_js()
    body = _function_body(js, "loadPillCounts")
    assert body.count("gqlFetch(") == 1
    assert "queryVariables()" in body and "listQueryVariables()" in body
    assert "function applyPill" in js and "function renderPills" in js
    assert "LIST_PILLS" in js


def test_pill_strings_are_translated():
    import i18n
    for key in ("library.pill_all", "library.pill_outdated", "library.pill_missing_dlc",
                "library.pill_up_to_date", "library.pill_complete", "library.pill_incomplete",
                "library.pill_corrupt", "library.pill_repack"):
        assert {"en", "es"} <= set(i18n.TRANSLATIONS[key]), key


# --- cards, icons and list rows ------------------------------------------------------

def _rule(css, selector):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return "\n".join(m.group(2) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
                     if selector in [s.strip() for s in m.group(1).split(",")])


def test_cards_use_the_surface_look_and_status_badges():
    body = _function_body(_library_js(), "renderCardView")
    for needle in ("library-card", "library-cover", "library-card-body", "library-card-meta",
                   "library-badges", "statusBadge('wait'", "is-missing", "attr('href', game.url)"):
        assert needle in body, needle
    # Catalogue text goes through .text(), never into HTML strings.
    assert "${game.name}" not in body and "${game.meta" not in body


def test_card_styles_use_tokens_only():
    css = _read("app", "static", "style.css")
    for selector in (".library-card", ".library-badges", ".library-card.is-missing .library-cover", ".library-card-meta",
                     ".library-icon"):
        body = _rule(css, selector)
        assert body.strip(), selector
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), selector


def test_phones_get_two_card_columns():
    assert "col-6 col-md-" in _function_body(_library_js(), "cardColumnClasses")


def test_card_badge_strings_are_translated():
    import i18n
    # The game page still shows these; a card only says when its base game is missing.
    for key in ("library.badge_update", "library.badge_missing_dlc", "library.badge_complete",
                "library.base_missing"):
        assert {"en", "es"} <= set(i18n.TRANSLATIONS[key]), key


# --- empty and error states -------------------------------------------------------------

def test_empty_and_error_states_exist(client):
    html = client.get("/").get_data(as_text=True)
    for needle in ('id="libraryEmpty"', 'id="clearFiltersBtn"', 'id="libraryEmptyLibrary"',
                   'id="libraryError"', 'id="libraryRetryBtn"'):
        assert needle in html, needle
    for state in ("libraryEmpty", "libraryEmptyLibrary", "libraryError"):
        assert re.search(rf'id="{state}"[^>]*hidden', html), state


def test_empty_library_links_admins_to_paths_and_upload(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code in (302, 303)
    html = shop_app.client.get("/").get_data(as_text=True)
    state = html.split('id="libraryEmptyLibrary"', 1)[1].split("</div>", 1)[0]
    assert 'href="/admin/settings#Library"' in state and 'href="/admin"' in state


def test_a_failed_query_shows_the_error_state_and_clear_resets_everything():
    js = _library_js()
    load = _function_body(js, "loadPage")
    assert "libraryError" in load.split("catch", 1)[1]
    clear = _function_body(js, "clearAllFilters")
    assert "searchTerm" in clear and "saveFiltersToStorage()" in clear and "resetToFirstPage()" in clear


def test_state_strings_are_translated():
    import i18n
    for key in ("library.empty_title", "library.empty_body", "library.clear_filters",
                "library.empty_library_title", "library.empty_library_body",
                "library.empty_library_admin", "library.error_title", "library.retry"):
        assert {"en", "es"} <= set(i18n.TRANSLATIONS[key]), key


def test_remembered_preferences_are_guarded_and_validated():
    js = _library_js()
    # Only the three helpers touch localStorage, each inside try/catch.
    uses = [l.strip() for l in js.splitlines() if "localStorage." in l]
    assert len(uses) == 3 and all(u.startswith("try {") for u in uses), uses
    assert "['card', 'icon', 'list'].includes(savedCurrentView)" in js
    assert "savedItemsPerPage > 0" in js and "savedCardSize >= 1" in js
    load = _function_body(js, "loadFiltersFromStorage")
    assert "try { filters = JSON.parse(" in load


def test_a_card_without_artwork_uses_a_local_placeholder():
    # placehold.it is gone, and the UI must not depend on the internet anyway.
    js = _library_js()
    assert "placehold.it" not in js
    body = _function_body(js, "renderCardView")
    assert "library-cover--empty" in body


@pytest.mark.parametrize("grouped", [True, False])
def test_cards_sort_by_the_catalogue_release_date(grouped):
    """Found in the browser check: `apps` sorted RELEASE_DATE by the app row's own date,
    empty for base games, so the cards came back unsorted. The schema promises the
    catalogue's date - the game's, as NAME uses the game's name, so a DLC sorts with
    its game - the same column `titles` sorts on."""
    from gql.filters import APP_ORDER, APP_ORDER_GROUPED, OrderBy, OrderDirection, OrderField, order_sql
    order = OrderBy(field=OrderField.RELEASE_DATE, direction=OrderDirection.DESC)
    sql = order_sql(order, APP_ORDER_GROUPED if grouped else APP_ORDER, "a.app_id")
    assert sql.startswith("td.release_date IS NULL, td.release_date DESC")


# --- final review fixes --------------------------------------------------------------

def test_state_pills_and_tiles_only_cover_owned_games(library):
    """The header tiles count owned games; the pills they apply must too, or "Games with
    a pending update: 12" opens a grid of every unowned DLC ("Update pending 340")."""
    js = _library_js()
    for name in ("outdated", "missingDlc", "upToDate"):
        assert re.search(rf"{name}: \{{[^}}]*ownership: 'Owned'", js), name
    assert re.search(r"all: \{[^}]*ownership: ''", js)
    counts = _extract_query(js, "CARD_COUNTS_QUERY")
    for alias in ("outdated", "missingDlc", "upToDate"):
        line = next(l for l in counts.splitlines() if l.strip().startswith(alias + ":"))
        assert "owned: true" in line, alias
    # ...and the counts still equal the grid for what each pill sets.
    data = _gql(library, counts, appType=["BASE", "DLC"], search=None, owned=None)
    for alias, extra in CARD_PILL_FILTERS[1:]:
        grid = _gql(library, _extract_query(js, "CARDS_QUERY"), page=1, pageSize=1,
                    appType=["BASE", "DLC"], search=None, owned=True,
                    upToDate=extra.get("upToDate"), complete=extra.get("complete"),
                    orderBy={"field": "NAME", "direction": "ASC"})
        assert data[alias]["total"] == grid["apps"]["total"], alias


def test_custom_page_size_is_a_whole_number_within_the_server_limit(client):
    html = client.get("/").get_data(as_text=True)
    assert re.search(r'id="customItemsPerPage"[^>]*min="1"[^>]*max="500"[^>]*step="1"', html)
    js = _library_js()
    assert "function clampPageSize" in js
    body = _function_body(js, "clampPageSize")
    assert "Math.floor" in body and "500" in body
    assert "clampPageSize(" in _function_body(js, "loadPage") or "clampPageSize($('#customItemsPerPage')" in js

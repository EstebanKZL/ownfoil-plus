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

def test_sort_controls_offer_every_field_and_both_directions(client):
    html = client.get("/").get_data(as_text=True)
    sel = html.split('id="sortField"', 1)[1].split("</select>", 1)[0]
    assert re.findall(r'value="(\w+)"', sel) == ["NAME", "RELEASE_DATE", "REGION", "SIZE", "ADDED_AT", "ID"]
    # One button per direction, the one in use lit (the single flip button didn't sit
    # well: back to the pair).
    assert 'class="btn btn-outline-secondary sort-direction-btn" data-direction="ASC"' in html
    assert 'class="btn btn-outline-secondary sort-direction-btn" data-direction="DESC"' in html


def test_the_list_view_is_a_desk_thing(client):
    html = client.get("/").get_data(as_text=True)
    # Hidden on phones, and a remembered list becomes cards there.
    assert 'view-toggle-btn d-none d-sm-inline-flex" data-view="list"' in html
    js = _library_js()
    assert "savedCurrentView === 'list' && window.matchMedia('(max-width: 575.98px)')" in js


def test_owned_cards_and_rows_wear_the_library_mark():
    js = _library_js()
    # The gray check on the covers went (asked for): the card keeps its badges and the
    # star, and the List view's rows still wear the game page's badge ("En la
    # biblioteca", check in its circle) instead of a plain Bootstrap pill.
    assert "library-card-check" not in js
    css = _read("app", "static", "style.css")
    assert ".library-card-check" not in css
    assert "statusBadge('ok', 'bi-check-circle', I18N.inLibrary)" in js


def test_the_console_filter_is_one_stadium_bar():
    css = _read("app", "static", "style.css")
    rule = re.search(r"#libraryConsole \{([^}]*)\}", css).group(1)
    assert "border-radius: 2rem" in rule and "var(--op-surface-1)" in rule
    # Only the resting pills go transparent: the chosen one keeps the accent fill
    # (an id-scoped rule on every pill used to swallow it).
    assert "#libraryConsole .filter-pill:not(.active)" in css
    assert not re.search(r"#libraryConsole \.filter-pill \{[^}]*background", css)
    # The chosen option carries its count as a nested pill, Switch Library style.
    assert re.search(r"#libraryConsole \.filter-pill\.active \.filter-pill__count \{[^}]*border-radius: 1rem", css)


def test_the_list_titles_state_their_mark_and_both_versions():
    js = _library_js()
    body = _function_body(js, "renderListView")
    # No date after "Latest version"; the pill keeps its green/amber state and reads
    # both ways ("3.0.0 · v1048576") - the state ICON beside it was the part that
    # went (asked for), not the pill.
    assert "latestDate" not in body
    assert "latest.displayVersion" in body and "· v${latest.appVersion}" in body
    assert "text-bg-success" in body and "text-bg-warning" in body
    assert "bi-check-circle-fill" not in body and "bi-arrow-down-circle" not in body
    # Every update row reads both names too, in the collapsible sections.
    assert "a.displayVersion ? `${a.displayVersion} · v${a.appVersion}`" in js


@pytest.mark.parametrize("field", ["REGION", "SIZE", "ADDED_AT", "ID"])
@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_shipped_queries_sort_by_every_field(library, field, direction):
    js = _library_js()
    order = {"field": field, "direction": direction}
    cards = _gql(library, _extract_query(js, "CARDS_QUERY"), page=1, pageSize=20,
                 appType=["BASE", "DLC"], orderBy=order)
    assert cards["apps"]["total"] == 2
    listed = _gql(library, _extract_query(js, "LIST_QUERY"), page=1, pageSize=20, owned=True, orderBy=order)
    assert listed["titles"]["total"] == 1


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
    listed = _gql(library, _extract_query(js, "LIST_QUERY"), page=1, pageSize=20, owned=True, orderBy=order)
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


def test_header_tiles_replace_the_stats_line(client):
    html = client.get("/").get_data(as_text=True)
    # No count beside the title (the Games tile says it).
    assert 'class="page-head' in html and 'id="libraryCount"' not in html
    assert re.search(r'id="libraryTiles"[^>]*hidden', html)
    # The big percentage bar is gone: the "Up to date" tile carries the share.
    assert 'id="libraryProgress"' not in html
    assert 'id="libraryStats"' not in html


def test_tiles_are_computed_from_the_stats_query():
    body = _function_body(_library_js(), "renderLibraryStats")
    assert "ownedTitles - stats.upToDateTitles" in body
    assert "stats.missingDlc.toLocaleString()" in body
    # No size tile (it was admin only): the same four tiles for everyone.
    assert "stats.totalFiles" not in body and "I18N.tileUpToDate.replace('{pct}', pct)" in body
    assert "stat-tile__bar-fill" in body
    # Pending updates and missing DLC tiles apply their filter.
    assert 'data-pill' in body or "dataset.pill" in body


def test_tiles_and_sections_wear_the_fixed_type_colors():
    js = _library_js()
    # The tiles that identify a content type keep its fixed color in every style:
    # games coral (base), updates amber, missing DLC cyan; "up to date" stays the
    # green of done. None of them follows the style's accent.
    block = re.search(r"const tiles = \[(.*?)\];", js, re.DOTALL).group(1)
    for tone in ("'base'", "'wait'", "'dlc'", "'ok'"):
        assert tone in block, tone
    assert "'nav'" not in block and "'action'" not in block
    # The list view identifies its sections the same way: a colored dot on the base
    # game's row and on the Updates / DLC headers.
    assert "tone: 'base'," in js and "updateRows, 'update')" in js and "}), 'dlc'));" in js
    assert "list-section-dot list-section-dot--${tone}" in js


def test_library_header_strings_are_translated(client):
    import i18n
    for key in ("library.title", "library.subtitle", "library.tile_games", "library.tile_updates",
                "library.tile_dlc_missing", "library.tile_up_to_date"):
        assert {"en", "es"} <= set(i18n.TRANSLATIONS[key]), key


# --- toolbar, View and Filters menus ---------------------------------------------------

def test_toolbar_holds_search_sort_views_and_both_menus(client):
    html = client.get("/").get_data(as_text=True)
    bar = html.split('class="toolbar library-toolbar', 1)[1].split('<!-- Pagination controls (top)', 1)[0]
    for needle in ('id="textFilter"', 'id="sortField"', 'sort-direction-btn', 'data-view="card"',
                   'data-view="icon"', 'data-view="list"', 'id="viewMenuBtn"', 'id="filtersMenuBtn"',
                   'id="pageSizeOptions"', 'id="filtersActiveDot"'):
        assert needle in bar, needle
    # Every filter group lives in the one Filters menu, the same for every view.
    menu = bar.split('id="filtersMenuBtn"', 1)[1]
    for group in ("Ownership filter", "Update filter", "Completion filter", "Favourites"):
        assert f'aria-label="{group}"' in menu, group
    assert 'listHealthFilterCol' not in menu
    assert "filterDropdownBtn" not in html and "listHealthDropdownBtn" not in html


def test_filters_dot_counts_every_filter():
    body = _function_body(_library_js(), "updateFiltersDot")
    assert "activeHealthFilter" not in body
    for name in ("activeOwnershipFilter", "activeUpdateFilter", "activeCompletionFilter", "onlyFavorites"):
        assert name in body, name


# --- console pills with exact counts ------------------------------------------------
#
# The row under the toolbar holds the console choice only (the other filters are in the
# Filters menu); its counts follow the view's own filters.

CONSOLES = (("consoleAll", None), ("consoleSwitch", "switch"), ("consoleSwitch2", "switch2"))


@pytest.mark.parametrize("app_type,search,up_to_date", [(["BASE", "DLC"], None, None), (["BASE"], None, False),
                                                        (["BASE", "DLC"], "alpha", None), (["DLC"], "nothing-matches", None)])
def test_console_counts_equal_the_grid_totals(library, app_type, search, up_to_date):
    js = _library_js()
    counts = _gql(library, _extract_query(js, "CARD_COUNTS_QUERY"),
                  appType=app_type, search=search, owned=None, upToDate=up_to_date)
    for alias, console in CONSOLES:
        grid = _gql(library, _extract_query(js, "CARDS_QUERY"), page=1, pageSize=1,
                    appType=app_type, search=search, owned=None, upToDate=up_to_date, console=console,
                    orderBy={"field": "NAME", "direction": "ASC"})
        assert counts[alias]["total"] == grid["apps"]["total"], alias


@pytest.mark.parametrize("search", [None, "alpha"])
def test_list_console_counts_equal_the_list_totals(library, search):
    js = _library_js()
    counts = _gql(library, _extract_query(js, "LIST_COUNTS_QUERY"), search=search, owned=True)
    for alias, console in CONSOLES:
        listed = _gql(library, _extract_query(js, "LIST_QUERY"), page=1, pageSize=1, search=search,
                      owned=True, console=console, orderBy={"field": "NAME", "direction": "ASC"})
        assert counts[alias]["total"] == listed["titles"]["total"], alias


def test_one_pill_row_left_the_console_one(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="libraryConsole"' in html and 'id="libraryPills"' not in html
    js = _library_js()
    body = _function_body(js, "loadPillCounts")
    assert body.count("gqlFetch(") == 1
    assert "queryVariables()" in body and "listQueryVariables()" in body
    # The tiles still apply the common filters.
    assert "function applyPill" in js and "LIST_PILLS" not in js
    assert "const row = $('#libraryConsole').empty();" in js   # every view, the list too


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
                     ".compact-card"):
        body = _rule(css, selector)
        assert body.strip(), selector
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), selector


def test_phones_get_one_card_a_row():
    """Two cards side by side on a phone cut the title and broke the id; Compact keeps two."""
    assert "col-12 col-sm-6 col-md-" in _function_body(_library_js(), "cardColumnClasses")


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
    assert "$('#textFilter').val('')" in clear and "saveFiltersToStorage()" in clear and "resetToFirstPage()" in clear


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
    assert "savedTarget >= 10 && savedTarget <= 100 && savedTarget % 10 === 0" in js
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

def test_state_tiles_only_cover_owned_games():
    """The header tiles count owned games; the filters they apply must too, or "Games
    with a pending update: 12" opens a grid of every unowned DLC."""
    js = _library_js()
    for name in ("outdated", "missingDlc", "upToDate"):
        assert re.search(rf"{name}: \{{[^}}]*ownership: 'Owned'", js), name
    assert re.search(r"all: \{[^}]*ownership: ''", js)


def test_page_sizes_fill_whole_rows_from_10_to_100(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="customItemsPerPage"' not in html and 'id="cardSizeRange"' not in html
    js = _library_js()
    options = _function_body(js, "pageSizeOptions")
    assert "target <= 100; target += 10" in options and "Math.ceil(target / columns) * columns" in options
    assert "Math.floor(100 / columns) * columns" in options
    # A resize that changes the columns refits the page size.
    assert "refitPageSize(true)" in js and "window.addEventListener('resize'" in js


def test_size_sorts_by_what_the_library_holds():
    """Sorting by size with both consoles mixed Switch 2 games in apart (their catalogue
    size is missing or written differently): the size is the files' own now."""
    from gql.filters import APP_ORDER, TITLE_ORDER
    for order in (APP_ORDER, TITLE_ORDER):
        assert "SUM(fl.size)" in order["size"] and "COALESCE" in order["size"]


def test_the_tile_in_use_is_marked_and_lifts_smoothly():
    js = _library_js()
    assert "function markActiveTile()" in js and "tile.classList.toggle('is-active', on)" in js
    assert "const on = tile.dataset.pill === active;" in js          # "Games" too
    css = _read("app", "static", "style.css")
    assert ".stat-tile.is-active" in css
    assert re.search(r"button\.stat-tile,\s*a\.stat-tile \{\s*transition: transform", css)


def test_a_template_with_an_unknown_field_is_refused(client, shop_app):
    import fixture
    shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    body = shop_app.client.post('/api/settings/library/management', json={
        'organizer': {'templates': {'multi': '{titleName} [{packageNamez}]'}}}).get_json()
    assert body['success'] is False and body['errors'][0]['error'] == '{packageNamez}'


def test_the_search_lasts_while_on_the_page_and_list_updates_have_no_date():
    """Views and filters keep the search (same page); coming back from another page it is
    empty - only the filters are remembered. The List view's updates show no date."""
    js = _library_js()
    assert "storageSet('searchTerm'" not in js and "storageRemove('searchTerm');" in js
    assert "sub: a.releaseDate" not in js


def test_sagas_go_by_pages_of_24_and_complete_ones_are_gold():
    js = _read("app", "static", "js", "sagas.js")
    assert "Pager.perPage('sagas', SAGA_SIZES, 24)" in js and "card.classList.toggle('is-complete', complete);" in js
    assert "bi-trophy-fill" in js
    css = _read("app", "static", "style.css")
    # Gold at rest, trophy and count always gold - but the frame yields to the hover
    # marking like any other card (asked for after pinning it by mistake).
    assert re.search(r"\.saga-card\.is-complete \{[^}]*--op-fav-rgb", css)
    assert re.search(r"\.saga-card\.is-complete:hover \{[^}]*--op-nav-rgb", css)
    # 1, 2 or 3 columns: each divides every size offered (12, 24, 48, 96), so only the
    # last page has a short row.
    assert "repeat(3, minmax(0, 1fr))" in css[css.index(".saga-grid {"):]


def test_two_or_more_folders_give_a_folder_filter_and_sort(client, shop_app):
    """With two library folders the Library filters and sorts by folder - by its name,
    never its path - and Statistics shows each with its games and free space."""
    import os
    with shop_app.app.app_context():
        from db import Libraries, db
        parent = os.path.dirname(Libraries.query.first().path)
        db.session.add(Libraries(path=os.path.join(parent, 'second-games')))
        db.session.commit()
    html = client.get("/").get_data(as_text=True)
    assert 'name="folderFilter"' in html and '<option value="FOLDER">' in html
    assert 'second-games' in html and parent not in html.split('LIBRARY_FOLDERS')[1][:400]
    js = _library_js()
    assert "libraryId: activeFolder," in js and "$libraryId: Int" in js


def test_titles_and_apps_filter_by_folder(client, shop_app):
    with shop_app.app.app_context():
        from db import Libraries
        lib_id = Libraries.query.first().id
    body = client.post("/api/graphql", json={"query": f"""{{
        a: titles(owned: true, libraryId: {lib_id}, page: 1, pageSize: 5) {{ total }}
        b: titles(owned: true, libraryId: 999999, page: 1, pageSize: 5) {{ total }}
        c: apps(groupByAppId: true, libraryId: 999999, page: 1, pageSize: 5) {{ total }}
        d: apps(groupByAppId: true, orderBy: {{field: FOLDER}}, page: 1, pageSize: 5) {{ total }}
        stats {{ libraryFolders {{ id name games files free }} }} }}"""}).get_json()
    assert not body.get("errors"), body
    data = body["data"]
    assert data["b"]["total"] == 0 and data["c"]["total"] == 0
    assert data["stats"]["libraryFolders"] is None          # a shop user: no stats

    # An admin gets each folder with its games and the free space of its disk.
    shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    stats = shop_app.client.post("/api/graphql", json={"query": "{ stats { libraryFolders { id name path games free } } }"}).get_json()
    folder = stats["data"]["stats"]["libraryFolders"][0]
    assert folder["id"] == lib_id and folder["path"] and folder["games"] >= 0

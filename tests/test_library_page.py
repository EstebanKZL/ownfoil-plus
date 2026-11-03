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

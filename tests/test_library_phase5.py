"""Phase 5: the Library after opening a game (A), file format, update mark and DLC count
on the cards (C), and the Compact view (D)."""
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _js(name):
    return _read("app", "static", "js", name)


def _function_body(js, name):
    start = js.index(f"function {name}(")
    depth, i = 0, js.index(") {", start) + 2
    while True:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        i += 1
        if depth == 0:
            return js[start:i]


# --- A: back from a game, the Library as it was left ------------------------------------------

def test_coming_back_from_a_game_keeps_the_page_filters_and_scroll():
    """Asked for later: back from a game, the same page of the grid (not page 1), with
    the filters and search it had."""
    js = _js("library.js")
    assert "forgetFiltersForGame" not in js and "clearAllFilters();\n    }\n});" not in js
    assert "sessionStorage.setItem('libraryPage', String(currentPage))" in js
    restore = js[js.index("nav.type === 'back_forward'"):]
    restore = restore[:restore.index("sessionStorage.removeItem('libraryPage')")]
    assert "sessionStorage.getItem('libraryPage')" in restore and "currentPage = page" in restore


def test_the_page_state_comes_only_from_what_is_stored():
    """Seen in the browser: back from a game, the browser filled the search box in again
    by itself (it restores form fields), and the list stayed searched."""
    body = _function_body(_js("library.js"), "loadFiltersFromStorage")
    assert "$('#textFilter').val(savedSearch || '')" in body
    assert "['#ownershipAll', '#updateAll', '#completionAll', '#healthAll'].forEach(" in body
    html = _read("app", "templates", "index.html")
    assert re.search(r'<input type="search" id="textFilter"[^>]*autocomplete="off"', html)


# --- D: the Compact view ---------------------------------------------------------------------

def test_the_icon_view_is_now_the_compact_view(shop_app):
    import fixture
    from i18n import TRANSLATIONS
    assert TRANSLATIONS["library.view_compact"]["es"] == "Vista compacta"
    assert "library.view_icons" not in TRANSLATIONS
    client = shop_app.client
    client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    html = client.get("/").get_data(as_text=True)
    button = re.search(r'<button id="view-toggle-btn-icon"[^>]*>.*?</button>', html, re.S).group(0)
    assert 'title="Compact view"' in button and "bi-grid-3x3-gap-fill" in button


def test_a_compact_card_carries_cover_name_meta_id_and_badges():
    body = _function_body(_js("library.js"), "renderCompactView")
    for part in ("compact-card", "game.iconUrl", "library-card-title", "cardMetaLine(game.meta)",
                 "library-card-id", "dlcCountText(", "coverFormat(game)", "library-cover-update",
                 "data-firmware-title", "library-badges", "attr('href', game.url)", "is-missing"):
        assert part in body, part
    assert "renderIconView" not in _js("library.js")
    assert "library-cover-format" in _function_body(_js("library.js"), "coverFormat")


def test_the_compact_query_brings_what_the_cards_show():
    query = re.search(r"const ICONS_QUERY = `(.*?)`;", _js("library.js"), re.S).group(1)
    for field in ("dlcOwned", "dlcTotal", "upToDate", "downloadableFile { format }", "publisher", "releaseDate", "iconUrl"):
        assert field in query, field


def test_the_compact_grid_fits_five_or_six_a_row_and_two_on_a_phone():
    css = _read("app", "static", "style.css")
    grid = re.search(r"#gameGrid\.compact-grid \{([^}]*)\}", css).group(1)
    assert "display: grid" in grid and "minmax(min(46%, var(--compact-min, 10rem)), 1fr)" in grid
    sizes = _function_body(_js("library.js"), "adjustCompactSizes")
    assert "--compact-min" in sizes
    loader = _js("library.js")
    assert "$('#gameGrid').toggleClass('compact-grid', currentView === 'icon')" in loader

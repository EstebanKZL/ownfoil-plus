"""Coverage for translating the library page (app/templates/index.html): the filter
dropdown, search/pagination controls, and the JS-generated Card/List view content, in
both languages - plus the by-now-familiar structural regression guard against the
inline <script> block being accidentally split.
"""
import re

import fixture
import pytest


def _page_and_js(client):
    """The page plus static/js/library.js, where its logic lives since stage 2: tests of
    JS-built content look at both."""
    return (client.get("/").get_data(as_text=True)
            + client.get("/static/js/library.js").get_data(as_text=True))


@pytest.fixture
def client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def test_library_page_renders_in_english_by_default(client):
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Search titles..." in html
    assert "Items per page" in html
    assert ">Owned<" in html
    assert ">Missing<" in html
    assert "Missing Update" in html
    assert "Missing DLC" in html


def test_library_page_renders_in_spanish(client):
    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Buscar títulos..." in html
    assert "Elementos por página" in html
    assert ">Poseído<" in html
    assert ">Faltante<" in html
    assert "Falta update" in html
    assert "Falta DLC" in html


def test_the_i18n_object_carries_spanish_values_for_the_list_view(client):
    """The Card/Icon/List views build most of their text in JS from the I18N object
    (Owned/Missing badges, Base Game, section titles, metadata labels) rather than
    static HTML - confirm the object itself carries the Spanish strings through render."""
    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert "const I18N = {" in html
    assert '"Juego base"' in html      # baseGame
    assert '"No reconocido"' in html   # unrecognized


def test_list_view_health_filter_dropdown_is_present_and_hidden_by_default(client):
    """The dropdown for the List view's own Complete/Incomplete/Corrupt/Repack
    filter - present in the DOM (server-rendered), but hidden by default since
    Card/Icon is the default view; the JS toggles it visible when List is selected."""
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert 'id="listHealthFilterCol"' in html
    col_tag = [line for line in html.splitlines() if 'id="listHealthFilterCol"' in line][0]
    assert "d-none" in col_tag
    assert 'id="healthComplete"' in html
    assert 'id="healthIncomplete"' in html
    assert 'id="healthCorrupt"' in html
    assert 'id="healthRepack"' in html


def test_list_view_health_filter_labels_are_translated(client):
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert "Complete" in html
    assert "Incomplete" in html
    assert "Corrupt" in html
    assert "Repack" in html

    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert "Completos" in html
    assert "Incompletos" in html
    assert "Corruptos" in html


def test_game_detail_fields_are_translated(client):
    """The game's detail tiles - Players/Genre/Rating/File size/Languages/Title ID - live
    on its own page since stage 3 (the Library's modal is gone), in both languages."""
    html = client.get("/game/0100000000010000").get_data(as_text=True)
    for label in ("Players", "Genre", "Rating", "File size", "Languages", "Title ID"):
        assert label in html, label

    client.set_cookie("ownfoil_lang", "es")
    html = client.get("/game/0100000000010000").get_data(as_text=True)
    assert "Jugadores" in html
    # Inside a JS string literal (rendered through |tojson), accented characters appear
    # \uXXXX-escaped in the raw HTML; a browser decodes them at parse time.
    assert "G\\u00e9nero" in html          # Género
    assert "Clasificaci\\u00f3n" in html   # Clasificación
    assert "Tama\\u00f1o" in html          # Tamaño
    assert "Idiomas" in html

def test_pagination_controls_exist_at_both_top_and_bottom(client):
    """Two identical pagination bars - top one right under the stats line, bottom one
    below the grid - both driven by the same updatePaginationControls() function."""
    html = _page_and_js(client)
    assert 'id="paginationControlsTop"' in html
    assert 'id="paginationControlsBottom"' in html
    assert "function updatePaginationControls" in html
    assert "paginationControlsTop" in html and "paginationControlsBottom" in html


def test_library_page_script_is_not_split_by_a_stray_closing_tag(client):
    """Same regression class as the other pages' equivalent tests."""
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    script_blocks = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(script_blocks) == 1, (
        f"Expected exactly one inline <script>...</script> block, found {len(script_blocks)}")
    body = script_blocks[0]
    assert "const I18N = {" in body
    # The page logic itself lives in static/js/library.js since stage 2.
    js = client.get("/static/js/library.js").get_data(as_text=True)
    assert "function renderListView" in js
    assert "function renderCardView" in js


def test_internal_filter_state_identifiers_are_not_accidentally_translated(client):
    """activeOwnershipFilter etc. compare against literal English strings ('Owned',
    'Missing', 'DLC', ...) that are never displayed - only the <label> text wrapping
    them should have changed. Confirm the JS-side comparisons survived untouched."""
    html = _page_and_js(client)

    assert "activeOwnershipFilter === 'Owned'" in html
    assert "activeOwnershipFilter = 'Owned';" in html

"""Coverage for translating the library page (app/templates/index.html): the filter
dropdown, search/pagination controls, and the JS-generated Card/List view content, in
both languages - plus the by-now-familiar structural regression guard against the
inline <script> block being accidentally split.
"""
import re

import fixture
import pytest


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
    assert ">Details<" in html


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
    assert ">Detalles<" in html


def test_the_i18n_object_carries_spanish_values_for_the_list_view(client):
    """The Card/Icon/List views build most of their text in JS from the I18N object
    (Owned/Missing badges, Base Game, section titles, metadata labels) rather than
    static HTML - confirm the object itself carries the Spanish strings through render."""
    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert "const I18N = {" in html
    assert '"Juego base"' in html      # baseGame
    assert '"Desarrollador"' in html   # developer
    assert '"Editor"' in html          # publisher
    assert '"No reconocido"' in html   # unrecognized


def test_library_page_script_is_not_split_by_a_stray_closing_tag(client):
    """Same regression class as the other pages' equivalent tests."""
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    script_blocks = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(script_blocks) == 1, (
        f"Expected exactly one inline <script>...</script> block, found {len(script_blocks)}")
    body = script_blocks[0]
    assert "const I18N = {" in body
    assert "function renderListView" in body
    assert "function renderCardView" in body
    assert "function openMetadata" in body


def test_internal_filter_state_identifiers_are_not_accidentally_translated(client):
    """activeOwnershipFilter etc. compare against literal English strings ('Owned',
    'Missing', 'DLC', ...) that are never displayed - only the <label> text wrapping
    them should have changed. Confirm the JS-side comparisons survived untouched."""
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert "activeOwnershipFilter === 'Owned'" in html
    assert "activeOwnershipFilter = 'Owned';" in html
    assert "activeTypeFilter = 'DLC';" in html

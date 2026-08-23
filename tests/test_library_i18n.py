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


def test_metadata_edit_ui_is_present(client):
    """The editable-metadata form (backed by the existing setTitleOverride /
    deleteTitleOverride mutations) built for the Fantasy Life i / titledb-incomplete
    scenario - present in the DOM, hidden until an admin opens edit mode."""
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert 'id="metadataEditBtn"' in html
    assert 'id="metadataEditFooter"' in html
    assert 'id="metadataResetBtn"' in html
    assert 'id="metadataSaveBtn"' in html
    assert "function renderMetadataEditForm" in html
    assert "setTitleOverride" in html
    assert "deleteTitleOverride" in html


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


def test_metadata_modal_new_detail_fields_are_translated(client):
    """The enriched metadata modal's new icon rows - Players/Genre/Rating/File
    size/Languages/Title ID/Type - all render with translated labels, both languages."""
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert "Players" in html
    assert "Genre" in html
    assert "Rating" in html
    assert "File size" in html
    assert "Languages" in html
    assert "Title ID" in html
    assert "Type" in html

    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert "Jugadores" in html
    # These live inside a JS string literal (I18N object, rendered through |tojson) -
    # accented characters there appear \uXXXX-escaped in the raw HTML, which a browser
    # decodes normally at parse time.
    assert "G\\u00e9nero" in html          # Género
    assert "Clasificaci\\u00f3n" in html   # Clasificación
    assert "Tama\\u00f1o" in html          # Tamaño
    assert "Idiomas" in html


def test_metadata_modal_dialog_is_the_larger_size(client):
    """Wide enough for the two-column banner+details layout and the screenshot
    carousel - the plain default modal size was too cramped for it."""
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert 'id="metadataModal"' in html
    modal_section = html[html.index('id="metadataModal"'):][:400]
    assert "modal-lg" in modal_section


def test_metadata_modal_html_helpers_are_present(client):
    """The rendering functions and screenshot carousel markup this feature added."""
    resp = client.get("/")
    html = resp.get_data(as_text=True)
    assert "function metadataDetailRows" in html
    assert "metadataScreenshotCarousel" in html
    assert "carousel-item" in html
    assert "new bootstrap.Carousel" in html


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

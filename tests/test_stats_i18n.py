"""Coverage for translating the Stats page (app/templates/stats.html) into the i18n
system: the page renders correctly in both languages, and - since a stray `</script>`
tag once silently orphaned half the page's JS outside any script block while this was
being built - a structural regression guard against that happening again.
"""
import os
import re

import fixture
import pytest



def _page_and_js(client):
    """The Statistics page plus static/js/stats.js, where its logic lives since stage 4."""
    return (client.get("/admin/stats").get_data(as_text=True)
            + client.get("/static/js/stats.js").get_data(as_text=True))

@pytest.fixture
def client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def test_stats_page_renders_in_english_by_default(client):
    html = _page_and_js(client)

    assert client.get("/admin/stats").status_code == 200
    assert "Verification status" in html
    assert "Verify pending files" in html
    assert "Extensions" in html
    assert "App types" in html


def test_stats_page_renders_in_spanish(client):
    client.set_cookie("ownfoil_lang", "es")
    html = _page_and_js(client)

    assert client.get("/admin/stats").status_code == 200
    assert "Estado de verificación" in html
    assert "Verificar faltantes" in html
    assert "Extensiones" in html
    assert "Tipos de aplicación" in html
    # The verification-status labels are JS literals rendered through |tojson, so they
    # appear unicode-escaped in the raw HTML rather than as literal accented text -
    # that's normal (a browser decodes \uXXXX in a JS string literal at parse time),
    # not a translation gap.
    assert "V\\u00e1lido" in html
    assert "Sin verificar" in html


def test_the_inline_script_is_not_split_by_a_stray_closing_tag(client):
    """Regression guard: the I18N object literal and the rest of the page's JS
    (STATS_QUERY, loadStats, the verify-now button handler, ...) must live in one
    continuous <script> block. An extra </script> after the I18N object once silently
    orphaned everything after it outside any script tag - broken, but with no visible
    symptom short of opening the browser console."""
    html = _page_and_js(client)

    page = client.get("/admin/stats").get_data(as_text=True)
    script_blocks = re.findall(r"<script>(.*?)</script>", page, re.DOTALL)
    assert len(script_blocks) == 1, (
        f"Expected exactly one inline <script>...</script> block, found {len(script_blocks)}")
    assert "const I18N = {" in script_blocks[0]
    body = client.get("/static/js/stats.js").get_data(as_text=True)  # the logic, since stage 4
    assert "const STATS_QUERY" in body
    assert "function loadStats" in body
    assert "verifyNowBtn" in body


def test_verify_now_button_is_aligned_with_the_table_not_the_heading(client):
    """The button previously sat right after a hint span crammed next to the h4
    (ms-auto on the button, but competing for space with that span) - now the header
    row is a plain two-item flex (heading left, button right) and the hint moved below
    the table entirely."""
    html = _page_and_js(client)

    header_start = html.index("stats.verification_status") if "stats.verification_status" in html \
        else html.index("Verification status")
    button_idx = html.index('id="verifyNowBtn"')
    hint_idx = html.index('stats.click_row_hint') if 'stats.click_row_hint' in html \
        else html.index("Click a row to see which titles")
    table_idx = html.index('id="byVerification"')

    # Button comes before the hint moved past it, and the hint now sits after the
    # table (byVerification), not between the heading and the button.
    assert header_start < button_idx
    assert table_idx < hint_idx, "The row-click hint should now appear after the table"


def test_verify_now_header_row_is_capped_to_the_table_width(client):
    """Regression guard: justify-content-between only lands the button flush with the
    table's actual right edge if the header row is capped to the same max-width as
    .stat-table - otherwise it right-aligns against the wider section column and
    visibly overshoots past "Size", which is exactly what was reported."""
    html = _page_and_js(client)

    assert "stat-section-head" in html

    css_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "style.css")
    with open(css_path) as f:
        css = f.read()
    assert ".stat-section-head" in css
    assert "max-width: 30rem" in css


def test_missing_app_type_modal_is_present_and_translated(client):
    html = _page_and_js(client)
    assert 'id="missingAppTypeModal"' in html
    assert 'id="missingAppTypeList"' in html
    assert 'id="missingAppTypePrev"' in html
    assert 'id="missingAppTypeNext"' in html
    assert "function openMissingAppType" in html
    assert "const MISSING_APP_TYPE_QUERY" in html
    assert "missingAppType:" in html

    client.set_cookie("ownfoil_lang", "es")
    html = _page_and_js(client)
    assert "T\\u00edtulos" in html or "Títulos" in html


def test_missing_app_type_modal_is_not_nested_inside_the_verification_files_modal(client):
    """Regression: a previous edit spliced this modal's markup in before the first
    modal's own closing </div>s, leaving it nested *inside* verificationFilesModal
    instead of a sibling - Bootstrap doesn't handle a modal nested inside another
    modal correctly (the reported symptom: the backdrop darkened but nothing showed,
    and there was no way to dismiss it short of reloading the page)."""
    html = _page_and_js(client)

    verif_start = html.index('id="verificationFilesModal"')
    missing_start = html.index('id="missingAppTypeModal"')
    assert missing_start > verif_start

    # Walk the div balance from the start of the first modal's own opening tag: the
    # first point where it returns to 0 is that modal's own closing </div> - the
    # second modal's opening tag must appear at or after that point, never before it.
    first_modal_open = html.rindex("<div", 0, verif_start)
    depth = 0
    i = first_modal_open
    closed_at = None
    while i < len(html):
        if html.startswith("<div", i):
            depth += 1
            i += 4
        elif html.startswith("</div>", i):
            depth -= 1
            i += 6
            if depth == 0:
                closed_at = i
                break
        else:
            i += 1
    assert closed_at is not None, "could not find verificationFilesModal's closing tag"
    assert missing_start >= closed_at, (
        "missingAppTypeModal starts before verificationFilesModal's own closing "
        "</div> - it is nested inside it instead of being a sibling"
    )


def test_library_detail_modal_is_present_and_translated(client):
    html = _page_and_js(client)
    assert 'id="libraryDetailModal"' in html
    assert 'id="libraryDetailBody"' in html
    assert 'id="libraryDetailPrev"' in html
    assert 'id="libraryDetailNext"' in html
    assert "function openLibraryDetail" in html
    assert "const LIBRARY_DETAIL_QUERY" in html
    assert "libraryId:" in html          # a folder by its id (a collaborator has no path)
    assert "const CLEAN_APP_MUTATION" in html
    assert "const CLEAN_TITLE_MUTATION" in html
    assert "cleanAppRecord" in html
    assert "cleanTitleRecord" in html

    client.set_cookie("ownfoil_lang", "es")
    html = _page_and_js(client)
    assert "Limpiar solo el registro" in html


def test_library_detail_modal_is_not_nested_inside_another_modal(client):
    """Same regression class as missingAppTypeModal's own guard above - confirmed
    fresh this time, up front, rather than after the fact."""
    html = _page_and_js(client)

    missing_start = html.index('id="missingAppTypeModal"')
    detail_start = html.index('id="libraryDetailModal"')
    assert detail_start > missing_start

    first_modal_open = html.rindex("<div", 0, missing_start)
    depth = 0
    i = first_modal_open
    closed_at = None
    while i < len(html):
        if html.startswith("<div", i):
            depth += 1
            i += 4
        elif html.startswith("</div>", i):
            depth -= 1
            i += 6
            if depth == 0:
                closed_at = i
                break
        else:
            i += 1
    assert closed_at is not None
    assert detail_start >= closed_at, (
        "libraryDetailModal starts before missingAppTypeModal's own closing </div>"
    )


def test_library_detail_modal_groups_updates_and_dlc_into_collapsible_sections(client):
    """The base game stays directly visible, but Updates/DLC group behind the same
    collapsible section style the List view uses, rather than a flat list of every
    app - requested after the first version rendered everything flat."""
    html = _page_and_js(client)
    assert "function buildLibraryDetailSection" in html
    assert "list-section-trigger" in html
    assert "list-chevron" in html
    assert "updatesSection:" in html


def test_all_three_drill_down_modals_have_a_debounced_search_box(client):
    """Requested after the first version of these modals had no way to narrow a long
    list down - each gets its own search input, wired into the query's existing
    search/filter capability (titles already had `search`; files got `filename:
    {contains:}`), debounced the same 250ms the List view's own search box uses."""
    html = _page_and_js(client)

    assert 'id="libraryDetailSearch"' in html
    assert 'id="missingAppTypeSearch"' in html
    assert 'id="verificationFilesSearch"' in html

    assert "libraryDetailSearchDebounce" in html
    assert "missingAppTypeSearchDebounce" in html
    assert "verificationSearchDebounce" in html

    # Each query actually threads the term through, not just an unused input sitting there.
    assert "libraryId: $path, search: $search" in html   # the folder by id: no path needed
    assert "missingAppType: $type, search: $search" in html
    assert "filename: {contains: $search}" in html


def test_both_clean_and_delete_actions_are_always_available_no_settings_toggle(client):
    """No settings toggle gates these anymore - admin access (implicit, since this
    whole page requires it) is the only gate. Two distinct icons for two distinct
    actions: bi-database-x for the database-only clean, bi-trash for the real,
    irreversible delete-from-disk."""
    html = _page_and_js(client)
    assert "CLEAN_RECORD_ENABLED" not in html
    assert "webCleanRecordEnabledCheck" not in html
    assert "bi-database-x" in html
    assert "bi-trash" in html
    assert "function handleCleanClick" in html
    assert "function handleDeleteClick" in html
    assert "function handleRecordAction" in html
    assert "const DELETE_APP_MUTATION" in html
    assert "const DELETE_TITLE_MUTATION" in html
    assert "deleteAppRecord" in html
    assert "deleteTitleRecord" in html


def test_duplicate_files_are_handled_on_the_files_page_not_in_stats(client):
    """Stats only reports: duplicates are resolved under Files (its Duplicates tab)."""
    html = _page_and_js(client)
    assert 'id="duplicatesSection"' not in html
    assert "loadDuplicateGroups" not in html

    page = client.get("/admin/stats").get_data(as_text=True)
    script_blocks = re.findall(r"<script>(.*?)</script>", page, re.DOTALL)
    assert len(script_blocks) == 1
    body = client.get("/static/js/stats.js").get_data(as_text=True)
    assert "function loadStats" in body

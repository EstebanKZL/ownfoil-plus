"""Coverage for translating the Stats page (app/templates/stats.html) into the i18n
system: the page renders correctly in both languages, and - since a stray `</script>`
tag once silently orphaned half the page's JS outside any script block while this was
being built - a structural regression guard against that happening again.
"""
import os
import re

import fixture
import pytest


@pytest.fixture
def client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def test_stats_page_renders_in_english_by_default(client):
    resp = client.get("/admin/stats")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Verification status" in html
    assert "Verify library now" in html
    assert "Extensions" in html
    assert "App types" in html


def test_stats_page_renders_in_spanish(client):
    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/stats")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Estado de verificación" in html
    assert "Verificar biblioteca ahora" in html
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
    resp = client.get("/admin/stats")
    html = resp.get_data(as_text=True)

    script_blocks = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(script_blocks) == 1, (
        f"Expected exactly one inline <script>...</script> block, found {len(script_blocks)}")
    body = script_blocks[0]
    assert "const I18N = {" in body
    assert "const STATS_QUERY" in body
    assert "function loadStats" in body
    assert "verifyNowBtn" in body


def test_verify_now_button_is_aligned_with_the_table_not_the_heading(client):
    """The button previously sat right after a hint span crammed next to the h4
    (ms-auto on the button, but competing for space with that span) - now the header
    row is a plain two-item flex (heading left, button right) and the hint moved below
    the table entirely."""
    resp = client.get("/admin/stats")
    html = resp.get_data(as_text=True)

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
    resp = client.get("/admin/stats")
    html = resp.get_data(as_text=True)

    assert "stat-section-head" in html

    css_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "style.css")
    with open(css_path) as f:
        css = f.read()
    assert ".stat-section-head" in css
    assert "max-width: 30rem" in css


def test_verification_modal_table_css_overrides_the_dashboard_width_cap():
    """Regression guard for the cramped-Title-column bug: the modal table reuses
    .stat-table's styling, but the small dashboard tables' max-width (30rem) once
    applied to it too, squeezing long titles into a near-unreadable single-word-per-line
    wrap. style.css must scope an override to the modal specifically."""
    css_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "style.css")
    with open(css_path) as f:
        css = f.read()

    assert "#verificationFilesModal .stat-table" in css
    assert "max-width: none" in css


def test_duplicate_files_ui_is_present_and_hidden_by_default(client):
    """The section only earns its place on the page while there's an actual duplicate
    to resolve - hidden via a class the JS toggles once loadDuplicateGroups() has an
    answer, not rendered server-side (the fixture has no seeded files here)."""
    resp = client.get("/admin/stats")
    html = resp.get_data(as_text=True)

    assert 'id="duplicatesSection"' in html
    assert "d-none" in html.split('id="duplicatesSection"')[0][-200:] or \
           "d-none" in html.split('id="duplicatesSection"')[1][:200]
    assert "Duplicate files" in html
    assert "const DUPLICATE_GROUPS_QUERY" in html
    assert "const RESOLVE_DUPLICATE_MUTATION" in html
    assert "const RESOLVE_BY_SIZE_MUTATION" in html
    assert 'id="resolveBySizeBtn"' in html
    assert "Resolve all by size" in html


def test_duplicate_files_ui_is_translated_in_spanish(client):
    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/stats")
    html = resp.get_data(as_text=True)

    assert "Archivos duplicados" in html
    assert "Conservar este" in html
    assert "Resolver todo por tamaño" in html  # static HTML, rendered as literal UTF-8
    # This one lives inside a JS string literal (I18N.duplicateKeepLargest), rendered
    # through |tojson - accented characters there appear \uXXXX-escaped in the raw
    # HTML, which a browser decodes normally at parse time (see the equivalent note
    # for the verification-status labels above).
    assert "Conservar el m\\u00e1s grande" in html


def test_stats_script_still_one_block_with_the_duplicates_ui_added(client):
    """Same regression class as the earlier script-split bug: this round added a
    second, much larger chunk of JS (loadDuplicateGroups, resolveDuplicate, the two
    card-building helpers) to the same script tag."""
    resp = client.get("/admin/stats")
    html = resp.get_data(as_text=True)

    script_blocks = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(script_blocks) == 1, (
        f"Expected exactly one inline <script>...</script> block, found {len(script_blocks)}")
    body = script_blocks[0]
    assert "function loadDuplicateGroups" in body
    assert "function resolveDuplicate" in body
    assert "function buildDuplicateGroupCard" in body
    assert "function loadStats" in body  # earlier content of the same block, untouched
    assert "resolveBySizeBtn" in body

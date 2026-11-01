"""Etapa 3: phone layout fixes for the admin pages. Checked as the CSS/markup that
produces them - the visual result was checked in a browser at 375px."""
import os
import re

import fixture
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _css():
    with open(os.path.join(ROOT, "app", "static", "style.css"), encoding="utf-8") as f:
        return f.read()


def _media_block(css, query):
    """The body of every `@media (<query>)` block, concatenated."""
    out = []
    for match in re.finditer(r"@media \(" + re.escape(query) + r"\) \{", css):
        depth, i = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append(css[match.end():i - 1])
    return "\n".join(out)


@pytest.fixture
def admin_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code == 302
    return shop_app.client


def test_files_tiles_are_two_compact_columns_on_phones():
    phone = _media_block(_css(), "max-width: 575.98px")
    assert re.search(r"\.files-tiles \{[^}]*grid-template-columns: repeat\(2,", phone)
    assert re.search(r"\.files-tile \{[^}]*min-height: 0", phone)


def test_task_details_wrap_under_the_name_on_phones():
    phone = _media_block(_css(), "max-width: 575.98px")
    assert re.search(r"\.task-head \{[^}]*flex-wrap: wrap", phone)
    assert re.search(r"\.task-head > \.task-meta \{[^}]*flex-basis: 100%", phone)


def test_admin_tabs_are_one_scrollable_row_on_phones():
    tablet = _media_block(_css(), "max-width: 767.98px")
    assert re.search(r"\.settings-sidebar \.nav \{[^}]*flex-wrap: nowrap[^}]*overflow-x: auto", tablet)


def test_admin_pages_scroll_the_active_tab_into_view(admin_client):
    for url in ("/admin", "/admin/files", "/admin/tasks", "/admin/stats", "/admin/settings"):
        assert "/static/js/admin-nav.js" in admin_client.get(url).get_data(as_text=True), url


def test_settings_fields_are_full_width_on_phones(admin_client):
    html = admin_client.get("/admin/settings").get_data(as_text=True)
    assert 'class="col-6"' not in html
    assert 'class="col-12 col-md-6"' in html

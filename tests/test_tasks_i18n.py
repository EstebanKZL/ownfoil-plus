"""Coverage for translating the Tasks page (app/templates/tasks.html) into the i18n
system: renders correctly in both languages, and a structural regression guard against
the inline <script> block being accidentally split (see test_stats_i18n.py for why
this specific guard exists - it caught a real bug while stats.html was being built).
"""
import re

import fixture
import pytest


@pytest.fixture
def client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def test_tasks_page_renders_in_english_by_default(client):
    resp = client.get("/admin/tasks")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Nothing queued." in html
    assert "Nothing scheduled." in html
    assert "No failures." in html
    assert "Workers" in html


def test_tasks_page_renders_in_spanish(client):
    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/tasks")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "No hay nada en cola." in html
    assert "No hay nada programado." in html
    assert "Sin fallos." in html
    assert "Procesos" in html


def test_the_inline_script_is_not_split_by_a_stray_closing_tag(client):
    """Same regression class as stats.html's equivalent test: the I18N object and the
    rest of the page's JS (mutations, render(), the realtime wiring) must live in one
    continuous <script> block."""
    resp = client.get("/admin/tasks")
    html = resp.get_data(as_text=True)

    script_blocks = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(script_blocks) == 1, (
        f"Expected exactly one inline <script>...</script> block, found {len(script_blocks)}")
    body = script_blocks[0]
    assert "const I18N = {" in body
    assert "const CANCEL_MUTATION" in body
    assert "function renderWorkers" in body
    assert "live.start()" in body
    assert "function loadHistory" in body
    assert "const HISTORY_QUERY" in body


def test_history_section_is_present_and_translated(client):
    resp = client.get("/admin/tasks")
    html = resp.get_data(as_text=True)
    assert 'id="historyList"' in html
    assert 'id="refreshHistory"' in html
    assert "History" in html
    assert "Nothing has finished yet." in html

    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/tasks")
    html = resp.get_data(as_text=True)
    assert "Historial" in html
    assert "Todav" in html  # "Todavía no terminó nada." - accent may render escaped

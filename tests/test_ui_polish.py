"""UI polish round 1: game cards that fill their row, a softer light theme that also
covers the game cards, task history clearing, and long lists capped to N visible rows
(Tasks history 5, dashboard 10, stats downloads 10)."""
import datetime
import os
import re

import fixture
import pytest

from db import DownloadEvent, TaskHistory, db

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _block(css, header):
    """Body of the rule/block starting with `header {`, braces balanced."""
    start = css.index(header + " {") + len(header) + 2
    depth, i = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        i += 1
    return css[start:i - 1]


@pytest.fixture
def admin_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code == 302
    return shop_app.client


# --- game cards ----------------------------------------------------------------------

def test_game_cards_are_no_longer_forced_dark():
    html = _read("app", "static", "js", "library.js")  # the cards are built there since stage 2
    assert "text-bg-dark game-card" not in html and "text-bg-dark list-game-card" not in html
    # Cards, Compact and List each build their cards on the theme-aware surface.
    assert html.count("card game-surface") == 3


# --- light theme -----------------------------------------------------------------------

def test_light_theme_is_soft_not_stark_white():
    # The palette moved to the design tokens (stage 1), Bootstrap reads it from there.
    css = _read("app", "static", "css", "tokens.css")
    light = _block(css, '[data-bs-theme="light"]')
    bg = re.search(r"--op-surface-0: (#[0-9a-f]{6})", light).group(1)
    assert bg.lower() not in ("#fff", "#ffffff")
    assert "--op-text:" in light and "--op-surface-1:" in light
    assert "--bs-body-bg: var(--op-surface-0)" in css


def test_light_theme_covers_the_game_cards():
    css = _read("app", "static", "style.css")
    for selector in ("[data-bs-theme=light] .game-surface",
                     "[data-bs-theme=light] .game-title", "[data-bs-theme=light] .list-card-body"):
        assert selector + " {" in css, selector


def test_game_cards_follow_the_design_tokens():
    # Stage 1 design system: the card colors come from the tokens, not literals. The
    # card gray is its own token (Switch Library Manager's card tone, on our tokens).
    rule = _block(_read("app", "static", "style.css"), ".game-surface")
    assert "var(--op-card)" in rule and "var(--op-text)" in rule


# --- task history ------------------------------------------------------------------------

def test_clear_task_history(admin_client):
    with admin_client.application.app_context():
        for n in range(3):
            db.session.add(TaskHistory(task_name="scan_library", summary=f"Scan {n}",
                                       completed_at=datetime.datetime.utcnow()))
        db.session.commit()
    assert admin_client.delete("/api/tasks/history").get_json() == {"success": True, "deleted": 3}
    with admin_client.application.app_context():
        assert TaskHistory.query.count() == 0


def test_clearing_history_is_admin_only(shop_app):
    shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    assert shop_app.client.delete("/api/tasks/history").status_code == 403


def test_tasks_page_caps_history_to_five_and_offers_clearing(admin_client):
    html = (admin_client.get("/admin/tasks").get_data(as_text=True)
            + admin_client.get("/static/js/tasks.js").get_data(as_text=True))  # JS moved in stage 5a
    assert 'id="clearHistory"' in html
    assert 'id="historyScroll" style="--task-rows: 5"' in html


# --- capped lists ----------------------------------------------------------------------------

def test_admin_pages_load_the_row_limiter(admin_client):
    for url in ("/admin", "/admin/tasks", "/admin/stats"):
        assert "/static/js/scroll-limit.js" in admin_client.get(url).get_data(as_text=True), url


def test_dashboard_lists_show_ten_and_return_up_to_fifty(admin_client):
    js = admin_client.get("/static/js/dashboard.js").get_data(as_text=True)  # since stage 4
    assert "limitVisibleRows(document.getElementById(id + 'Scroll'), 'li', 10)" in js
    for list_id in ("dashRecentDownloads", "dashRecentSaves", "dashRecentFiles"):
        assert f"renderCardList('{list_id}'" in js, list_id
    with admin_client.application.app_context():
        now = datetime.datetime.utcnow()
        for n in range(55):
            db.session.add(DownloadEvent(filename=f"g{n}.nsp", client="web",
                                         downloaded_at=now - datetime.timedelta(minutes=n)))
        db.session.commit()
    assert len(admin_client.get("/api/dashboard").get_json()["recent_downloads"]) == 50


def test_stats_download_tables_show_ten_and_the_short_ones_four(admin_client):
    html = admin_client.get("/admin/stats").get_data(as_text=True)
    for table in ("downloadTopTitles", "downloadByUser", "downloadByClient"):
        assert f'id="{table}Scroll"' in html, table
    js = admin_client.get("/static/js/stats.js").get_data(as_text=True)  # since stage 4
    assert "[['downloadTopTitles', 10], ['downloadByUser', 4], ['downloadByClient', 4]]" in js
    assert "limitVisibleRows(document.getElementById(id + 'Scroll'), 'li', rows)" in js


def test_stats_top_titles_go_beyond_ten(admin_client):
    with admin_client.application.app_context():
        now = datetime.datetime.utcnow()
        for n in range(15):
            db.session.add(DownloadEvent(filename="g.nsp", client="web", title_id=f"01000000000{n:02d}000",
                                         downloaded_at=now))
        db.session.commit()
    assert len(admin_client.get("/api/stats/downloads").get_json()["top_titles"]) == 15


def test_row_limiter_measures_rendered_rows():
    js = _read("app", "static", "js", "scroll-limit.js")
    assert "function limitVisibleRows(container, rowSelector, visible)" in js
    assert "getBoundingClientRect" in js and "ResizeObserver" in js


def test_card_lists_keep_their_frame_and_a_card_scrollbar():
    """Stats and Dashboard lists kept growing as rows arrived: the frame holds its rows'
    height empty too, and every list that scrolls in a card has the thin card scrollbar."""
    js = _read("app", "static", "js", "scroll-limit.js")
    assert "--row-pitch" in js and "dash-list__empty" in js and "container.style.height" in js
    css = _read("app", "static", "style.css")
    assert re.search(r"\.task-scroll,\s*\.rows-limited \{\s*scrollbar-width: thin;", css)
    assert re.search(r"\.dl-card \.dl-scroll \{[^}]*--row-pitch: [\d.]+rem;[^}]*padding-right", css)

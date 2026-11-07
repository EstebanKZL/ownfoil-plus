"""Stage 4 design: the Statistics (/admin/stats) and Dashboard (/admin) pages - JS in
static/js/stats.js and dashboard.js, chart helpers in charts.js, and the new sections."""
import json
import os
import re

import fixture
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _js(name):
    return _read("app", "static", "js", name)


def _function_body(js, name):
    start = re.search(rf"(async )?function {name}\(", js).start()
    depth, i = 0, js.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        i += 1
        if depth == 0:
            return js[start:i]


@pytest.fixture
def admin_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code in (302, 303)
    return shop_app.client


# --- the JS lives in static/js -----------------------------------------------------------

@pytest.mark.parametrize("url,script,moved", [
    ("/admin/stats", "stats.js", ("function loadStats", "function renderVerification", "function loadDownloads")),
    ("/admin", "dashboard.js", ("function renderTiles", "function renderStorage", "function renderAlerts")),
])
def test_page_logic_lives_in_its_own_script(admin_client, url, script, moved):
    html = admin_client.get(url).get_data(as_text=True)
    assert f"/static/js/{script}" in html
    inline = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(inline) == 1
    js = _js(script)
    for name in moved:
        assert name not in inline[0], name
        assert name in js, name


# --- chart helpers (static/js/charts.js) -------------------------------------------------

def test_chart_helpers_guard_empty_data():
    js = _js("charts.js")
    pct = _function_body(js, "percent")
    assert "!total" in pct or "total <= 0" in pct
    donut = _function_body(js, "donutGradient")
    # Nothing to draw (no segments, or all zero): one neutral ring, never NaN degrees.
    assert "var(--op-chart-track) 0deg 360deg" in donut
    assert "acc" in donut and "360" in donut
    ring = _function_body(js, "ringGradient")
    assert "conic-gradient(" in ring
    assert "const CHART_COLORS" in js and "var(--op-nav)" in js


@pytest.mark.parametrize("url", ["/admin/stats", "/admin"])
def test_pages_load_the_chart_helpers_first(admin_client, url):
    html = admin_client.get(url).get_data(as_text=True)
    own = "stats.js" if url.endswith("stats") else "dashboard.js"
    assert html.index("js/charts.js") < html.index(f"js/{own}")


# --- statistics page ---------------------------------------------------------------------

def _extract_query(js_source, const_name):
    m = re.search(rf"const {const_name} = `(.*?)`;", js_source, re.DOTALL)
    assert m, f"{const_name} not found"
    return m.group(1)


def test_stats_page_has_the_overview_sections(admin_client):
    html = admin_client.get("/admin/stats").get_data(as_text=True)
    assert 'class="page-head' in html
    for section in ("statsFormats", "statsLibraries", "statsVerification", "statsTypes", "statsLargest",
                    "downloadsSection"):
        assert re.search(rf'id="{section}"[^>]*>|class="[^"]*surface[^"]*"[^>]*id="{section}"', html), section
    for chart in ("formatDonut", "verificationRing", "largestFiles"):
        assert f'id="{chart}"' in html, chart


def test_main_tiles_are_four(admin_client):
    body = _function_body(_js("stats.js"), "tiles")
    assert body.count("I18N.") >= 4
    assert "unidentifiedFiles" in body and "ownedTitles" in body and "totalSize" in body


def test_charts_render_from_the_stats_query():
    js = _js("stats.js")
    assert "donutGradient(" in _function_body(js, "renderFormats")
    verification = _function_body(js, "renderVerification")
    assert "ringGradient(" in verification and "SIGNATURE_OK" in verification and "VALID" in verification
    assert "openVerificationFiles(" in verification
    assert "openLibraryDetail(" in _function_body(js, "renderLibraries")
    assert "openMissingAppType(" in _function_body(js, "renderTypes")
    for fn in ("renderFormats", "renderLibraries", "renderVerification", "renderTypes", "renderLargestFiles"):
        body = _function_body(js, fn)
        assert "innerHTML = `" not in body, fn   # paths and names go through textContent


def test_largest_files_query_runs_and_is_ordered(admin_client):
    query = _extract_query(_js("stats.js"), "LARGEST_FILES_QUERY")
    resp = admin_client.get("/api/graphql", query_string={"query": query})
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    sizes = [f["size"] for f in body["data"]["files"]["items"]]
    assert sizes == sorted(sizes, reverse=True)
    assert len(sizes) <= 10


def test_largest_files_link_to_their_game_when_known():
    body = _function_body(_js("stats.js"), "renderLargestFiles")
    assert "`/game/${" in body
    # An unidentified file (no title) is shown without a link.
    assert "titleId" in body and "if (" in body


def test_empty_sections_show_a_message():
    js = _js("stats.js")
    for fn in ("renderFormats", "renderLibraries", "renderVerification", "renderTypes", "renderLargestFiles"):
        assert "emptyRow(" in _function_body(js, fn) or "nothingToReport" in _function_body(js, fn), fn


def test_stats_strings_are_translated():
    import i18n
    for key in ("stats.subtitle_overview", "stats.space_by_format", "stats.space_by_library",
                "stats.verified_ok", "stats.content_by_type", "stats.largest_files", "stats.total"):
        assert {"en", "es"} <= set(i18n.TRANSLATIONS[key]), key


# --- dashboard ----------------------------------------------------------------------------

def test_storage_tone_thresholds():
    body = _function_body(_js("dashboard.js"), "storageTone")
    assert "15" in body and "5" in body
    assert "'danger'" in body and "'wait'" in body and "'ok'" in body


def test_alerts_are_toned_notices():
    body = _function_body(_js("dashboard.js"), "renderAlerts")
    assert "dash-notice" in body and "list-group-item-" not in body


def test_storage_handles_offline_and_unknown_totals():
    body = _function_body(_js("dashboard.js"), "renderStorage")
    assert "!s.online" in body and "!s.total" in body
    assert "percentBar(" in body and "storageTone(" in body


def test_recent_rows_link_to_the_game_and_icons_come_in_one_request():
    js = _js("dashboard.js")
    # The rows and the icon request are shared with Statistics since 6.2.5.49
    # (static/js/title-list.js; tests/test_admin_polish.py covers the single request).
    assert "titleListRow(" in _function_body(js, "renderCardList")
    shared = _js("title-list.js")
    assert "`/game/${titleId}`" in shared
    icons = _function_body(shared, "fillTitleIcons")
    assert icons.count("fetch(") == 1
    assert "[0-9A-F]{16}" in icons      # ids are validated before going into the query


def test_recent_downloads_carry_their_title_id(admin_client, shop_app):
    import datetime
    from db import DownloadEvent, db
    with shop_app.app.app_context():
        db.session.add(DownloadEvent(filename="g.nsp", client="web", title_id="0100000000010000",
                                     downloaded_at=datetime.datetime.utcnow()))
        db.session.commit()
    data = admin_client.get("/api/dashboard").get_json()
    assert data["recent_downloads"][0]["title_id"] == "0100000000010000"


def test_the_dashboard_has_no_status_chips(admin_client):
    # Each service's state is under Services; the dashboard keeps alerts and lists.
    assert "renderStatus" not in _js("dashboard.js")
    assert 'id="dashStatus"' not in admin_client.get("/admin").get_data(as_text=True)


def test_dashboard_strings_are_translated():
    import i18n
    for key in ("dash.storage_used",):
        assert {"en", "es"} <= set(i18n.TRANSLATIONS[key]), key


# --- found in the browser check ---------------------------------------------------------

def test_long_labels_wrap_and_the_verify_button_reaches_the_edge():
    """A long library path squeezed its "(6)" into a one-character column, and the old
    30rem cap on .stat-section-head (sized for the tables) left "Verify" mid-card."""
    css = _read("app", "static", "style.css")
    label = re.search(r"\.chart-row__label \{([^}]*)\}", css).group(1)
    assert "flex-wrap: wrap" in label
    assert re.search(r"\.stats-section \.stat-section-head \{[^}]*max-width: none", css)


def test_long_file_names_never_widen_the_phone_page():
    """Found at 375px: a largest-files row's file name (the secondary text) was set not to
    shrink and pushed the page to 465px wide."""
    css = _read("app", "static", "style.css")
    subs = " ".join(m.group(1) for m in re.finditer(r"\.chart-row__sub \{([^}]*)\}", css))
    assert "flex: 0 0 auto" not in subs
    assert "overflow-wrap: anywhere" in subs and "min-width: 0" in subs


def test_dashboard_columns_and_storage_rows_fit_a_phone():
    """Found at 375px: the recent lists' unbreakable lines grew their grid column to
    520px, and the storage figures left the library path 53px wide."""
    css = _read("app", "static", "style.css")
    assert re.search(r"\.stat-sections > \* \{[^}]*min-width: 0", css)
    assert re.search(r"\.dash-storage__head \{[^}]*flex-wrap: wrap", css)


# --- final review fixes --------------------------------------------------------------------

def test_unidentified_tile_opens_the_unidentified_tab():
    assert "'/admin/files#unidentified'" in _function_body(_js("stats.js"), "tiles")


def test_chart_tracks_show_on_light_cards():
    """The tracks used --op-surface-2, ~1:1 against a light card: empty charts vanished."""
    css = _read("app", "static", "style.css")
    charts = _js("charts.js")
    assert "--op-chart-track" in _read("app", "static", "css", "tokens.css")
    assert re.search(r"\.chart-bar \{[^}]*background-color: var\(--op-chart-track\)", css)
    assert "var(--op-chart-track)" in charts and "var(--op-surface-2)" not in charts


def test_clickable_chart_rows_keep_a_visible_focus():
    css = _read("app", "static", "style.css")
    # The rule of its own, not the one shared with :hover.
    rules = re.findall(r"(?m)^\.chart-row\.is-clickable:focus-visible \{([^}]*)\}", css)
    assert any("outline: 2px solid var(--op-nav)" in r for r in rules)

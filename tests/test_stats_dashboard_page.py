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
    ("/admin/stats", "stats.js", ("function loadStats", "function renderTable", "function loadDownloads")),
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
    assert "var(--op-surface-2) 0deg 360deg" in donut
    assert "acc" in donut and "360" in donut
    ring = _function_body(js, "ringGradient")
    assert "conic-gradient(" in ring
    assert "const CHART_COLORS" in js and "var(--op-nav)" in js


@pytest.mark.parametrize("url", ["/admin/stats", "/admin"])
def test_pages_load_the_chart_helpers_first(admin_client, url):
    html = admin_client.get(url).get_data(as_text=True)
    own = "stats.js" if url.endswith("stats") else "dashboard.js"
    assert html.index("js/charts.js") < html.index(f"js/{own}")

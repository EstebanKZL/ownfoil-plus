"""Stage 5a design: the Files, Tasks and Services admin pages - JS in static/js
(files.js, tasks.js), page headers and surfaces, Files tones and the game link, Tasks
state tones and worker cards."""
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


@pytest.mark.parametrize("url,script,moved", [
    ("/admin/files", "files.js", ("function fileRow", "function openDrawer", "function paintTiles")),
    ("/admin/tasks", "tasks.js", ("function scheduleRender", "function markDone")),
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


# --- headers and surfaces ------------------------------------------------------------------

@pytest.mark.parametrize("url", ["/admin/files", "/admin/tasks", "/admin/services"])
def test_admin_pages_have_the_page_head(admin_client, url):
    assert 'class="page-head' in admin_client.get(url).get_data(as_text=True)


def test_tasks_sections_are_surfaces(admin_client):
    html = admin_client.get("/admin/tasks").get_data(as_text=True)
    for section in ("tasksQueue", "tasksScheduled", "tasksFailed", "tasksHistory", "tasksWorkers"):
        assert re.search(rf'<section class="surface[^"]*" id="{section}"', html), section
    for kept in ("queueTasks", "scheduledTasks", "failedTasks", "historyList", "workerCards",
                 "purgeFailed", "refreshHistory", "clearHistory", "queueEmpty", "historyEmpty"):
        assert f'id="{kept}"' in html, kept


def test_services_section_is_a_surface(admin_client):
    html = admin_client.get("/admin/services").get_data(as_text=True)
    assert re.search(r'<section class="surface[^"]*" id="servicesDiscovery"', html)
    assert 'id="discoveryEnabledCheck"' in html and 'id="submitServicesSettingsBtn"' in html


# --- Files: tokens, tile tones, game link ---------------------------------------------------

def _css():
    return _read("app", "static", "style.css")


def test_files_palette_is_built_from_the_tokens():
    css = _css()
    blocks = re.findall(r"(?m)^(?:\[data-bs-theme=\w+\] )?\.files-page \{([^}]*)\}", css)
    assert blocks
    palette = "".join(blocks)
    assert "--files-success: var(--op-ok)" in palette and "--files-danger: var(--op-danger)" in palette
    assert not re.search(r"--files-[a-z-]+: #[0-9a-fA-F]{3,8}", palette)


def test_files_tiles_take_a_tone_per_state():
    css = _css()
    for key, token in (("unidentified", "--op-wait"), ("duplicates", "--op-wait"), ("outdated", "--op-wait"),
                       ("all", "--op-nav"), ("pending", "--op-nav"), ("verification", "--op-ok")):
        assert re.search(rf'\.files-tile\[data-tile="{key}"\] \{{[^}}]*var\({token}', css), key
    tile = re.search(r"(?m)^\.files-tile \{([^}]*)\}", css).group(1)
    assert "var(--op-radius-lg)" in tile and "#" not in tile


def test_identified_files_link_to_their_game_page():
    body = _function_body(_js("files.js"), "titleLink")
    assert "`/game/${titleId}`" in body and "/title/" not in body
    # Only identified files get the link: the drawer builds it from a title it found.
    assert "titles.length ? titleLink(" in _function_body(_js("files.js"), "renderDrawer")


# --- Tasks: state tones and worker cards ------------------------------------------------------

def test_task_states_have_their_tones():
    css = _css()
    assert re.search(r"\.task-progress \{[^}]*background-color: var\(--op-chart-track\)", css)
    assert re.search(r"\.task-progress \.progress-bar \{[^}]*background-color: var\(--op-nav\)", css)
    assert re.search(r"\.task-list--failed > \.task-row \{[^}]*var\(--op-danger", css)
    assert re.search(r"\.task-list--scheduled > \.task-row \{[^}]*var\(--op-wait", css)


def test_worker_cards_are_surfaces_with_a_status_dot():
    body = _function_body(_js("tasks.js"), "renderWorkers")
    assert "worker-card surface" in body
    for state in ("busy", "idle", "offline"):
        assert f"worker-dot--{state}" in body or f"'{state}'" in body, state
    # Task names and worker data go in as text, not HTML.
    assert "innerHTML = `" not in body
    css = _css()
    for state, token in (("busy", "--op-nav"), ("idle", "--op-ok"), ("offline", "--op-danger")):
        assert re.search(rf"\.worker-dot--{state} \{{[^}}]*var\({token}\)", css), state


# --- every element the moved JS looks up still exists --------------------------------------

@pytest.mark.parametrize("url,script", [("/admin/files", "files.js"), ("/admin/tasks", "tasks.js"),
                                        ("/admin/stats", "stats.js"), ("/admin", "dashboard.js")])
def test_every_id_the_script_queries_exists(admin_client, url, script):
    js = _js(script)
    queried = set(re.findall(r"getElementById\('([A-Za-z][\w-]*)'\)", js))
    queried |= set(re.findall(r"""\$\(['"]#([A-Za-z][\w-]*)['"]\)""", js))
    queried |= set(re.findall(r"""querySelector\(['"]#([A-Za-z][\w-]*)['"]\)""", js))
    html = admin_client.get(url).get_data(as_text=True)
    created = set(re.findall(r"""id[:=]\s*['"`]([A-Za-z][\w-]*)""", js))
    missing = sorted(i for i in queried if f'id="{i}"' not in html and i not in created)
    assert not missing, missing


def test_long_task_names_ellipsize_inside_the_narrower_columns():
    """Found in the browser: in the two-column layout a failed task's long error text
    scrolled the list sideways - the name couldn't shrink below its text."""
    css = _css()
    assert re.search(r"\.task-name \{[^}]*min-width: 0", css)
    assert re.search(r"\.task-head \{[^}]*min-width: 0", css)


def test_a_long_task_error_ellipsizes_and_keeps_the_full_text_in_a_tooltip():
    """The sideways scroll came from the meta line: a failed task's error message."""
    css = _css()
    assert re.search(r"\.task-meta \{[^}]*min-width: 0[^}]*text-overflow: ellipsis", css)
    js = _read("app", "static", "js", "tasks.js")
    assert "meta.title = meta.textContent" in js


# --- Final review fixes -----------------------------------------------------------------

def test_files_info_tone_is_its_own_token_not_the_style_accent():
    """Neon's accent is red: an info pill ("Signature ok") built from it read as an error."""
    tokens = _read("app", "static", "css", "tokens.css")
    assert len(re.findall(r"--op-info: #[0-9a-f]{6};", tokens)) == 2      # dark and light
    assert len(re.findall(r"--op-info-rgb: \d+, \d+, \d+;", tokens)) == 2
    css = _css()
    assert "--files-info: var(--op-info);" in css
    assert "--files-info-bg: rgba(var(--op-info-rgb), .12);" in css


def test_state_edges_only_paint_top_level_task_rows():
    """Sub-tasks nest inside a failed parent's row; they keep their own look."""
    css = _css()
    assert ".task-list--failed > .task-row" in css
    assert ".task-list--scheduled > .task-row" in css
    assert not re.search(r"\.task-list--(failed|scheduled) \.task-row", css)


def test_a_stopped_worker_is_shown_in_the_danger_color():
    css = _css()
    assert ".worker-dot--offline { background-color: var(--op-danger); }" in css
    assert re.search(r"\.worker-card__state--stopped \{[^}]*color: var\(--op-danger\)", css)
    js = _read("app", "static", "js", "tasks.js")
    assert "worker-card__state--stopped" in js


def test_a_tile_with_broken_files_glows_in_the_danger_color():
    """The Dashboard's "N corrupt" alert lands on the verification tile: it was green."""
    js = _read("app", "static", "js", "files.js")
    assert "tile.dataset.tone = alert ? tone : '';" in js
    css = _css()
    assert re.search(r'\.files-tile\[data-tone="danger"\] \{ --tile: var\(--op-danger\); --tile-rgb: var\(--op-danger-rgb\); \}', css)


# --- Settings (stage 5b) ----------------------------------------------------------------

def test_settings_js_lives_in_a_static_file(admin_client):
    html = admin_client.get("/admin/settings").get_data(as_text=True)
    inline = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(inline) == 1
    assert html.index('/static/js/settings.js') > html.index("<script>")
    assert "function scanLibrary" not in html
    assert "async function scanLibrary" in _js("settings.js")


def test_settings_js_has_no_jinja():
    js = _js("settings.js")
    assert "{{" not in js and "{%" not in js


def test_settings_server_values_are_data(admin_client):
    html = admin_client.get("/admin/settings").get_data(as_text=True)
    assert re.search(r'<script type="application/json" id="settingsLanguages">', html)
    assert "const ADMIN_ACCOUNT_CREATED =" in html
    assert "if (!ADMIN_ACCOUNT_CREATED)" in _js("settings.js")


def test_no_admin_yet_forces_the_new_user_access_boxes():
    js = _js("settings.js")
    block = js[js.index("if (!ADMIN_ACCOUNT_CREATED)"):]
    block = block[:block.index("}")]
    for box in ("checkboxNewUserAdminAccess", "checkboxNewUserShopAccess", "checkboxNewUserBackupAccess"):
        assert box in block, box

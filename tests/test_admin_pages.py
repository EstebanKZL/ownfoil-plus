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


def test_services_are_cards_and_discovery_is_explained_in_settings(admin_client):
    html = admin_client.get("/admin/services").get_data(as_text=True)
    # Discovery's switch is a card of the Services panel, saved as it's flipped; what
    # it does and the Docker/Windows note live in Settings > Server network.
    assert 'id="serviceSwitch-discovery"' in html and 'id="servicesPanel"' in html
    assert 'id="servicesDiscovery"' not in html
    settings = admin_client.get("/admin/settings").get_data(as_text=True)
    assert re.search(r'<section class="surface[^"]*" id="Network"', settings)
    assert 'id="discoverySwitch"' in settings


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
    # A color of its own per tile (asked for: they read the same before).
    for key, token in (("all", "--op-nav"), ("compress", "--op-action"), ("combine", "--op-fav"),
                       ("unidentified", "--op-wait"), ("verification", "--op-ok"), ("duplicates", "--op-info"),
                       ("outdated", "--op-firmware"), ("pending", "--op-dlc")):
        assert re.search(rf'\.files-tile\[data-tile="{key}"\] \{{[^}}]*var\({token}', css), key
    tile = re.search(r"(?m)^\.files-tile \{([^}]*)\}", css).group(1)
    assert "var(--op-radius-lg)" in tile and "#" not in tile


def test_files_content_column_chips_carry_the_type_colors():
    js = _js("files.js")
    # The Content column is built through contentChips (no plain-text line anymore);
    # chip(text, tone) wears the type's fixed color, from the files-chip--* rules.
    assert "contentChips(r)," in js and "line('files-row-content'" not in js
    assert "`files-chip files-chip--${tone}`" in js
    css = _css()
    for tone, token in (("base", "--op-base"), ("update", "--op-wait"),
                        ("dlc", "--op-dlc"), ("multi", "--op-fav")):
        assert re.search(rf"\.files-chip--{tone} \{{[^}}]*var\({token}", css), tone


def test_duplicates_tile_counts_each_file_once():
    # A multi-content file sits in several groups (the game's base, its update, each
    # DLC); deleting it frees its size a single time, like the bulk-delete path.
    body = _function_body(_js("files.js"), "loadStats")
    assert "const doomed = new Map();" in body and "doomed.set(String(f.id)" in body


def test_files_header_synchronizes_like_switch_library_manager():
    html = _read("app/templates/files.html")
    # A labeled button, not the old icon that only re-read the DB: it downloads the
    # latest TitleDB and analyzes the library again, spinning while it runs.
    assert 'id="syncFiles"' in html and "files.sync_title" in html
    assert 'id="refreshFiles"' not in html
    js = _js("files.js")
    assert "mutation { syncLibrary { id status } }" in js and "addClass('spin')" in js


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
                                        ("/admin/stats", "stats.js"), ("/admin", "dashboard.js"),
                                        ("/admin/settings", "settings.js")])
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


SETTINGS_IDS = ["Authentication", "Registration", "Library", "Titles", "Media", "Shop", "Network", "Scheduler", "Maintenance",
                "Vault", "Notifications", "Workers", "Appearance", "Backup", "Danger"]


def test_settings_has_a_page_head(admin_client):
    html = admin_client.get("/admin/settings").get_data(as_text=True)
    head = re.search(r'<header class="page-head">(.*?)</header>', html, re.S)
    assert head and "bi-gear" in head.group(1) and "page-head__title" in head.group(1)


def test_settings_sections_are_cards_in_order(admin_client):
    html = admin_client.get("/admin/settings").get_data(as_text=True)
    ids = re.findall(r'<section class="surface admin-section settings-section[^"]*" id="(\w+)"', html)
    assert ids == SETTINGS_IDS


def test_settings_has_no_hr_separators(admin_client):
    assert "hr-settings" not in admin_client.get("/admin/settings").get_data(as_text=True)


def test_danger_zone_is_marked(admin_client):
    html = admin_client.get("/admin/settings").get_data(as_text=True)
    assert re.search(r'<section class="[^"]*settings-section--danger[^"]*" id="Danger"', html)
    assert re.search(r"\.settings-section--danger \{[^}]*var\(--op-danger\)", _css())


def test_links_into_settings_still_land(admin_client):
    html = admin_client.get("/admin/settings").get_data(as_text=True)
    targets = set()
    for folder in (("app", "templates"), ("app", "static", "js")):
        path = os.path.join(ROOT, *folder)
        for name in os.listdir(path):
            if name.endswith((".html", ".js")):
                targets |= set(re.findall(r"/admin/settings#([A-Za-z]\w*)", _read(*folder, name)))
    assert targets >= {"Authentication", "Library", "Maintenance"}
    missing = sorted(t for t in targets if f'id="{t}"' not in html)
    assert not missing, missing


SETTINGS_ICONS = ["bi-people", "bi-person-plus", "bi-folder", "bi-translate", "bi-image", "bi-shop", "bi-hdd-network", "bi-clock", "bi-archive",
                  "bi-safe", "bi-bell", "bi-cpu", "bi-palette", "bi-box-arrow-down", "bi-exclamation-triangle"]


def test_settings_index_lists_every_section(admin_client):
    html = admin_client.get("/admin/settings").get_data(as_text=True)
    nav = re.search(r'<nav class="settings-index" id="settingsIndex" aria-label="([^"]+)">(.*?)</nav>', html, re.S)
    assert nav and nav.group(1) == "On this page"
    links = re.findall(r'<a class="settings-index__link" href="#(\w+)" data-section="(\w+)">\s*<i class="bi ([\w-]+)"',
                       nav.group(2))
    assert [l[0] for l in links] == SETTINGS_IDS
    assert all(href == section for href, section, _ in links)
    assert [l[2] for l in links] == SETTINGS_ICONS
    # The index sits beside the sections, both inside the layout.
    assert html.index('class="settings-layout"') < html.index('id="settingsIndex"') < html.index('class="settings-sections"')


def test_settings_index_is_sticky_and_becomes_chips():
    css = _css()
    assert re.search(r"(?m)^\.settings-index \{[^}]*position: sticky", css)
    phone = re.search(r"@media \(max-width: 991\.98px\) \{(.*?)\n\}", css, re.S)
    phone_blocks = [b for b in re.findall(r"@media \(max-width: 991\.98px\) \{(.*?)\n\}", css, re.S)
                    if ".settings-index" in b]
    assert phone_blocks and "overflow-x: auto" in phone_blocks[0]
    assert re.search(r"@media \(min-width: 992px\) \{\s*\.settings-layout \{[^}]*display: grid", css)


def test_anchor_targets_clear_the_sticky_bars():
    css = _css()
    assert re.search(r"\.settings-section,\s*\.settings-section \[id\] \{[^}]*scroll-margin-top", css)


def test_index_click_scrolls_and_replaces_the_hash():
    body = _function_body(_js("settings.js"), "initSettingsIndex")
    assert "history.replaceState" in body
    assert "scrollIntoView" in body
    assert "prefers-reduced-motion" in body
    assert "'smooth'" in body and "'auto'" in body


def test_scrollspy_is_guarded():
    body = _function_body(_js("settings.js"), "initSettingsIndex")
    assert "'IntersectionObserver' in window" in body
    assert body.index("'IntersectionObserver' in window") < body.index("new IntersectionObserver")


def test_arriving_hash_marks_its_section():
    body = _function_body(_js("settings.js"), "initSettingsIndex")
    assert "location.hash" in body
    assert ".closest('.settings-section')" in body


def test_active_chip_scrolls_its_row_not_the_page():
    body = _function_body(_js("settings.js"), "setActiveSection")
    assert "aria-current" in body and "'active'" in body
    assert "scrollIntoView" not in body
    assert ".scrollTo(" in body


def test_settings_index_starts_on_ready():
    assert re.search(r"\$\(\s*initSettingsIndex\s*\)|DOMContentLoaded', initSettingsIndex", _js("settings.js"))


def test_the_bottom_of_the_page_marks_the_last_section_in_both_paths():
    """Found in the browser: the observer fired after the scroll handler and put an
    earlier section back. Both decide with the same atIndexBottom() check."""
    body = _function_body(_js("settings.js"), "initSettingsIndex")
    observer = body[body.index("new IntersectionObserver"):body.index("observer.observe")]
    assert "atIndexBottom()" in observer
    assert "function atIndexBottom" in _js("settings.js")


def test_a_linked_control_keeps_its_label_in_view():
    """Found in the browser: #shopHostInput landed under the chips with its label hidden."""
    css = _css()
    assert re.search(r"(?m)^\.settings-section \[id\] \{[^}]*scroll-margin-top: calc\(var\(--settings-top\) \+ 3rem\)", css)
    assert re.search(r"(?m)^    \.settings-section \[id\] \{[^}]*scroll-margin-top: calc\(var\(--settings-top\) \+ 6rem\)", css)


# --- Stage 5b final review fixes ----------------------------------------------------------

def test_danger_title_icon_is_red_too():
    """The 5a rule colors every section title's icon with the style accent."""
    assert re.search(r"\.settings-section--danger \.admin-section__title \.bi \{[^}]*color: var\(--op-danger\)", _css())


def test_settings_is_one_entry_of_the_search_palette():
    """Asked for: Settings once in Ctrl+K, not one entry per section (its words still
    find it)."""
    nav = _read("app", "templates", "nav.html")
    assert "'/admin/settings', 'bi-gear'" in nav
    assert "'/admin/settings#" not in nav


def test_index_click_moves_keyboard_focus_into_the_section(admin_client):
    html = admin_client.get("/admin/settings").get_data(as_text=True)
    assert len(re.findall(r'<section class="surface admin-section settings-section[^"]*" id="\w+" tabindex="-1"', html)) == len(SETTINGS_IDS)
    body = _function_body(_js("settings.js"), "initSettingsIndex")
    assert "target.focus({preventScroll: true})" in body


def test_phone_chips_sit_right_under_the_top_bar():
    """The top bar measures 57px; 4.25rem left an 11px gap content showed through."""
    assert re.search(r"\.settings-page \{\s*--settings-top: 3\.5625rem;", _css())


def test_files_tiles_are_the_library_tiles_in_the_asked_order(admin_client):
    """The Library's stat tiles (icon, count, label, note), the one in use outlined in its own
    color with a check; every file first, then the unidentified ones, then packing."""
    html = admin_client.get("/admin/files").get_data(as_text=True)
    order = re.findall(r'<a class="stat-tile files-tile" href="#(\w+)"', html)
    assert order == ["all", "unidentified", "compress", "combine", "verification", "duplicates",
                     "outdated", "pending"]
    assert html.count('class="stat-tile__icon"') >= 8
    assert "tile.classList.toggle('is-active', key === current);" in _js("files.js")

"""Admin pages polish, from screenshots of a real library: spacing under section titles,
"Clean DB" on a file, the Tasks layout, and the Statistics lists."""
import os
import re

import fixture
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _css():
    return _read("app", "static", "style.css")


def _js(name):
    return _read("app", "static", "js", name)


@pytest.fixture
def admin_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code == 302
    return shop_app.client


# --- 1.1 spacing -----------------------------------------------------------------------

def test_section_titles_keep_their_space_below():
    """A global `h1..h6 { margin: 0 !important }` swallowed every section title's own
    margin: the content sat right under the title."""
    css = _css()
    rule = re.search(r"\.admin-section__title:not\(\.mb-0\),\s*\.stats-section__title:not\(\.mb-0\)[^{]*\{([^}]*)\}", css)
    assert rule and re.search(r"margin-bottom: [.\d]+rem !important", rule.group(1))


def test_worker_cards_do_not_climb_under_their_title():
    """`.row.g-3` pulls itself up by its gutter, onto the Processes title."""
    assert re.search(r"#workerCards \{[^}]*margin-top: 0", _css())


def test_stats_hints_sit_apart_from_the_rows_above(admin_client):
    html = admin_client.get("/admin/stats").get_data(as_text=True)
    assert html.count('class="stats-hint') >= 2
    assert re.search(r"\.stats-hint \{[^}]*margin-top: [.\d]+rem", _css())


# --- 1.2 Clean DB in the Files drawer ----------------------------------------------------

def test_files_drawer_offers_clean_db_before_delete():
    js = _js("files.js")
    actions = js[js.index("const ACTIONS = {"):js.index("};", js.index("const ACTIONS = {"))]
    assert "cleanDb:" in actions
    assert actions.index("cleanDb:") < actions.index("delete:")
    assert "cleanFileRecord(fileId: $id)" in js
    assert "I18N.actionCleanDbTitle" in actions and "I18N.confirmCleanDbTemplate" in js


def test_clean_db_strings_exist_in_both_languages():
    import i18n
    for key in ("files.action_clean_db_title", "files.confirm_clean_db"):
        assert i18n.TRANSLATIONS[key]["en"] and i18n.TRANSLATIONS[key]["es"], key


# --- 1.3 Tasks layout ---------------------------------------------------------------------

def test_tasks_sections_read_queue_failed_then_scheduled_history(admin_client):
    """Two columns: Queue | Failed on top, Scheduled | History below, Processes last."""
    html = admin_client.get("/admin/tasks").get_data(as_text=True)
    ids = re.findall(r'<section class="surface admin-section[^"]*" id="(tasks\w+)"', html)
    assert ids == ["tasksQueue", "tasksFailed", "tasksScheduled", "tasksHistory", "tasksWorkers"]
    for scroll in ("queueScroll", "failedScroll", "scheduledScroll", "historyScroll"):
        assert f'id="{scroll}"' in html, scroll


def test_tasks_lists_keep_a_fixed_frame_of_ten_or_five_rows(admin_client):
    """The cards grew and shrank as rows came and went: each list has a frame of a fixed
    height now (10 rows for Queue and Failed, 5 for Scheduled and History), and scrolls."""
    html = admin_client.get("/admin/tasks").get_data(as_text=True)
    for scroll, n in (("queueScroll", 10), ("failedScroll", 10), ("scheduledScroll", 5), ("historyScroll", 5)):
        assert f'class="task-scroll" id="{scroll}" style="--task-rows: {n}"' in html, scroll
    task_scroll = re.search(r"(?m)^\.task-scroll \{([^}]*)\}", _css()).group(1)
    assert "height: calc(var(--task-rows, 5) * var(--task-row-h))" in task_scroll
    assert re.search(r"\.task-scroll,\s*\.rows-limited \{\s*scrollbar-width: thin;", _css())
    # The whole queue, no "N oldest" note.
    assert 'queueTruncated' not in html and 'MAX_TASKS' not in _js("tasks.js")


# --- 1.4 Statistics lists: the Dashboard's rows, with each game's icon ---------------------

def _function_body(js, name):
    start = re.search(rf"(async )?function {name}\(", js).start()
    depth, i = 0, js.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        if depth == 0:
            return js[start:i + 1]
        i += 1


def test_title_rows_and_icons_are_shared_by_dashboard_and_stats(admin_client):
    shared = _js("title-list.js")
    assert "function titleListRow(" in shared and "function fillTitleIcons(" in shared
    icons = _function_body(shared, "fillTitleIcons")
    assert icons.count("fetch(") == 1              # one request for every icon on screen
    assert "[0-9A-F]{16}" in icons                 # ids validated before going into the query
    for page, script in (("/admin", "dashboard.js"), ("/admin/stats", "stats.js")):
        html = admin_client.get(page).get_data(as_text=True)
        assert html.index("/static/js/title-list.js") < html.index(f"/static/js/{script}"), page
    dash = _js("dashboard.js")
    assert "function loadIcons" not in dash and "fillTitleIcons(" in dash and "titleListRow(" in dash


def test_stats_lists_are_rows_not_tables(admin_client):
    html = admin_client.get("/admin/stats").get_data(as_text=True)
    for list_id in ("verificationFilesList", "missingAppTypeList", "downloadTopTitles",
                    "downloadByUser", "downloadByClient"):
        assert re.search(rf'<ul class="dash-list[^"]*" id="{list_id}"', html), list_id
    assert "<table" not in html


def test_stats_lists_carry_the_game_icon():
    js = _js("stats.js")
    assert re.search(r"title \{[^}]*iconUrl", js[js.index("const FILES_BY_STATUS_QUERY"):])
    missing = js[js.index("const MISSING_APP_TYPE_QUERY"):js.index("`;", js.index("const MISSING_APP_TYPE_QUERY"))]
    assert "titleId" in missing and "iconUrl" in missing
    library = js[js.index("const LIBRARY_DETAIL_QUERY"):js.index("`;", js.index("const LIBRARY_DETAIL_QUERY"))]
    assert "iconUrl" in library
    card = _function_body(js, "buildLibraryDetailTitleCard")
    assert "dash-list__icon" in card and "text-bg-dark" not in card
    downloads = _function_body(js, "renderDownloads")
    assert "dlList(" in downloads and "fillTitleIcons(" in downloads
    assert "titleListRow(" in _function_body(js, "dlList")
    assert "limitVisibleRows(document.getElementById(id + 'Scroll'), 'li', rows)" in downloads


def test_a_long_error_never_squeezes_the_task_name_away():
    """Seen in the browser: a failed task's long error took the row and cut its name
    down to "U…". The name keeps its width (up to 60% of the row); the error shrinks."""
    css = _css()
    name = re.search(r"(?m)^\.task-name \{([^}]*)\}", css).group(1)
    assert "flex: 0 0 auto" in name and "max-width: 60%" in name
    meta = re.search(r"(?m)^\.task-meta \{([^}]*)\}", css).group(1)
    assert "flex: 1 1 auto" in meta and "min-width: 0" in meta

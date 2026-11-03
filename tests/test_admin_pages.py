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

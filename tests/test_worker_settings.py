"""POST /api/settings/worker: the admin-only route behind the Settings page's
"Workers" section. The backend (worker pool scaling on settings change, the
per-task-group concurrency cap `tasks.blocked_task_names` enforces) already existed
and is covered by tests/test_compression.py's `test_blocked_task_names` and
`test_claim_task_respects_group_cap` - this file covers the one thing that wasn't
wired up yet: `group_limits.net` (the "Max concurrent network tasks" control,
alongside the pre-existing `group_limits.io` one) end to end, from the route's
validation through to the real Settings page template and its i18n strings.
"""
import fixture
import pytest

from constants import DEFAULT_SETTINGS
from settings import get_settings


@pytest.fixture
def client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


@pytest.fixture
def shopper_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def test_default_settings_declare_both_concurrency_groups():
    """`net` sits alongside `io` in the shipped defaults now - both are groups a real
    task is registered under (tasks.TASK_GROUPS), so both need a limit out of the box
    for `tasks.blocked_task_names` to ever actually cap them."""
    assert DEFAULT_SETTINGS["worker"]["group_limits"] == {"io": 1, "net": 1}


def test_setting_net_limit_persists_and_preserves_io(client):
    resp = client.post("/api/settings/worker", json={"group_limits": {"net": 3}})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True

    worker = get_settings()["worker"]
    assert worker["group_limits"]["net"] == 3
    assert worker["group_limits"]["io"] == 1  # untouched, not reset to a default


def test_setting_io_and_net_together(client):
    resp = client.post("/api/settings/worker", json={
        "count": 4, "group_limits": {"io": 2, "net": 5}})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    worker = get_settings()["worker"]
    assert worker["count"] == 4
    assert worker["group_limits"] == {"io": 2, "net": 5}


@pytest.mark.parametrize("value", ["abc", 0, -1])
def test_net_limit_rejects_non_positive_or_non_numeric(client, value):
    resp = client.post("/api/settings/worker", json={"group_limits": {"net": value}})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is False
    assert len(body["errors"]) == 1
    assert body["errors"][0]["path"] == "worker/group_limits/net"
    assert body["errors"][0]["error"]  # non-empty message

    # The rejected field's own default is untouched.
    assert get_settings()["worker"]["group_limits"]["net"] == 1


def test_io_limit_still_validated_the_same_way_net_now_is(client):
    """Guards against a regression where generalizing the route to loop over every
    group silently dropped io's own validation - same per-field path shape as net."""
    resp = client.post("/api/settings/worker", json={"group_limits": {"io": 0}})
    body = resp.get_json()
    assert body["success"] is False
    assert body["errors"][0]["path"] == "worker/group_limits/io"


def test_an_unrelated_group_key_is_ignored_not_rejected(client):
    """Only keys DEFAULT_SETTINGS['worker']['group_limits'] actually declares are
    validated/stored - a client sending an unknown group name doesn't error, it's
    just dropped, the same way a brand new group added later would need its own
    DEFAULT_SETTINGS entry before this route does anything with it."""
    resp = client.post("/api/settings/worker", json={"group_limits": {"made_up_group": 9}})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert "made_up_group" not in get_settings()["worker"]["group_limits"]


def test_worker_settings_route_requires_admin(shopper_client):
    resp = shopper_client.post("/api/settings/worker", json={"group_limits": {"net": 2}})
    assert resp.status_code in (401, 403)


# --- UI wiring on the Settings page ------------------------------------------------

@pytest.fixture
def settings_page_client(client):
    """/admin/settings additionally reads TITLEDB_DIR/languages.json, which the
    shop_app fixture's bare titledb dir doesn't seed - not something this feature
    touches, just a pre-existing dependency of that one route (see the identical
    fixture in tests/test_settings_backup.py)."""
    import json
    import os
    from constants import TITLEDB_DIR
    os.makedirs(TITLEDB_DIR, exist_ok=True)
    with open(os.path.join(TITLEDB_DIR, "languages.json"), "w") as f:
        json.dump({"US": ["en"]}, f)
    return client


def test_settings_page_has_the_net_limit_control(settings_page_client):
    resp = settings_page_client.get("/admin/settings")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert 'id="netLimitInput"' in html
    assert 'id="ioLimitInput"' in html  # pre-existing control, still there alongside it
    assert "Max concurrent network tasks" in html
    assert "Max concurrent I/O tasks" in html


def test_settings_page_loads_net_limit_from_saved_settings(settings_page_client):
    settings_page_client.post("/api/settings/worker", json={"group_limits": {"net": 7}})
    resp = settings_page_client.get("/admin/settings")
    html = resp.get_data(as_text=True)

    assert "workerSettings['group_limits']['net']" in html


def test_net_limit_i18n_keys_exist_in_both_locales():
    from i18n import TRANSLATIONS
    for key in ("workers.net_limit_label", "workers.net_limit_help"):
        assert key in TRANSLATIONS
        assert TRANSLATIONS[key].get("en")
        assert TRANSLATIONS[key].get("es")

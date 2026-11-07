"""Phase 4, part B: Services (/admin/services) as one control panel - each service's
state and a switch for it - and the Store switch, which closes the shop to consoles."""
import base64
import re

import fixture
import pytest

from settings import get_settings

SERVICES = ("registration", "shop", "public_shop", "watcher", "maintenance", "notifications", "vault",
            "discovery")


def _login(shop_app, user):
    resp = shop_app.client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    assert resp.status_code == 302
    return shop_app.client


def _basic(user="shopper"):
    token = base64.b64encode(f"{user}:{fixture.PASSWORDS[user]}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_the_panel_lists_every_service_with_its_state(shop_app):
    admin = _login(shop_app, "admin")
    data = admin.get("/api/services").get_json()
    assert [s["id"] for s in data["services"]] == list(SERVICES)
    states = {s["id"]: s["enabled"] for s in data["services"]}
    assert states["shop"] is True and states["vault"] is False and states["registration"] is False
    # Each one links to where it's set up.
    assert all(s["settings"].startswith("/admin/") for s in data["services"])


@pytest.mark.parametrize("service,path", [
    ("registration", ("registration", "enabled")), ("shop", ("shop", "enabled")),
    ("maintenance", ("maintenance", "enabled")), ("notifications", ("notifications", "enabled")),
    ("vault", ("vault", "enabled")), ("discovery", ("services", "discovery", "enabled")),
    ("public_shop", ("shop", "public")), ("watcher", ("library", "watcher", "enabled"))])
def test_a_switch_turns_its_service_on_and_off(shop_app, service, path):
    admin = _login(shop_app, "admin")

    def stored():
        value = get_settings()
        for key in path:
            value = value[key]
        return value

    before = stored()
    resp = admin.post(f"/api/services/{service}", json={"enabled": not before})
    assert resp.status_code == 200 and resp.get_json()["enabled"] is (not before)
    assert stored() is (not before)
    admin.post(f"/api/services/{service}", json={"enabled": before})
    assert stored() is before


def test_unknown_services_and_non_admins_are_refused(shop_app):
    admin = _login(shop_app, "admin")
    assert admin.post("/api/services/nope", json={"enabled": True}).status_code == 404
    admin.get("/logout")
    shopper = _login(shop_app, "shopper")
    assert shopper.get("/api/services").status_code in (302, 401, 403)
    assert shopper.post("/api/services/shop", json={"enabled": False}).status_code in (302, 401, 403)


def test_the_page_draws_the_panel(shop_app):
    html = _login(shop_app, "admin").get("/admin/services").get_data(as_text=True)
    assert 'id="servicesPanel"' in html and "/static/js/services.js" in html
    assert len(re.findall(r"<script>(.*?)</script>", html, re.S)) == 1
    for name in ("serviceOn:", "serviceOff:", "serviceSettings:"):
        assert name in html, name


# --- the Store switch -------------------------------------------------------------------------

def test_a_closed_shop_turns_consoles_away(shop_app):
    admin = _login(shop_app, "admin")
    admin.post("/api/services/shop", json={"enabled": False})
    admin.get("/logout")
    client = shop_app.client
    sphaira = {"User-Agent": "sphaira/0.9", **_basic()}
    assert client.open("/", method="OPTIONS", headers=sphaira).status_code == 503
    # The shop listing answers in the client's own format, which it shows on screen.
    assert "closed" in client.get("/", headers=sphaira).get_data(as_text=True)
    assert client.post("/api/graphql", json={"query": "{ __typename }"}, headers=_basic()).status_code == 503
    assert client.get("/api/get_game/1", headers=_basic()).status_code == 503


def test_a_closed_shop_still_shows_the_web_library(shop_app):
    admin = _login(shop_app, "admin")
    admin.post("/api/services/shop", json={"enabled": False})
    admin.get("/logout")
    client = _login(shop_app, "shopper")
    assert client.get("/").status_code == 200
    resp = client.post("/api/graphql", json={"query": "{ __typename }"})
    assert resp.status_code == 200


def test_an_open_shop_answers_consoles_as_before(shop_app):
    resp = shop_app.client.open("/", method="OPTIONS", headers={"User-Agent": "sphaira/0.9", **_basic()})
    assert resp.status_code == 200 and resp.get_json()["features"]["shop"] is True

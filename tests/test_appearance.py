"""Stage 1 design system: the admin's default color style (appearance.default_style)."""
import fixture
import pytest


def _login(client, user):
    resp = client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    assert resp.status_code == 302


@pytest.fixture
def admin_client(shop_app):
    _login(shop_app.client, "admin")
    return shop_app.client


@pytest.fixture
def shopper_client(shop_app):
    _login(shop_app.client, "shopper")
    return shop_app.client


def test_default_style_is_joycon(shop_app):
    import settings
    assert settings.get_default_style() == "joycon"


def test_invalid_default_style_falls_back_to_joycon(shop_app, monkeypatch):
    import settings
    monkeypatch.setitem(settings.get_settings(), "appearance", {"default_style": "pink"})
    assert settings.get_default_style() == "joycon"


def test_missing_appearance_section_falls_back(shop_app, monkeypatch):
    import settings
    monkeypatch.delitem(settings.get_settings(), "appearance", raising=False)
    assert settings.get_default_style() == "joycon"


@pytest.mark.parametrize("style", ["ownfoil", "neon", "joycon"])
def test_admin_sets_style_and_pages_render_it(shop_app, admin_client, style):
    resp = admin_client.post("/api/settings/appearance", json={"default_style": style})
    assert resp.get_json()["success"] is True
    for url in ("/", "/admin", "/offline"):
        assert f'data-style="{style}"' in admin_client.get(url).get_data(as_text=True), url
    # The login page is for visitors who are not signed in yet.
    anonymous = shop_app.app.test_client()
    assert f'data-style="{style}"' in anonymous.get("/login").get_data(as_text=True)


def test_unknown_style_is_rejected(admin_client):
    body = admin_client.post("/api/settings/appearance", json={"default_style": "pink"}).get_json()
    assert body["success"] is False and body["errors"][0]["path"] == "appearance/default_style"


def test_shopper_cannot_change_style(shopper_client):
    resp = shopper_client.post("/api/settings/appearance", json={"default_style": "neon"})
    assert resp.status_code in (302, 401, 403)


def test_appearance_section_and_search_entry(admin_client):
    html = admin_client.get("/admin/settings").get_data(as_text=True)
    assert 'id="Appearance"' in html
    assert "apariencia" in admin_client.get("/").get_data(as_text=True)   # Ctrl+K finds Settings by it

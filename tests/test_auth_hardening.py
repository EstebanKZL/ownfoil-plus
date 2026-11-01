"""Stage 0 security hardening: a per-install secret key instead of the one that used
to be hard-coded (and public), no open redirect through the login's `next`, a web
login brute-force guard, user editing, and no way to remove the last admin.
"""
import os

import fixture
import pytest
import yaml

from auth import LOGIN_MAX_FAILURES, safe_next_url


def _login(client, user, password, **extra):
    return client.post("/login", data={"user": user, "password": password, **extra},
                       follow_redirects=False)


@pytest.fixture
def admin_client(shop_app):
    resp = _login(shop_app.client, "admin", fixture.PASSWORDS["admin"])
    assert resp.status_code in (302, 303)
    return shop_app.client


def _user_id(client, name):
    return next(u["id"] for u in client.get("/api/users").get_json() if u["user"] == name)


# --- secret key ------------------------------------------------------------------

def test_secret_key_is_not_the_old_public_constant(shop_app):
    key = shop_app.app.config["SECRET_KEY"]
    assert key and key != "8accb915665f11dfa15c2db1a4e8026905f57716"


def test_secret_key_is_generated_once_and_reused(tmp_path, monkeypatch):
    import app as app_mod
    monkeypatch.delenv("OWNFOIL_SECRET_KEY", raising=False)
    monkeypatch.setattr(app_mod, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(app_mod, "SECRET_KEY_FILE", str(tmp_path / ".secret_key"))

    first = app_mod.load_or_create_secret_key()
    second = app_mod.load_or_create_secret_key()

    assert first == second
    assert len(first) >= 64
    assert (tmp_path / ".secret_key").read_text().strip() == first


def test_secret_key_env_var_wins(tmp_path, monkeypatch):
    import app as app_mod
    monkeypatch.setenv("OWNFOIL_SECRET_KEY", "from-the-environment")
    monkeypatch.setattr(app_mod, "SECRET_KEY_FILE", str(tmp_path / ".secret_key"))

    assert app_mod.load_or_create_secret_key() == "from-the-environment"
    assert not os.path.exists(tmp_path / ".secret_key")


def test_session_cookies_are_samesite_lax(shop_app):
    assert shop_app.app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert shop_app.app.config["REMEMBER_COOKIE_SAMESITE"] == "Lax"


# --- next / open redirect ----------------------------------------------------------

@pytest.mark.parametrize("value", [
    "https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "", None,
])
def test_safe_next_url_rejects_offsite_targets(value):
    assert safe_next_url(value) == "/"


@pytest.mark.parametrize("value", ["/admin/settings", "/admin/files?q=zelda"])
def test_safe_next_url_keeps_local_paths(value):
    assert safe_next_url(value) == value


def test_login_does_not_redirect_offsite(shop_app):
    resp = _login(shop_app.client, "admin", fixture.PASSWORDS["admin"], next="https://evil.example/")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_login_redirects_to_local_next(shop_app):
    resp = _login(shop_app.client, "admin", fixture.PASSWORDS["admin"], next="/admin/settings")
    assert resp.headers["Location"] == "/admin/settings"


def test_login_page_carries_next_into_the_form(shop_app):
    html = shop_app.client.get("/login?next=/admin/files").get_data(as_text=True)
    assert 'name="next" value="/admin/files"' in html


# --- brute-force guard -------------------------------------------------------------

def test_wrong_password_shows_an_error(shop_app):
    resp = _login(shop_app.client, "admin", "nope")
    assert resp.status_code == 401
    assert "alert-danger" in resp.get_data(as_text=True)


def test_login_locks_after_repeated_failures(shop_app):
    for _ in range(LOGIN_MAX_FAILURES):
        assert _login(shop_app.client, "admin", "nope").status_code == 401

    # Even the right password is refused while locked.
    assert _login(shop_app.client, "admin", fixture.PASSWORDS["admin"]).status_code == 429
    # Another username from the same address is unaffected.
    assert _login(shop_app.client, "shopper", fixture.PASSWORDS["shopper"]).status_code == 302


def test_successful_login_resets_the_failure_count(shop_app):
    for _ in range(LOGIN_MAX_FAILURES - 1):
        _login(shop_app.client, "admin", "nope")
    assert _login(shop_app.client, "admin", fixture.PASSWORDS["admin"]).status_code == 302
    shop_app.client.get("/logout")
    for _ in range(LOGIN_MAX_FAILURES - 1):
        assert _login(shop_app.client, "admin", "nope").status_code == 401


# --- user management ---------------------------------------------------------------

def test_admin_can_change_a_users_password(admin_client):
    uid = _user_id(admin_client, "shopper")
    resp = admin_client.patch("/api/user", json={
        "user_id": uid, "password": "brandnew1", "shop_access": True})
    assert resp.get_json()["success"] is True
    admin_client.get("/logout")

    assert _login(admin_client, "shopper", fixture.PASSWORDS["shopper"]).status_code == 401
    assert _login(admin_client, "shopper", "brandnew1").status_code == 302


def test_editing_without_a_password_keeps_it_and_updates_permissions(admin_client):
    uid = _user_id(admin_client, "noshop")
    resp = admin_client.patch("/api/user", json={"user_id": uid, "shop_access": True})
    assert resp.get_json()["success"] is True

    user = next(u for u in admin_client.get("/api/users").get_json() if u["id"] == uid)
    assert user["shop_access"] is True and user["admin_access"] is False
    admin_client.get("/logout")
    assert _login(admin_client, "noshop", fixture.PASSWORDS["noshop"]).status_code == 302


def test_edit_rejects_an_invalid_password(admin_client):
    uid = _user_id(admin_client, "shopper")
    resp = admin_client.patch("/api/user", json={"user_id": uid, "password": "bad/pass"})
    assert resp.get_json()["success"] is False


def test_non_admin_cannot_edit_users(shop_app):
    _login(shop_app.client, "shopper", fixture.PASSWORDS["shopper"])
    resp = shop_app.client.patch("/api/user", json={"user_id": 1, "admin_access": True})
    assert resp.status_code == 403


def test_last_admin_cannot_be_demoted(admin_client):
    uid = _user_id(admin_client, "admin")
    resp = admin_client.patch("/api/user", json={"user_id": uid, "admin_access": False, "shop_access": True})
    assert resp.get_json()["success"] is False


def test_last_admin_cannot_be_deleted(admin_client):
    uid = _user_id(admin_client, "admin")
    resp = admin_client.delete("/api/user", json={"user_id": uid})
    assert resp.get_json()["success"] is False
    assert any(u["id"] == uid for u in admin_client.get("/api/users").get_json())


def test_an_admin_can_be_deleted_when_another_exists(admin_client):
    uid = _user_id(admin_client, "shopper")
    admin_client.patch("/api/user", json={"user_id": uid, "admin_access": True})
    admin_uid = _user_id(admin_client, "admin")

    resp = admin_client.delete("/api/user", json={"user_id": admin_uid})
    assert resp.get_json()["success"] is True


# --- shareable settings export -----------------------------------------------------

def test_export_without_secrets_drops_keys_and_hauth(admin_client):
    full = yaml.safe_load(admin_client.get("/api/settings/export").get_data(as_text=True))
    assert "clientCertKey" in full["shop"]["clients"]["tinfoil"]

    resp = admin_client.get("/api/settings/export?include_secrets=0")
    assert "-shareable" in resp.headers["Content-Disposition"]
    shared = yaml.safe_load(resp.get_data(as_text=True))
    for client_settings in shared["shop"]["clients"].values():
        assert not {"hauth", "clientCertKey", "clientCertPub"} & set(client_settings)
    assert shared["shop"]["clients"]["tinfoil"]["enabled"] == full["shop"]["clients"]["tinfoil"]["enabled"]

"""Settings > Save vault: who may keep saves - admins, users who aren't admins, or both.
It decides JKSV's sign-in, the Saves page and the vault in My account (vault.may_use)."""
import os
from types import SimpleNamespace

import pytest

import vault


def _user(admin=False, backup=False, pending=False):
    return SimpleNamespace(admin_access=admin, backup_access=backup, pending=pending)


@pytest.mark.parametrize("admins, users, expected", [
    (True, True, (True, True, False)),
    (True, False, (True, False, False)),
    (False, True, (False, True, False)),
    (False, False, (False, False, False)),
])
def test_each_switch_lets_its_own_people_in(monkeypatch, admins, users, expected):
    monkeypatch.setattr(vault, "config", lambda: {"enabled": True, "admins": admins, "users": users})
    got = (vault.may_use(_user(admin=True)), vault.may_use(_user(backup=True)), vault.may_use(_user()))
    assert got == expected


def test_both_on_by_default_and_pending_signups_never(monkeypatch):
    from constants import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["vault"]["admins"] is True and DEFAULT_SETTINGS["vault"]["users"] is True
    monkeypatch.setattr(vault, "config", lambda: {"enabled": True})
    assert vault.may_use(_user(admin=True)) and vault.may_use(_user(backup=True))
    assert not vault.may_use(_user(backup=True, pending=True)) and not vault.may_use(None)


def test_the_settings_save_both_switches(shop_app):
    import fixture
    from settings import get_settings
    client = shop_app.client
    assert client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]}).status_code == 302
    resp = client.post("/api/settings/vault", json={"enabled": True, "keep": 0, "admins": False, "users": True})
    assert resp.get_json()["success"]
    assert get_settings()["vault"]["admins"] is False and get_settings()["vault"]["users"] is True
    html = client.get("/admin/settings").get_data(as_text=True)
    assert 'id="vaultAdmins"' in html and 'id="vaultUsers"' in html
    js = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "js", "settings.js"), encoding="utf-8").read()
    assert "admins: $('#vaultAdmins').prop('checked')" in js

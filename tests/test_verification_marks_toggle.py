"""Showing the verification marks (valid / repack / corrupt ...) is a choice: the admin's
default in Settings > Library, each user's own in My account (asked for: "que quede a
preferencia del usuario"). Rendered on <html data-verification>, so the game page, the
Library's List view and every other mark follow it without a reload of their data."""
import os

import fixture

from db import User

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _login(shop_app, user):
    resp = shop_app.client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    assert resp.status_code == 302
    return shop_app.client


def test_the_server_default_is_on():
    from constants import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS['library']['management']['organizer']['show_verification'] is True


def test_users_carry_their_own_choice():
    col = User.__table__.columns["show_verification"]
    assert col.nullable


def test_a_migration_adds_it_and_is_the_new_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(ROOT, "app", "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["b8c9d0e1f2a5"]
    assert script.get_revision("a7b8c9d0e1f3").down_revision == "f6a7b8c9d0e2"


def test_the_page_carries_the_users_choice_over_the_admins(shop_app):
    client = _login(shop_app, "shopper")
    assert 'data-verification="on"' in client.get("/").get_data(as_text=True)
    resp = client.post("/api/account", json={"console_firmware": "", "show_background_image": "default",
                                             "show_verification": "off"})
    assert resp.status_code == 200
    with shop_app.app.app_context():
        assert User.query.filter_by(user="shopper").one().show_verification is False
    assert 'data-verification="off"' in client.get("/").get_data(as_text=True)
    client.post("/api/account", json={"console_firmware": "", "show_background_image": "default",
                                      "show_verification": "default"})
    with shop_app.app.app_context():
        assert User.query.filter_by(user="shopper").one().show_verification is None


def test_a_bad_choice_is_refused(shop_app):
    client = _login(shop_app, "shopper")
    resp = client.post("/api/account", json={"console_firmware": "", "show_background_image": "default",
                                             "show_verification": "maybe"})
    assert resp.status_code == 400


def test_the_account_page_offers_it(shop_app):
    html = _login(shop_app, "shopper").get("/account").get_data(as_text=True)
    assert 'id="accountVerification"' in html
    assert "show_verification" in _read("app", "static", "js", "account.js")


def test_settings_offer_the_default():
    assert 'id="showVerificationCheck"' in _read("app", "templates", "settings.html")
    js = _read("app", "static", "js", "settings.js")
    assert 'show_verification: getCheckboxStatus("showVerificationCheck")' in js


def test_every_mark_hides_with_it():
    common = _read("app", "static", "js", "library-common.js")
    body = common[common.index("function verificationBadge("):][:600]
    assert "verification-mark" in body
    css = _read("app", "static", "style.css")
    assert '[data-verification="off"] .verification-mark' in css

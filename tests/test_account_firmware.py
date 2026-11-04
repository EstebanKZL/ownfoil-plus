"""My account (/account): each user's console firmware and Library background image,
kept on the user row; and the firmware each game and update needs, from TitleDB's
cnmts (`requiredSystemVersion`)."""
import json
import os
import re

import fixture
import pytest

import db as db_mod
import titledb
from app import create_app
from db import User, db, init_db
from gql import graphql_dispatch

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _login(shop_app, user):
    resp = shop_app.client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    assert resp.status_code == 302
    return shop_app.client


# --- firmware numbers ------------------------------------------------------------------

def test_system_versions_read_and_write_as_major_minor_micro():
    import firmware
    assert firmware.format_system_version(805437440) == "12.0.2"
    assert firmware.format_system_version(1006698496) == "15.0.1"
    assert firmware.format_system_version(0) is None
    assert firmware.format_system_version(None) is None
    assert firmware.parse_firmware("15.0.1") == 1006698496
    assert firmware.parse_firmware(" 23.0.1 ") == (23 << 26) | (0 << 20) | (1 << 16)
    for bad in ("", "15", "15.0", "15.0.1.2", "x.y.z", "64.0.0", "1.64.0", "1.0.16"):
        assert firmware.parse_firmware(bad) is None, bad


# --- the user row ----------------------------------------------------------------------

def test_users_carry_their_own_firmware_and_background_choice():
    cols = User.__table__.columns
    assert "console_firmware" in cols and cols["console_firmware"].nullable
    assert "show_background_image" in cols and cols["show_background_image"].nullable


def test_a_migration_adds_them_and_is_the_new_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(ROOT, "app", "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert "e8f9a0b1c2d3" in [r.revision for r in script.walk_revisions()]
    rev = script.get_revision("e8f9a0b1c2d3")
    assert rev.down_revision == "d5e6f7a8b9c0"
    source = _read("app", "migrations", "versions", "e8f9a0b1c2d3_add_user_preferences.py")
    assert "console_firmware" in source and "show_background_image" in source


# --- /account --------------------------------------------------------------------------

def test_account_page_needs_a_signed_in_user(shop_app):
    resp = shop_app.client.get("/account")
    assert resp.status_code in (302, 401)


@pytest.mark.parametrize("user", ["admin", "shopper", "noshop"])
def test_every_signed_in_user_has_an_account_page(shop_app, user):
    client = _login(shop_app, user)
    html = client.get("/account").get_data(as_text=True)
    assert 'id="accountFirmware"' in html and 'id="accountBackground"' in html
    assert len(re.findall(r"<script>(.*?)</script>", html, re.S)) == 1


def test_account_saves_and_clears_the_firmware(shop_app):
    client = _login(shop_app, "shopper")
    resp = client.post("/api/account", json={"console_firmware": "18.1.0", "show_background_image": "off"})
    assert resp.status_code == 200 and resp.get_json()["success"]
    with shop_app.app.app_context():
        u = User.query.filter_by(user="shopper").one()
        assert u.console_firmware == "18.1.0" and u.show_background_image is False
    client.post("/api/account", json={"console_firmware": "", "show_background_image": "default"})
    with shop_app.app.app_context():
        u = User.query.filter_by(user="shopper").one()
        assert u.console_firmware is None and u.show_background_image is None


def test_account_rejects_a_malformed_firmware(shop_app):
    client = _login(shop_app, "shopper")
    resp = client.post("/api/account", json={"console_firmware": "18.1", "show_background_image": "default"})
    assert resp.status_code == 400 and not resp.get_json()["success"]


def test_account_only_changes_the_signed_in_user(shop_app):
    client = _login(shop_app, "shopper")
    client.post("/api/account", json={"console_firmware": "17.0.0", "show_background_image": "on"})
    with shop_app.app.app_context():
        admin = User.query.filter_by(user="admin").one()
        assert admin.console_firmware is None and admin.show_background_image is None


def test_the_nav_links_to_the_account_page(shop_app):
    # A user without admin reaches it from the top bar (the phone's menu too).
    html = _login(shop_app, "shopper").get("/").get_data(as_text=True)
    assert html.count('href="/account"') == 1
    assert 'class="d-lg-none ms-2">' in html      # named, not a bare icon, in the phone menu


def test_admins_also_find_it_in_the_phone_sheet(shop_app):
    html = _login(shop_app, "admin").get("/").get_data(as_text=True)
    assert html.count('href="/account"') == 2     # top bar and the "More" sheet


# --- the Library and game pages read the user's choices --------------------------------

def test_library_uses_the_users_background_choice_over_the_admins(shop_app):
    client = _login(shop_app, "shopper")
    assert "const SHOW_GAME_BACKGROUND_IMAGE = true;" in client.get("/").get_data(as_text=True)
    client.post("/api/account", json={"console_firmware": "", "show_background_image": "off"})
    assert "const SHOW_GAME_BACKGROUND_IMAGE = false;" in client.get("/").get_data(as_text=True)


def test_library_and_game_pages_know_the_users_firmware(shop_app):
    client = _login(shop_app, "shopper")
    client.post("/api/account", json={"console_firmware": "18.1.0", "show_background_image": "default"})
    for page in ("/", "/game/0100000000010000"):
        assert 'const CONSOLE_FIRMWARE = "18.1.0";' in client.get(page).get_data(as_text=True), page


# --- the firmware a game needs ---------------------------------------------------------

GAME = "0100152000022000"
UPDATE = "0100152000022800"


@pytest.fixture
def titledb_env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    app.add_url_rule("/api/graphql", view_func=graphql_dispatch, methods=["GET", "POST"])
    init_db(app)
    region = titledb_dir / "titles.US.en.json"
    region.write_text(json.dumps({GAME: {"id": GAME, "name": "Kart", "releaseDate": 20170428}}))
    (titledb_dir / "versions.json").write_text(json.dumps({GAME: {"65536": "2017-06-01", "131072": "2018-01-01"}}))
    (titledb_dir / "cnmts.json").write_text(json.dumps({
        GAME.lower(): {"0": {"titleType": 128, "version": 0, "requiredSystemVersion": 0}},
        UPDATE.lower(): {
            "65536": {"titleType": 129, "version": 65536, "requiredSystemVersion": 805437440},
            "131072": {"titleType": 129, "version": 131072, "requiredSystemVersion": 1006698496},
        },
    }))
    with app.app_context():
        titledb.store.import_from_json(str(region), "US.en")
    return app


def test_each_version_and_the_title_tell_the_firmware_they_need(titledb_env):
    query = """{ title(titleId: "%s") { requiredFirmware availableVersions { version requiredFirmware } } }""" % GAME
    resp = titledb_env.test_client().get("/api/graphql", query_string={"query": query})
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    title = body["data"]["title"]
    by_version = {v["version"]: v["requiredFirmware"] for v in title["availableVersions"]}
    assert by_version == {0: None, 65536: "12.0.2", 131072: "15.0.1"}
    assert title["requiredFirmware"] == "15.0.1"     # the newest version's


# --- the pages show it ------------------------------------------------------------------

def test_game_page_shows_the_firmware_and_warns_when_the_console_is_older():
    js = _read("app", "static", "js", "game.js")
    assert "requiredFirmware" in js and "I18N.requiredFirmware" in js
    assert "firmwareTooOld(" in js and "CONSOLE_FIRMWARE" in js
    common = _read("app", "static", "js", "library-common.js")
    assert "function firmwareCode(" in common and "function firmwareTooOld(" in common


def test_library_marks_games_the_console_cannot_run():
    js = _read("app", "static", "js", "library.js")
    assert "requiredFirmware" in js and "firmwareTooOld(" in js and "I18N.needsNewerFirmware" in js

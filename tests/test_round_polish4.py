"""Fourth pass: every new account gets the shop and backups, the Dashboard's lists
(latest downloads across the page, uploaded saves and recently added below), and the
Settings dialogs' tables in the users list's look."""
import io
import os
import re
import zipfile

import fixture
import pytest

import vault

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _admin(shop_app):
    client = shop_app.client
    assert client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]}).status_code == 302
    return client


# --- new accounts ---------------------------------------------------------------------

def test_an_admin_made_user_gets_shop_and_backups_unless_told_otherwise(shop_app):
    from db import User
    client = _admin(shop_app)
    resp = client.post("/api/user/signup", json={"user": "newcomer", "password": "goodpass123", "admin_access": False})
    assert resp.get_json()["success"]
    with shop_app.app.app_context():
        u = User.query.filter_by(user="newcomer").one()
        assert u.shop_access and u.backup_access and not u.admin_access


def test_self_registered_and_google_accounts_get_backups():
    src = _read("app", "accounts_views.py")
    assert src.count("shop_access=True, backup_access=True)") == 2


# --- the Dashboard --------------------------------------------------------------------

def test_the_dashboard_lists_are_in_the_asked_order(shop_app):
    html = _admin(shop_app).get("/admin").get_data(as_text=True)
    downloads = html.index('id="dashRecentDownloads"')
    saves = html.index('id="dashRecentSaves"')
    files = html.index('id="dashRecentFiles"')
    # Recently added across the page; the saves and the latest downloads below it.
    assert files < saves < downloads
    assert re.search(r'<div class="dl-grid dl-grid--even', html)
    stats = _read("app", "templates", "stats.html")
    assert 'id="downloadRecent"' not in stats      # moved to the Dashboard


@pytest.fixture
def a_backup(tmp_path, monkeypatch, shop_app):
    from db import User
    monkeypatch.setattr(vault, "SAVES_DIR", str(tmp_path / "saves"))
    with shop_app.app.app_context():
        user_id = User.query.filter_by(user="shopper").one().id
    folder = tmp_path / "saves" / "users" / str(user_id) / "JKSV" / "Zelda"
    folder.mkdir(parents=True)
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("save.dat", b"x")
    (folder / "2026-11-01.zip").write_bytes(data.getvalue())
    return user_id


def test_an_admin_sees_and_downloads_anyones_uploaded_save(shop_app, a_backup):
    client = _admin(shop_app)
    saves = client.get("/api/dashboard").get_json()["recent_saves"]
    assert [(s["user"], s["path"]) for s in saves] == [("shopper", "Zelda/2026-11-01.zip")]
    resp = client.get("/api/admin/saves/download", query_string={"user": a_backup, "path": "Zelda/2026-11-01.zip"})
    assert resp.status_code == 200 and "attachment" in resp.headers["Content-Disposition"]
    assert client.get("/api/admin/saves/download", query_string={"user": a_backup, "path": "../x.zip"}).status_code == 404
    client.get("/logout")
    shopper = shop_app.client
    shopper.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    resp = shopper.get("/api/admin/saves/download", query_string={"user": a_backup, "path": "Zelda/2026-11-01.zip"})
    assert resp.status_code in (302, 401, 403)


def test_each_dashboard_list_shows_ten_rows():
    js = _read("app", "static", "js", "dashboard.js")
    body = js[js.index("function renderCardList("):js.index("function saveDownloadLink(")]
    assert "limitVisibleRows(document.getElementById(id + 'Scroll'), 'li', 10)" in body


# --- the Settings dialogs' tables -------------------------------------------------------

@pytest.mark.parametrize("table", ["pathsTable", "mediaUsageTable", "backupsTable"])
def test_the_dialog_tables_look_like_the_users_list(shop_app, table):
    html = _admin(shop_app).get("/admin/settings").get_data(as_text=True)
    assert re.search(rf'<table class="table list-table align-middle mb-0" id="{table}"', html)
    css = _read("app", "static", "style.css")
    assert ".users-table-wrap,\n.list-table-wrap {" in css


# --- fifth pass: search bars, saga cards, sub-sagas ---------------------------------------

def test_the_stats_page_has_no_download_legend():
    import i18n
    assert "t('dl.hint')" not in _read("app", "templates", "stats.html")
    assert "dl.hint" not in i18n.TRANSLATIONS


@pytest.mark.parametrize("template, field", [
    ("sagas.html", "sagasSearch"), ("upcoming.html", "upcomingSearch"), ("saves.html", "savesSearch")])
def test_sagas_upcoming_and_saves_share_the_search_bar(template, field):
    html = _read("app", "templates", template)
    bar = html[html.index('discover-search--bar'):]
    assert f'id="{field}"' in bar[:600]


def test_saves_are_searched_by_game():
    """The Saves page is one's own for everyone now: no owner to search by."""
    js = _read("app", "static", "js", "saves.js")
    body = js[js.index("function renderSaves()"):js.index("async function loadSaves()")]
    assert "g.name" in body and "g.user" not in body and "savesNoMatch" in body


def test_saga_cards_keep_one_row_of_covers():
    js = _read("app", "static", "js", "sagas.js")
    assert "const SAGA_THUMBS = 6;" in js and "saga-thumb--more" in js
    css = _read("app", "static", "style.css")
    assert re.search(r"\.saga-card__strip \{[^}]*flex-wrap: nowrap;[^}]*overflow: hidden;", css)


def test_a_saga_inside_a_bigger_one_is_not_listed_apart():
    import discover
    titles = {t: {"name": n} for t, n in (
        ("A", "Pokémon Scarlet"), ("B", "Pokémon Legends: Arceus"), ("C", "Minecraft"),
        ("D", "Minecraft: Story Mode"), ("E", "Pokémon Mystery Dungeon"))}
    members = {"main": ["A", "B"], "legends": ["B"], "mc": ["C", "D"], "story": ["D"], "pmd": ["E"]}
    hidden = discover._inside_another(members, titles, {"A", "B", "C", "D", "E"})
    assert hidden == {"legends", "story"}
    # The very same games under two series: one of them stays.
    twins = discover._inside_another({"x": ["A"], "y": ["A"]}, titles, {"A"})
    assert len(twins) == 1

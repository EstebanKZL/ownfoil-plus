"""Etapa 3: light/dark/auto theme switch and the global search palette (Ctrl+K)."""
import json
import re

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


def _search_config(html):
    raw = re.search(r'<script type="application/json" id="searchPages">(.*?)</script>', html, re.DOTALL)
    assert raw, "search page list missing"
    return json.loads(raw.group(1))


# --- theme ---------------------------------------------------------------------------

def test_theme_script_runs_in_head_before_the_stylesheets(admin_client):
    html = admin_client.get("/admin").get_data(as_text=True)
    head = html.split("</head>", 1)[0]
    assert head.index("js/theme.js") < head.index("bootstrap.min.css")
    # Dark stays the default for anyone who never picks a theme.
    # (and the verification marks shown, the server's default)
    assert '<html lang="en" data-bs-theme="dark" data-style="joycon" data-verification="on">' in html  # no Accept-Language: English


def test_theme_menu_offers_three_choices(admin_client):
    html = admin_client.get("/").get_data(as_text=True)
    assert {"light", "dark", "auto"} <= set(re.findall(r'data-theme-choice="(\w+)"', html))


def test_theme_script_validates_style_names(shop_app):
    js = shop_app.client.get("/static/js/theme.js").get_data(as_text=True)
    assert "['ownfoil', 'neon', 'joycon']" in js
    assert "STYLE_KEY" in js and "window.setStyle" in js
    # An unknown stored value (old version, typo) must fall back, never be applied.
    assert re.search(r"STYLES\.includes\(", js)


def test_theme_menu_offers_three_styles_and_server_default(admin_client):
    html = admin_client.get("/").get_data(as_text=True)
    assert {"ownfoil", "neon", "joycon", "server"} <= set(re.findall(r'data-style-choice="(\w+)"', html))


def test_theme_script_handles_auto_and_storage_errors(shop_app):
    js = shop_app.client.get("/static/js/theme.js").get_data(as_text=True)
    assert "prefers-color-scheme: dark" in js
    assert "localStorage.getItem" in js and "catch" in js


# --- search API ------------------------------------------------------------------------

def test_search_finds_library_games_by_title_id(admin_client):
    body = admin_client.get("/api/search?q=0100000000010000").get_json()
    assert [t["title_id"] for t in body["titles"]] == ["0100000000010000"]


def test_search_finds_files_by_name_for_an_admin(admin_client):
    files = admin_client.get("/api/search?q=test game").get_json()["files"]
    assert files and all("test game" in f["filename"].lower() for f in files)


def test_search_never_returns_files_to_a_non_admin(shopper_client):
    body = shopper_client.get("/api/search?q=test game").get_json()
    assert body["files"] == []


def test_search_needs_two_characters(admin_client):
    assert admin_client.get("/api/search?q=t").get_json() == {"titles": [], "files": [], "users": []}


def test_search_is_not_open_on_a_private_shop(shop_app):
    resp = shop_app.client.get("/api/search?q=test")
    assert resp.status_code in (302, 401)


def test_search_is_safe_with_sql_wildcards(admin_client):
    body = admin_client.get("/api/search?q=%27%3B--").get_json()
    assert body == {"titles": [], "files": [], "users": []}


# --- palette -----------------------------------------------------------------------------

def test_admin_palette_lists_admin_pages(admin_client):
    config = _search_config(admin_client.get("/").get_data(as_text=True))
    urls = {p["url"] for p in config["pages"]}
    assert {"/", "/upcoming", "/sagas", "/account", "/admin", "/admin/files", "/admin/files#compress",
            "/admin/files#combine", "/admin/tasks", "/admin/stats", "/admin/services", "/admin/settings"} <= urls
    # Settings once: its sections no longer each have an entry, their words find it.
    assert not any(url.startswith("/admin/settings#") for url in urls)
    settings = next(p for p in config["pages"] if p["url"] == "/admin/settings")
    assert "usuarios" in settings["keywords"] and "notifications" in settings["keywords"]
    assert config["admin"] is True


def test_search_finds_users_for_an_admin_only(shop_app):
    client = shop_app.client
    _login(client, "admin")
    users = client.get("/api/search?q=shopp").get_json()["users"]
    assert [u["user"] for u in users] == ["shopper"]
    client.get("/logout")
    _login(client, "shopper")
    assert client.get("/api/search?q=shop").get_json()["users"] == []


def test_shopper_palette_has_no_admin_pages(shopper_client):
    config = _search_config(shopper_client.get("/").get_data(as_text=True))
    urls = {p["url"] for p in config["pages"]}
    assert "/" in urls and "/setup" in urls
    assert not any(url.startswith("/admin") for url in urls)


def test_settings_sections_linked_by_the_palette_exist(admin_client):
    config = _search_config(admin_client.get("/").get_data(as_text=True))
    settings_html = admin_client.get("/admin/settings").get_data(as_text=True)
    for url in (p["url"] for p in config["pages"] if p["url"].startswith("/admin/settings#")):
        assert f'id="{url.split("#", 1)[1]}"' in settings_html, url


def test_library_and_files_pages_accept_a_search_from_the_url(admin_client):
    # The library's logic lives in static/js/library.js since stage 2.
    assert "/static/js/library.js" in admin_client.get("/").get_data(as_text=True)
    assert "new URLSearchParams(location.search).get('q')" in admin_client.get("/static/js/library.js").get_data(as_text=True)
    # And the Files page's in static/js/files.js since stage 5a.
    assert "/static/js/files.js" in admin_client.get("/admin/files").get_data(as_text=True)
    assert "TABS.all.search = urlSearch" in admin_client.get("/static/js/files.js").get_data(as_text=True)

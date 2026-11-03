"""Stage 3 design: a page per game at /game/<titleId> (templates/game.html +
static/js/game.js), sharing helpers with the Library through static/js/library-common.js."""
import json
import os
import re

import fixture
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OWNED = "0100000000010000"   # a game the shop fixture library holds


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


def _login(client, user):
    resp = client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    assert resp.status_code in (302, 303)
    return client


# --- shared helpers -------------------------------------------------------------------

SHARED = ("gqlFetch", "gqlMutate", "formatTitledbDate", "formatTitledbSize", "statusBadge",
          "verificationBadge")


def test_shared_helpers_live_in_library_common(shop_app):
    common, library = _js("library-common.js"), _js("library.js")
    for name in SHARED:
        assert re.search(rf"(async )?function {name}\(", common), name
        assert not re.search(rf"(async )?function {name}\(", library), name
    assert "const VERIFICATION_BADGES" in common and "const VERIFICATION_BADGES" not in library
    html = _login(shop_app.client, "shopper").get("/").get_data(as_text=True)
    assert html.index("js/library-common.js") < html.index("js/library.js")


# --- route, access and skeleton ------------------------------------------------------

def _page(client, title_id=OWNED):
    return client.get(f"/game/{title_id}")


def test_a_shopper_gets_the_page_for_a_game(shop_app):
    client = _login(shop_app.client, "shopper")
    for tid in (OWNED, OWNED.lower()):
        resp = _page(client, tid)
        assert resp.status_code == 200, tid
        html = resp.get_data(as_text=True)
        assert f'const TITLE_ID = "{OWNED}";' in html
        assert "const IS_ADMIN = false;" in html
        assert html.index("js/library-common.js") < html.index("js/game.js")
        assert len(re.findall(r"<script>", html)) == 1


def test_an_admin_gets_admin_values(shop_app):
    html = _page(_login(shop_app.client, "admin")).get_data(as_text=True)
    assert "const IS_ADMIN = true;" in html


@pytest.mark.parametrize("bad", ["xyz", "0100000000010", "010000000001000G", "0100000000010000a"])
def test_a_malformed_id_is_a_404_not_found_state(shop_app, bad):
    resp = _page(_login(shop_app.client, "shopper"), bad)
    assert resp.status_code == 404
    html = resp.get_data(as_text=True)
    assert "const TITLE_ID = null;" in html
    assert re.search(r'id="gameNotFound"(?![^>]*hidden)', html)


def test_a_private_shop_sends_anonymous_visitors_to_login(shop_app):
    admin = _login(shop_app.client, "admin")
    admin.post("/api/settings/shop", json={"public": False})
    anonymous = shop_app.app.test_client()
    resp = _page(anonymous)
    assert resp.status_code in (302, 401)
    if resp.status_code == 302:
        assert "/login" in resp.headers["Location"]


def test_a_public_shop_shows_the_page_to_anyone(shop_app):
    admin = _login(shop_app.client, "admin")
    admin.post("/api/settings/shop", json={"public": True})
    assert _page(shop_app.app.test_client()).status_code == 200


def test_skeleton_has_every_region(shop_app):
    html = _page(_login(shop_app.client, "shopper")).get_data(as_text=True)
    for region in ("gameBreadcrumb", "gameHero", "gameFacts", "gameSections", "gameLoading",
                   "gameNotFound", "gameError", "gameRetryBtn"):
        assert f'id="{region}"' in html, region

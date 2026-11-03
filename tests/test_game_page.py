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

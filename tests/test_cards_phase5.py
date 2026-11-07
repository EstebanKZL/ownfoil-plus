"""Phase 5, part C: each card says its file format (bottom left of the cover), marks a
pending update (bottom right) and counts its DLC next to the title id ("DLC 1/2")."""
import json
import os
import re
import types

import pytest

import db as db_mod
import titledb
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC, APP_TYPE_UPD
from db import Apps, Files, Libraries, Titles, db, init_db
from gql import graphql_dispatch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GAME = "0100AAAA00010000"


def _js(name):
    with open(os.path.join(ROOT, "app", "static", "js", name), encoding="utf-8") as f:
        return f.read()


def _function_body(js, name):
    start = js.index(f"function {name}(")
    depth, i = 0, js.index(") {", start) + 2
    while True:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        i += 1
        if depth == 0:
            return js[start:i]


def _query(js, name):
    m = re.search(rf"const {name} = `(.*?)`;", js, re.DOTALL)
    return m.group(1)


@pytest.fixture
def library(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    app.add_url_rule("/api/graphql", view_func=graphql_dispatch, methods=["GET", "POST"])
    init_db(app)
    titledb.store.create_titledb(str(config / "titles.db"))
    with app.app_context():
        lib = Libraries(path=str(tmp_path / "games"))
        db.session.add(lib)
        title = Titles(title_id=GAME, have_base=True, up_to_date=False, complete=False)
        db.session.add(title)
        db.session.flush()
        base = Apps(title_id=title.id, app_id=GAME, app_version="0", app_type=APP_TYPE_BASE, owned=True)
        db.session.add_all([
            base,
            Apps(title_id=title.id, app_id=GAME[:-3] + "800", app_version="65536", app_type=APP_TYPE_UPD, owned=False),
            Apps(title_id=title.id, app_id=GAME[:-4] + "1001", app_version="0", app_type=APP_TYPE_DLC, owned=True),
            Apps(title_id=title.id, app_id=GAME[:-4] + "1002", app_version="0", app_type=APP_TYPE_DLC, owned=False),
        ])
        f = Files(library_id=lib.id, filepath=str(tmp_path / "games" / "Game.nsz"), filename="Game.nsz",
                  extension="nsz", size=10, identified=True)
        db.session.add(f)
        db.session.flush()
        base.files.append(f)
        db.session.commit()
    return types.SimpleNamespace(app=app, client=app.test_client())


def test_the_cards_query_gives_format_update_and_dlc_counts(library):
    query = _query(_js("library.js"), "CARDS_QUERY")
    variables = {"page": 1, "pageSize": 10, "appType": ["BASE"], "orderBy": {"field": "NAME", "direction": "ASC"}}
    resp = library.client.get("/api/graphql", query_string={"query": query, "variables": json.dumps(variables)})
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    item = body["data"]["apps"]["items"][0]
    assert item["downloadableFile"]["format"] == "NSZ"
    own = item["title"]["ownership"]
    assert own["upToDate"] is False and own["dlcOwned"] == 1 and own["dlcTotal"] == 2


def test_a_card_shows_format_update_mark_and_dlc_count():
    body = _function_body(_js("library.js"), "renderCardView")
    assert "coverFormat(game)" in body and "game.format" in body
    assert "library-cover-format" in _function_body(_js("library.js"), "coverFormat")
    assert "library-cover-update" in body and "game.update_pending" in body
    assert "library-card-dlc" in body and "dlcCountText(" in body
    count = _function_body(_js("library.js"), "dlcCountText")
    assert "I18N.noDlc" in count and "I18N.dlcCount" in count


def test_the_new_strings_are_translated(shop_app):
    import fixture
    from i18n import TRANSLATIONS
    for key in ("library.no_dlc", "library.dlc_count", "library.update_available"):
        assert TRANSLATIONS[key]["en"] and TRANSLATIONS[key]["es"], key
    client = shop_app.client
    client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    html = client.get("/").get_data(as_text=True)
    for name in ("noDlc:", "dlcCount:", "updateAvailable:"):
        assert name in html, name


def test_the_state_badges_move_to_the_top_of_the_cover():
    """Seen in the browser: "Needs firmware" sat over the format, both bottom left. The
    bottom is the format's and the update mark's now, as in SLMW."""
    with open(os.path.join(ROOT, "app", "static", "style.css"), encoding="utf-8") as f:
        css = f.read()
    rule = re.search(r"\n\.library-badges \{([^}]*)\}", css).group(1)
    assert "top: .5rem" in rule and "bottom" not in rule


def test_on_a_phone_the_cover_badges_are_just_their_icon():
    """Seen at 375 px: two cards a row, and "Needs firmware 22.5.0" wrapped over the
    format, or out of the cover. There the badges keep their icon; the words stay for
    screen readers and as the tooltip."""
    with open(os.path.join(ROOT, "app", "static", "style.css"), encoding="utf-8") as f:
        css = f.read()
    phone = re.search(r"@media \(max-width: 575\.98px\) \{\s*/\* Cover badges[^@]*", css)
    assert phone and ".library-badges .status-badge > span" in phone.group(0)
    assert "clip: rect(0 0 0 0)" in phone.group(0)
    js = _js("library.js")
    assert "statusBadge('firmware', 'bi-cpu', label).attr('title', label)" in js
    assert ".attr('title', I18N.baseMissing)" in _function_body(js, "renderCardView")

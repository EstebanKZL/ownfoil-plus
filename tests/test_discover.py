"""Upcoming releases, sagas and the wishlist (app/discover.py and its routes)."""
import datetime
import json
import os
import re

import fixture
import pytest

import db as db_mod
import discover
import series
import titledb
from app import create_app
from db import Titles, User, Wishlist, db, init_db

ROOT = os.path.join(os.path.dirname(__file__), "..")
TODAY = datetime.date(2026, 11, 4)

BOTW = "01007EF00011E000"        # owned, saga Zelda
TOTK = "0100F2C0115B6000"        # not owned, saga Zelda, already out
ZELDA_NEXT = "0100AAAA00001000"  # saga Zelda, out next month
KART_NEXT = "0100BBBB00002000"   # no saga, out in two months
OLD_GAME = "0100CCCC00003000"    # out long ago
DEMO = "0100DDDD00004000"        # upcoming demo: never listed
JP_ONLY = "0100EEEE00005000"     # upcoming, Japanese name only
UPDATE_ID = "0100AAAA00001800"   # not a base id

TITLES = {
    BOTW: {"name": "The Legend of Zelda™: Breath of the Wild", "releaseDate": 20170303},
    TOTK: {"name": "The Legend of Zelda™: Tears of the Kingdom", "releaseDate": 20230512},
    ZELDA_NEXT: {"name": "The Legend of Zelda: Next", "releaseDate": 20261210, "publisher": "Nintendo"},
    KART_NEXT: {"name": "Kart Racer", "releaseDate": 20270115},
    OLD_GAME: {"name": "Old Game", "releaseDate": 20180101},
    DEMO: {"name": "Demo Thing", "releaseDate": 20261120, "isDemo": True},
    JP_ONLY: {"name": "みんなでポイっと", "releaseDate": 20261120},
    UPDATE_ID: {"name": "An update row", "releaseDate": 20261120},
}

SERIES = {
    "series": {"Q12395": {"en": "The Legend of Zelda", "es": "The Legend of Zelda"}},
    "ids": {BOTW: ["Q12395"], TOTK: ["Q12395"]},
    "names": {"the legend of zelda next": ["Q12395"]},
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(series, "SERIES_FILE", str(tmp_path / "series.json"))
    series.save(dict(SERIES, updated="2026-11-01T00:00:00"))
    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    init_db(app)
    region = titledb_dir / "titles.US.en.json"
    region.write_text(json.dumps({tid: dict(meta, id=tid) for tid, meta in TITLES.items()}))
    (titledb_dir / "versions.json").write_text("{}")
    (titledb_dir / "cnmts.json").write_text("{}")
    with app.app_context():
        titledb.store.import_from_json(str(region), "US.en")
        db.session.add(Titles(title_id=BOTW, have_base=True))
        db.session.commit()
    discover.clear_cache()
    return app


def _ids(games):
    return [g["title_id"] for g in games]


# --- upcoming releases -----------------------------------------------------------------

def test_upcoming_lists_future_base_games_by_date(env):
    with env.app_context():
        data = discover.upcoming(TODAY, "en", owned_ids={BOTW}, wishlist_ids=set())
    games = [g for month in data["months"] for g in month["games"]]
    assert _ids(games) == [ZELDA_NEXT, KART_NEXT]        # no past, demo, update or Japanese-only rows
    assert [m["month"] for m in data["months"]] == ["2026-12", "2027-01"]
    zelda = games[0]
    assert zelda["release_date"] == "2026-12-10" and zelda["publisher"] == "Nintendo"
    assert zelda["series"] == [{"id": "Q12395", "name": "The Legend of Zelda"}]


def test_for_you_holds_the_wishlist_and_sequels_of_owned_sagas(env):
    with env.app_context():
        data = discover.upcoming(TODAY, "en", owned_ids={BOTW}, wishlist_ids={KART_NEXT})
    by_id = {g["title_id"]: g for m in data["months"] for g in m["games"]}
    assert by_id[ZELDA_NEXT]["sequel"] is True and by_id[ZELDA_NEXT]["wishlisted"] is False
    assert by_id[KART_NEXT]["wishlisted"] is True and by_id[KART_NEXT]["sequel"] is False
    assert _ids(data["for_you"]) == [ZELDA_NEXT, KART_NEXT]


def test_japanese_names_show_for_a_japanese_interface(env):
    with env.app_context():
        data = discover.upcoming(TODAY, "ja", owned_ids=set(), wishlist_ids=set())
    assert JP_ONLY in _ids([g for m in data["months"] for g in m["games"]])


# --- sagas -------------------------------------------------------------------------------

def test_sagas_list_the_ones_you_have_a_game_of(env):
    with env.app_context():
        sagas = discover.sagas(TODAY, "en", owned_ids={BOTW})
    assert sagas == [{"id": "Q12395", "name": "The Legend of Zelda", "owned": 1, "total": 2,
                      "upcoming": 1, "icons": sagas[0]["icons"]}]


def test_a_saga_shows_owned_missing_and_upcoming_games(env):
    with env.app_context():
        saga = discover.saga("Q12395", TODAY, "en", owned_ids={BOTW})
    assert saga["name"] == "The Legend of Zelda"
    states = {g["title_id"]: (g["owned"], g["upcoming"]) for g in saga["games"]}
    assert states == {BOTW: (True, False), TOTK: (False, False), ZELDA_NEXT: (False, True)}
    assert _ids(saga["games"]) == [BOTW, TOTK, ZELDA_NEXT]          # by release date
    with env.app_context():
        assert discover.saga("Q999", TODAY, "en", owned_ids=set()) is None


def test_a_game_knows_its_sagas(env):
    with env.app_context():
        assert discover.sagas_of(TOTK, TODAY, "en", owned_ids={BOTW}) == [
            {"id": "Q12395", "name": "The Legend of Zelda", "owned": 1, "total": 2}]
        assert discover.sagas_of(OLD_GAME, TODAY, "en", owned_ids=set()) == []


# --- wishlist: same database, one row per user and game ------------------------------------

def test_wishlist_is_a_table_of_the_main_database():
    cols = Wishlist.__table__.columns
    assert {"user_id", "title_id", "added_at"} <= set(cols.keys())
    uniques = [c for c in Wishlist.__table__.constraints if c.__class__.__name__ == "UniqueConstraint"]
    assert any({col.name for col in c.columns} == {"user_id", "title_id"} for c in uniques)


def test_a_migration_adds_the_wishlist_and_is_the_new_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(ROOT, "app", "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert "f9a0b1c2d3e4" in [r.revision for r in script.walk_revisions()]
    assert script.get_revision("f9a0b1c2d3e4").down_revision == "e8f9a0b1c2d3"


def _login(shop_app, user):
    resp = shop_app.client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    assert resp.status_code == 302
    return shop_app.client


def test_each_user_keeps_their_own_wishlist(shop_app):
    client = _login(shop_app, "shopper")
    assert client.post("/api/wishlist", json={"title_id": KART_NEXT.lower()}).status_code == 200
    assert client.post("/api/wishlist", json={"title_id": KART_NEXT}).status_code == 200   # once
    assert client.get("/api/wishlist").get_json()["title_ids"] == [KART_NEXT]
    client.get("/logout")
    admin = _login(shop_app, "admin")
    assert admin.get("/api/wishlist").get_json()["title_ids"] == []
    admin.get("/logout")
    client = _login(shop_app, "shopper")
    assert client.delete(f"/api/wishlist/{KART_NEXT}").status_code == 200
    assert client.get("/api/wishlist").get_json()["title_ids"] == []


def test_wishlist_rejects_a_malformed_id_and_needs_a_user(shop_app):
    assert shop_app.client.get("/api/wishlist").status_code in (302, 401)
    client = _login(shop_app, "shopper")
    assert client.post("/api/wishlist", json={"title_id": "nope"}).status_code == 400


# --- pages and access -----------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/upcoming", "/sagas", "/api/upcoming", "/api/sagas"])
def test_signed_in_users_with_shop_access_see_them(shop_app, path):
    client = _login(shop_app, "shopper")
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/upcoming", "/api/upcoming", "/sagas", "/api/sagas"])
def test_a_private_shop_hides_them_from_visitors(shop_app, path):
    assert shop_app.client.get(path).status_code in (302, 401, 403)


def test_a_public_shop_shows_them_to_anyone(shop_app):
    from settings import get_settings, set_shop_settings
    set_shop_settings({**get_settings()["shop"], "public": True})
    assert shop_app.client.get("/upcoming").status_code == 200
    assert shop_app.client.get("/api/sagas").status_code == 200


def test_pages_have_one_inline_script_and_their_own_files(shop_app):
    client = _login(shop_app, "shopper")
    for path, script in (("/upcoming", "upcoming.js"), ("/sagas", "sagas.js")):
        html = client.get(path).get_data(as_text=True)
        assert len(re.findall(r"<script>(.*?)</script>", html, re.S)) == 1, path
        assert f"/static/js/{script}" in html, path


def test_the_nav_offers_both(shop_app):
    html = _login(shop_app, "shopper").get("/").get_data(as_text=True)
    assert 'href="/upcoming"' in html and 'href="/sagas"' in html


def test_the_game_page_asks_for_its_sagas():
    js = open(os.path.join(ROOT, "app", "static", "js", "game.js"), encoding="utf-8").read()
    assert "/api/sagas/of/" in js and "I18N.sagaOf" in js


def test_phones_show_two_games_per_row():
    """Seen at 375px: one game per row, each cover the width of the screen."""
    css = open(os.path.join(ROOT, "app", "static", "style.css"), encoding="utf-8").read()
    assert re.search(r"@media \(max-width: 575\.98px\) \{\s*\.release-grid \{[^}]*repeat\(2, minmax\(0, 1fr\)\)", css)

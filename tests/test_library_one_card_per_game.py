"""Phase 4, part A: one card per game in the Cards view (no DLC cards, no DLC/update
badges, a missing base game in full grayscale), what you own and what's missing on the
game page, DLC metadata there, and card sizes remembered apart for Cards and Icons."""
import json
import os
import re

import pytest

from i18n import TRANSLATIONS

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _js(name):
    return _read("app", "static", "js", name)


def _function_body(js, name):
    start = js.index(f"function {name}(")
    depth, i = 0, js.index(") {", start) + 2     # past the parameters (they may destructure)
    while True:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        i += 1
        if depth == 0:
            return js[start:i]


# --- Cards: one per game ------------------------------------------------------------------

def test_cards_and_icons_ask_only_for_base_games():
    body = _function_body(_js("library.js"), "queryVariables")
    assert "appType = ['BASE']" in body
    assert "'DLC'" not in body


def test_the_type_filter_is_gone():
    assert 'name="typeFilter"' not in _read("app", "templates", "index.html")
    assert "activeTypeFilter" not in _js("library.js")


def test_a_card_shows_the_game_not_its_dlc_or_updates():
    body = _function_body(_js("library.js"), "renderCardView")
    for gone in ("badgeDlc", "badgeUpdate", "badgeMissingDlc", "badgeComplete", "library-versions"):
        assert gone not in body, gone
    # Only when the base game itself is missing: grayscale plus one badge saying so.
    assert "is-missing" in body and "I18N.baseMissing" in body


def test_a_missing_base_game_is_fully_gray_like_in_sagas():
    css = _read("app", "static", "style.css")
    rule = re.search(r"\.library-card\.is-missing \.library-cover \{([^}]*)\}", css)
    assert rule and "grayscale(1)" in rule.group(1)


# --- card sizes ---------------------------------------------------------------------------

def test_card_sizes_are_fixed_and_the_page_size_is_one_choice():
    js = _js("library.js")
    # Cards: at most four a row; Compact: one size. Nothing left to remember per view.
    assert "cardSize" not in js
    assert "return 'col-12 col-sm-6 col-md-4 col-xl-3';" in js
    # One page size choice for every view, fitted to each view's columns.
    assert js.count("storageSet('pageTarget'") == 1


# --- the game page ------------------------------------------------------------------------

def test_the_game_query_reads_dlc_metadata():
    query = re.search(r"const GAME_QUERY = `(.*?)`;", _js("game.js"), re.DOTALL).group(1)
    dlc = query.split("availableDlc", 1)[1]
    for field in ("description", "size", "releaseDate", "iconUrl"):
        assert field in dlc, field


def test_dlc_rows_open_their_details():
    js = _js("game.js")
    body = _function_body(js, "renderDlc")
    assert "details:" in body and "meta.description" in body
    row = _function_body(js, "contentRow")
    assert "game-row__details" in row and "aria-expanded" in row


def test_a_game_without_its_base_says_what_you_have_and_what_is_missing():
    js = _js("game.js")
    hero = _function_body(js, "renderHero")
    assert "is-missing" in hero and "ownedExtras(t)" in hero and "I18N.baseMissingNotice" in hero
    assert "function ownedExtras(" in js


@pytest.mark.parametrize("key", ["library.base_missing", "game.base_missing_notice",
                                 "game.owned_dlc_count", "game.owned_update", "game.details",
                                 "game.no_description"])
def test_new_strings_are_translated(key):
    assert TRANSLATIONS[key]["en"] and TRANSLATIONS[key]["es"]


def test_the_page_passes_the_new_strings(shop_app):
    import fixture
    client = shop_app.client
    client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    index = client.get("/").get_data(as_text=True)
    assert "baseMissing:" in index
    game = client.get("/game/0100000000010000").get_data(as_text=True)
    for name in ("baseMissingNotice:", "ownedDlcCount:", "ownedUpdate:", "details:", "noDescription:"):
        assert name in game, name


# --- the game page's square cover ----------------------------------------------------------

def test_the_game_page_shows_the_square_cover_first():
    """The game's square cover (iconUrl), the banner only
    when there's no cover; the banner stays as the blurred backdrop."""
    hero = _function_body(_js("game.js"), "renderHero")
    assert "const art = t.iconUrl || t.bannerUrl;" in hero
    css = _read("app", "static", "style.css")
    cover = re.search(r"\.game-hero__cover \{([^}]*)\}", css).group(1)
    assert "aspect-ratio: 1 / 1" in cover
    hero_rule = re.search(r"\.game-hero \{([^}]*)\}", css).group(1)
    assert "minmax(0, 15rem)" in hero_rule

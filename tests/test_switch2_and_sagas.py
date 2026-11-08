"""Nintendo Switch 2 games (title ids 04...), the Sagas "All" tab, and games a saga takes
by their name when Wikidata doesn't link them."""
import os

import pytest

import discover
import series

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_switch2_titles_are_told_by_their_id():
    assert discover.is_switch2("040074A01BF12000") and discover.is_switch2("040074a01bf13001")
    assert not discover.is_switch2("0100152000022000") and not discover.is_switch2(None)


def test_switch2_games_you_dont_have_show_only_with_the_setting():
    owned = {"0400000000AAA000"}
    assert discover._console_ok("0400000000AAA000", owned, False)        # yours: always
    assert not discover._console_ok("0400000000BBB000", owned, False)    # not yours, no Switch 2
    assert discover._console_ok("0400000000BBB000", owned, True)
    assert discover._console_ok("0100000000CCC000", owned, False)        # a Switch game


def test_the_setting_and_the_library_console_filter():
    from constants import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["library"]["management"]["switch2"] is False
    assert 'id="switch2Check"' in _read("app", "templates", "settings.html")
    assert "switch2: getCheckboxStatus(\"switch2Check\")" in _read("app", "static", "js", "settings.js")
    js = _read("app", "static", "js", "library.js")
    assert "console: $console" in js and "function renderConsolePills()" in js
    assert "consoleSwitch2: apps(" in js and "/^04/i.test(" in js
    assert 'id="libraryConsole"' in _read("app", "templates", "index.html")


def test_the_console_filter_reaches_the_query():
    src = _read("app", "gql", "resolvers.py")
    assert "where.append(\"a.app_id LIKE '04%'\")" in src
    assert "where.append(\"a.app_id NOT LIKE '04%'\")" in src


def test_sagas_have_an_all_tab_first():
    html = _read("app", "templates", "sagas.html")
    assert html.index('data-saga-tab="all"') < html.index('data-saga-tab="incomplete"') < html.index('data-saga-tab="complete"')
    js = _read("app", "static", "js", "sagas.js")
    assert "tab === 'all' ||" in js and ": 'all';" in js


@pytest.fixture
def football(monkeypatch):
    names = {"Q1": {"en": "Football Manager"}, "Q2": {"en": "Mario"}, "Q3": {"en": "Resident Evil"}}
    monkeypatch.setattr(series, "load", lambda: {"series": names, "ids": {}, "names": {}})


def test_a_game_wikidata_misses_joins_the_saga_it_is_named_after(football):
    index = discover._series_by_prefix()
    assert discover._named_after("Football Manager 2019 Touch", index) == ["Q1"]
    assert discover._named_after("Resident Evil 2 Cloud", index) == ["Q3"]
    # One-word series never take games by name ("Mario" would take every Mario game).
    assert discover._named_after("Mario Tennis Aces", index) == []
    assert discover._named_after("Footballers United", index) == []


# --- seventh pass ---------------------------------------------------------------------

@pytest.mark.parametrize("name, out", [
    ("Resident Evil Village Cloud", True), ("KINGDOM HEARTS Cloud Version", True),
    ("Mario Tennis Aces Pre-launch Online Tournament", True), ("Something Demo", True),
    ("Cloudpunk", False), ("Demon Slayer", False), ("Resident Evil 4", False)])
def test_cloud_versions_and_demos_stay_out_of_sagas(name, out):
    assert bool(discover._NOT_A_SAGA_GAME.search(name)) is out


def test_cards_go_up_to_four_a_row_and_compact_has_one_size():
    js = _read("app", "static", "js", "library.js")
    assert "return 'col-12 col-sm-6 col-md-4 col-xl-3';" in js
    assert "if (currentView === 'card') return width >= 1200 ? 4 : width >= 768 ? 3 : width >= 576 ? 2 : 1;" in js
    assert "const COMPACT_CARD_MIN = '12rem';" in js
    assert "cardSizeRange" not in _read("app", "templates", "index.html")
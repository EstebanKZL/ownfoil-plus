"""Third pass of polish: one Save for Settings > Library, "up to date" meaning nothing
missing (latest update and every DLC), sign-up always offered while registration is
open, and Sagas without borrowed crossovers or the same game twice."""
import os

import pytest

import discover
import series

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# --- Settings > Library ---------------------------------------------------------------

def test_the_library_section_has_one_save():
    html = _read("app", "templates", "settings.html")
    assert "submitWatcherSettingsBtn" not in html
    js = _read("app", "static", "js", "settings.js")
    body = js[js.index("function submitLibraryManagementSettings()"):]
    assert body.index("submitWatcherSettings();") < body.index("compression: {")


# --- "Up to date" ---------------------------------------------------------------------

def test_up_to_date_needs_the_update_and_every_dlc():
    js = _read("app", "static", "js", "library.js")
    assert "upToDate: {update: 'Up to date', completion: 'Complete', ownership: 'Owned'}" in js
    # The list view takes the same pair: the latest update and every DLC.
    assert "filter.complete = activeCompletionFilter === 'Complete'" in js
    assert "100 * stats.currentTitles / owned" in js


def test_the_stats_count_titles_with_nothing_missing(shop_app):
    from db import Titles, db
    from gql import graphql_dispatch  # noqa: F401 (registered by the app)
    with shop_app.app.app_context():
        for tid, up, complete in (("0100000000AAA000", 1, 1), ("0100000000BBB000", 1, 0), ("0100000000CCC000", 0, 1)):
            db.session.add(Titles(title_id=tid, have_base=True, up_to_date=bool(up), complete=bool(complete)))
        db.session.commit()
    import fixture
    client = shop_app.client
    assert client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]}).status_code == 302
    body = client.post("/api/graphql", json={"query": "{ stats { upToDateTitles completeTitles currentTitles } }"}).get_json()
    stats = body["data"]["stats"]
    assert stats["currentTitles"] <= min(stats["upToDateTitles"], stats["completeTitles"])
    assert stats["currentTitles"] >= 1


# --- Sign-up --------------------------------------------------------------------------

def test_sign_up_is_offered_whenever_registration_is_open():
    src = _read("app", "accounts_views.py")
    assert "{'auth_options': {'signup': accounts.registration_open()," in src
    html = _read("app", "templates", "signup.html")
    assert "t('signup.not_ready')" in html


# --- Sagas ----------------------------------------------------------------------------

@pytest.fixture
def series_names(monkeypatch):
    names = {"Q1": {"en": "Persona"}, "Q2": {"en": "Persona 5"}, "Q3": {"en": "Dynasty Warriors"},
             "Q4": {"en": "Fire Emblem"}, "Q5": {"en": "The Legend of Zelda"}}
    monkeypatch.setattr(series, "load", lambda: {"series": names, "ids": {}, "names": {}})


def test_a_crossover_stays_in_the_series_its_name_carries(series_names):
    assert discover._own_series("Persona 5 Strikers", ["Q1", "Q2", "Q3"]) == ["Q1", "Q2"]
    assert discover._own_series("Fire Emblem Warriors", ["Q4", "Q3"]) == ["Q4"]
    # No name carries a whole series name: Wikidata's word stands.
    assert discover._own_series("Hyrule Warriors", ["Q5", "Q3"]) == ["Q5", "Q3"]
    assert discover._own_series("Dynasty Warriors 9 Empires", ["Q3"]) == ["Q3"]


def test_the_same_game_from_another_region_counts_once():
    titles = {
        "A": {"name": "The Elder Scrolls V: Skyrim", "date": "20171117"},
        "B": {"name": "The Elder Scrolls V: Skyrim®", "date": "20171117"},
        "C": {"name": "The Elder Scrolls: Blades", "date": "20200514"},
    }
    assert sorted(discover._one_per_game(["A", "B", "C"], titles, {"B"})) == ["B", "C"]
    assert sorted(discover._one_per_game(["A", "B", "C"], titles, set())) == ["A", "C"]


def test_the_sagas_page_has_a_search_tabs_and_full_cards():
    html = _read("app", "templates", "sagas.html")
    for needle in ('id="sagasSearch"', 'data-saga-tab="incomplete"', 'data-saga-tab="complete"'):
        assert needle in html, needle
    js = _read("app", "static", "js", "sagas.js")
    assert "function sagaCard(" in js and "saga-card__strip" in js and "I18N.view" in js
    src = _read("app", "discover.py")
    assert "'cover':" in src and "'games':" in src

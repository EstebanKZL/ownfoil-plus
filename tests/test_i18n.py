"""app/i18n.py: t() must never crash or blank out on a missing translation, and the
language switcher must correctly persist and apply the person's choice via a cookie.
"""
import pytest

import i18n
from app import create_app
from db import init_db


@pytest.fixture
def client(tmp_path):
    app = create_app(f"sqlite:///{tmp_path/'test.db'}")
    init_db(app)
    return app.test_client()


def test_t_returns_english_by_default(client):
    resp = client.get("/login")
    html = resp.get_data(as_text=True)
    assert "Please login to your account" in html


def test_t_returns_spanish_once_the_cookie_is_set(client):
    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/login")
    html = resp.get_data(as_text=True)
    assert "Iniciá sesión en tu cuenta" in html
    assert "Please login to your account" not in html


def test_set_language_route_sets_a_persistent_cookie(client):
    resp = client.get("/set-language/es", headers={"Referer": "/login"})
    assert resp.status_code == 302
    assert "ownfoil_lang=es" in resp.headers.get("Set-Cookie", "")


def test_set_language_redirects_back_to_the_referring_page(client):
    resp = client.get("/set-language/es", headers={"Referer": "/admin/settings"})
    assert resp.headers["Location"] == "/admin/settings"


def test_set_language_with_no_referrer_falls_back_to_home(client):
    resp = client.get("/set-language/es")
    assert resp.headers["Location"] == "/"


def test_an_unsupported_language_code_falls_back_to_the_default(client):
    resp = client.get("/set-language/fr", headers={"Referer": "/login"})
    assert "ownfoil_lang=en" in resp.headers.get("Set-Cookie", "")


def test_a_garbled_cookie_value_falls_back_to_english_rather_than_crashing(client):
    client.set_cookie("ownfoil_lang", "not-a-real-language")
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Please login to your account" in resp.get_data(as_text=True)


# --- t() unit behavior (no request context needed for these) ----------------------

def test_t_falls_back_to_the_raw_key_for_an_unknown_key(client):
    with client.application.test_request_context("/"):
        assert i18n.t("some.key.nobody.translated") == "some.key.nobody.translated"


def test_t_falls_back_to_english_when_a_language_is_missing_from_an_entry(client, monkeypatch):
    monkeypatch.setitem(i18n.TRANSLATIONS, "partial.key", {"en": "English only"})
    with client.application.test_request_context("/"):
        client.set_cookie("ownfoil_lang", "es")
        with client.application.test_request_context("/", headers={"Cookie": "ownfoil_lang=es"}):
            assert i18n.t("partial.key") == "English only"


def test_t_formats_kwargs_when_provided():
    assert i18n.t("Hello {name}", name="World") == "Hello World"


def test_every_translation_entry_has_both_supported_languages():
    """A key missing one language silently falls back to English for that language,
    which is a legitimate incremental state - but flag it here so gaps are visible
    and intentional rather than accidental."""
    incomplete = {
        key for key, langs in i18n.TRANSLATIONS.items()
        if not set(i18n.SUPPORTED_LANGUAGES).issubset(langs)
    }
    assert incomplete == set(), f"Missing a language for: {incomplete}"

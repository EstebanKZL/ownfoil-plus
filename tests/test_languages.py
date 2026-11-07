"""The web UI in more languages: English and Spanish in i18n.py, the rest in
app/locales/<code>.json, an "Automatic" choice that follows the browser, and each
language listed by its own name."""
import json
import os
import re

import pytest

import i18n

LOCALES = os.path.join(os.path.dirname(__file__), "..", "app", "locales")
PLACEHOLDER = re.compile(r"\{[a-zA-Z_]*\}")
TAG = re.compile(r"</?[a-zA-Z][^>]*>")


def test_the_languages_on_offer():
    assert i18n.SUPPORTED_LANGUAGES == ('en', 'es', 'fr', 'de', 'it', 'pt', 'nl', 'ru', 'ja', 'ko', 'zh')
    assert set(i18n.LANGUAGE_NAMES) == set(i18n.SUPPORTED_LANGUAGES)
    assert i18n.LANGUAGE_NAMES['ja'] == '日本語' and i18n.LANGUAGE_NAMES['zh'] == '简体中文'


@pytest.mark.parametrize("lang", [l for l in i18n.SUPPORTED_LANGUAGES if l not in ('en', 'es')])
def test_each_locale_file_matches_english(lang):
    path = os.path.join(LOCALES, f"{lang}.json")
    if not os.path.exists(path):
        pytest.skip(f"{lang}.json not written yet: English stands in")
    with open(path, encoding="utf-8") as f:
        texts = json.load(f)
    english = {k: v["en"] for k, v in i18n.TRANSLATIONS.items()}
    assert not set(texts) - set(english), "keys English no longer has"
    for key, text in texts.items():
        assert isinstance(text, str) and text.strip(), key
        # {name} placeholders filled by str.format, and markup rendered with |safe.
        assert sorted(PLACEHOLDER.findall(text)) == sorted(PLACEHOLDER.findall(english[key])), key
        assert sorted(TAG.findall(text)) == sorted(TAG.findall(english[key])), key


@pytest.mark.parametrize("header, expected", [
    (None, "en"), ("", "en"), ("fr-FR,fr;q=0.9,en;q=0.8", "fr"), ("pt-BR", "pt"),
    ("zh-Hans-CN,zh;q=0.9", "zh"), ("sv-SE,de;q=0.7,en;q=0.5", "de"),
    ("en;q=0.4,ja;q=0.8", "ja"), ("xx", "en"), ("es;q=0", "en"),
])
def test_automatic_follows_the_browser(header, expected):
    assert i18n.browser_language(header) == expected


def test_automatic_is_the_default_and_can_be_chosen(shop_app):
    client = shop_app.app.test_client()
    html = client.get("/login", headers={"Accept-Language": "de-DE,de;q=0.9"}).get_data(as_text=True)
    assert '<html lang="de"' in html
    resp = client.get("/set-language/ja")
    assert "ownfoil_lang=ja" in resp.headers["Set-Cookie"]
    resp = client.get("/set-language/auto")
    assert "ownfoil_lang=auto" in resp.headers["Set-Cookie"]
    html = client.get("/login", headers={"Accept-Language": "ko"}).get_data(as_text=True)
    assert '<html lang="ko"' in html


def test_the_menu_lists_automatic_and_each_language_by_its_own_name():
    nav = open(os.path.join(os.path.dirname(__file__), "..", "app", "templates", "nav.html"),
               encoding="utf-8").read()
    assert "/set-language/auto" in nav and "t('language.auto')" in nav
    assert "LANGUAGE_NAMES[lang]" in nav

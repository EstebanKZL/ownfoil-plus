"""Stage 2 design: the Library page (templates/index.html + static/js/library.js) -
header and tiles, toolbar with sorting, filter pills with exact counts, cards, empty and
error states. Markup and JS are checked as source; the shipped GraphQL queries run
against the real schema on a seeded library."""
import json
import os
import re

import fixture
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _library_js():
    return _read("app", "static", "js", "library.js")


def _extract_query(js_source, const_name):
    m = re.search(rf"const {const_name} = `(.*?)`;", js_source, re.DOTALL)
    assert m, f"{const_name} not found in library.js"
    return m.group(1)


@pytest.fixture
def client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    assert resp.status_code in (302, 303)
    return shop_app.client


# --- code structure ------------------------------------------------------------------

def test_library_logic_lives_in_its_own_script(client):
    html = client.get("/").get_data(as_text=True)
    assert "/static/js/library.js" in html
    assert "function loadPage" not in html
    assert "const I18N = {" in html
    js = client.get("/static/js/library.js").get_data(as_text=True)
    assert "function loadPage" in js and "const CARDS_QUERY" in js


def test_library_page_has_one_bare_inline_script(client):
    html = client.get("/").get_data(as_text=True)
    assert len(re.findall(r"<script>", html)) == 1

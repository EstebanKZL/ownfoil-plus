"""Stage 1 design system: tokens, the three color styles and the shared components.
Checked as the CSS/markup that produces them - the visual result is checked in a browser."""
import os
import re

import fixture
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STYLES = ("ownfoil", "neon", "joycon")


def _read(rel):
    with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8") as f:
        return f.read()


def _rule(css, selector):
    """The body of every rule whose selector list contains `selector`, concatenated."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    out = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = [s.strip() for s in match.group(1).split(",")]
        if selector in selectors:
            out.append(match.group(2))
    return "\n".join(out)


@pytest.fixture
def admin_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code == 302
    return shop_app.client


# --- tokens -------------------------------------------------------------------------

def test_every_style_defines_its_accents_in_both_modes():
    css = _read("app/static/css/tokens.css")
    for style in STYLES:
        for mode in ("dark", "light"):
            block = _rule(css, f'[data-style="{style}"][data-bs-theme="{mode}"]')
            for var in ("--op-nav:", "--op-action:", "--op-on-action:", "--op-glow-1:", "--op-glow-2:"):
                assert var in block, (style, mode, var)


def test_tokens_feed_bootstrap():
    css = _read("app/static/css/tokens.css")
    for var in ("--bs-primary:", "--bs-primary-rgb:", "--bs-body-bg:", "--bs-body-color:",
                "--bs-border-color:", "--bs-link-color:", "--bs-body-font-family:"):
        assert var in css, var
    # Bootstrap compiles the button colors as literals: they must be re-pointed.
    assert "var(--op-action)" in _rule(css, ".btn-primary")


def test_inter_is_vendored_and_declared(shop_app):
    css = _read("app/static/css/tokens.css")
    assert "@font-face" in css and "InterVariable.woff2" in css
    assert shop_app.client.get("/static/vendor/inter/InterVariable.woff2").status_code == 200


def test_tokens_load_between_bootstrap_and_style(shop_app):
    head = shop_app.client.get("/login").get_data(as_text=True).split("</head>", 1)[0]
    assert head.index("bootstrap.min.css") < head.index("css/tokens.css") < head.index("style.css")


def test_style_css_has_no_bootstrap_blue_literal():
    assert "#0d6efd" not in _read("app/static/style.css").lower()


def test_light_palette_lives_in_tokens_only():
    # style.css loads after tokens.css: a leftover light block there would win.
    assert not _rule(_read("app/static/style.css"), "[data-bs-theme=light]").strip()

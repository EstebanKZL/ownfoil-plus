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


# --- shared components ---------------------------------------------------------------

COMPONENTS = (".page-head", ".stat-tile", ".filter-pill", ".toolbar", ".surface",
              ".status-badge", ".empty-state")


def test_components_exist_and_use_tokens_only():
    css = _read("app/static/style.css")
    for cls in COMPONENTS:
        body = _rule(css, cls)
        assert body.strip(), cls
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", body), cls


def test_component_modifiers_use_the_semantic_colors():
    css = _read("app/static/style.css")
    for modifier, token in (("--ok", "--op-ok"), ("--wait", "--op-wait"), ("--nav", "--op-nav"),
                            ("--action", "--op-action")):
        assert token in _rule(css, ".stat-tile" + modifier), modifier
    for modifier, token in (("--ok", "--op-ok"), ("--wait", "--op-wait"), ("--fav", "--op-fav")):
        assert token in _rule(css, ".status-badge" + modifier), modifier


def test_content_type_colors_are_fixed_in_every_style():
    # What identifies a content type lives in the theme blocks only: a style may change
    # its accents, never the type colors (base coral, DLC cyan, firmware violet).
    css = _read("app/static/css/tokens.css")
    for mode in ("dark", "light"):
        block = _rule(css, f'[data-bs-theme="{mode}"]')
        for var in ("--op-base:", "--op-base-rgb:", "--op-dlc:", "--op-firmware:"):
            assert var in block, (mode, var)
    for style in STYLES:
        for mode in ("dark", "light"):
            block = _rule(css, f'[data-style="{style}"][data-bs-theme="{mode}"]')
            for var in ("--op-base", "--op-dlc", "--op-firmware"):
                assert var not in block, (style, mode, var)


def test_components_carry_the_content_type_colors():
    css = _read("app/static/style.css")
    for cls, token in ((".status-badge--dlc", "--op-dlc"),
                       (".stat-tile--base", "--op-base"), (".stat-tile--dlc", "--op-dlc"),
                       (".packing-kind--base", "--op-base"), (".packing-kind--fav", "--op-fav"),
                       (".game-row__icon--base", "--op-base"), (".game-row__icon--update", "--op-wait"),
                       (".game-row__icon--dlc", "--op-dlc"),
                       (".list-section-dot--base", "--op-base"), (".list-section-dot--update", "--op-wait"),
                       (".list-section-dot--dlc", "--op-dlc"),
                       (".files-chip--base", "--op-base"), (".files-chip--update", "--op-wait"),
                       (".files-chip--dlc", "--op-dlc"), (".files-chip--multi", "--op-fav")):
        assert token in _rule(css, cls), cls


def test_charts_use_the_same_colors_in_every_style():
    # A plain share is the info blue (not the style's accent); a bar that names a
    # content type wears its color, and Statistics' per-type rows carry their tone.
    css = _read("app/static/style.css")
    assert "var(--op-info)" in _rule(css, ".chart-bar__fill")
    assert "var(--op-info)" in _rule(css, ".dash-list__bar-fill")
    for cls, token in ((".chart-bar--base .chart-bar__fill", "--op-base"),
                       (".chart-bar--dlc .chart-bar__fill", "--op-dlc")):
        assert token in _rule(css, cls), cls
    js = _read("app/static/js/stats.js")
    assert "TYPE_TONES = {BASE: 'base', UPDATE: 'wait', DLC: 'dlc'}" in js


def test_reduced_motion_disables_component_transitions():
    css = _read("app/static/style.css")
    assert "prefers-reduced-motion: reduce" in css


def test_game_cards_share_the_surface_look():
    css = _read("app/static/style.css")
    assert "var(--op-card)" in _rule(css, ".game-surface")
    # The card gray is a token of its own, in both themes (never a literal).
    tokens = _read("app/static/css/tokens.css")
    for mode in ("dark", "light"):
        block = _rule(tokens, f'[data-bs-theme="{mode}"]')
        assert "--op-card:" in block, mode


def test_dashboard_uses_page_head_and_stat_tiles(admin_client):
    html = admin_client.get("/admin").get_data(as_text=True)
    js = admin_client.get("/static/js/dashboard.js").get_data(as_text=True)  # since stage 4
    assert 'class="page-head' in html and "stat-tile" in js
    assert 'id="dashTiles"' in html


# --- login, setup and offline pages -------------------------------------------------

def test_login_and_offline_use_the_surface_card(shop_app):
    anonymous = shop_app.app.test_client()
    for url in ("/login", "/offline"):
        html = anonymous.get(url).get_data(as_text=True)
        assert 'class="surface' in html and "logo/logo.svg" in html, url
    assert 'class="empty-state' in anonymous.get("/offline").get_data(as_text=True)


def test_setup_uses_page_head(admin_client):
    html = admin_client.get("/setup").get_data(as_text=True)
    assert 'class="page-head' in html


# --- found in the browser check -----------------------------------------------------

def test_page_head_glow_does_not_widen_the_page():
    # A glow wider than the header made phone pages scroll sideways.
    body = _rule(_read("app/static/style.css"), ".page-head::before")
    inset = re.search(r"inset: ([^;]+);", body).group(1).split()
    assert inset[1] == "0" and inset[3] == "0"


def test_appearance_picker_marks_the_chosen_style():
    css = _read("app/static/style.css")
    assert "var(--op-nav)" in _rule(css, ".btn-check:checked + .style-option")


def test_range_inputs_follow_the_style():
    css = _read("app/static/css/tokens.css")
    assert "var(--op-nav)" in _rule(css, ".form-range::-webkit-slider-thumb")


def test_offline_page_assets_are_precached(shop_app):
    js = shop_app.client.get("/sw.js").get_data(as_text=True)
    assert "css/tokens.css" in js and "vendor/inter/InterVariable.woff2" in js


def _lum(hex_color):
    def chan(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    h = hex_color.lstrip("#")
    r, g, b = (chan(h[i:i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _var(block, name):
    return re.search(re.escape(name) + r":\s*(#[0-9a-fA-F]{6})", block).group(1)


def test_text_on_accent_colors_is_at_least_4_5_to_1():
    # The CHANGELOG promises AA contrast for text on the accents in all six combinations,
    # hover included; and the amber count badge carries text too.
    css = _read("app/static/css/tokens.css")
    for style in STYLES:
        for mode in ("dark", "light"):
            block = _rule(css, f'[data-style="{style}"][data-bs-theme="{mode}"]')
            on = _var(block, "--op-on-action")
            for name in ("--op-action", "--op-action-hover"):
                assert _contrast(on, _var(block, name)) >= 4.5, (style, mode, name)
    for mode in ("dark", "light"):
        block = _rule(css, f'[data-bs-theme="{mode}"]')
        assert _contrast(_var(block, "--op-on-wait"), _var(block, "--op-wait")) >= 4.5, mode

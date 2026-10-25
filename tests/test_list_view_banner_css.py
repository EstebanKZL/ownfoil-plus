"""Regression guard for a real visual bug: the List view's per-card banner image
(.list-banner-strip, absolutely positioned, sits behind everything) was completely
invisible because its sibling .list-card-body - a normal-flow block that spans the
card's whole height and contains all the actual content - had an *opaque*
background-color. An opaque background-color on that element blends with (and
therefore masks) anything behind it in stacking order, including a translucent
background-image gradient on the very same element, no matter how the banner element
itself is sized. The fix moved the readability gradient onto .list-card-body's own
background-image (translucent, reaching full opacity only ~420px down) and dropped
its background-color entirely - a background-color reappearing here, even as a
"safety fallback", reintroduces the exact bug.
"""
import os
import re


def _read_css():
    css_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "style.css")
    with open(css_path) as f:
        return f.read()


def _rule_body(css, selector):
    m = re.search(rf"{re.escape(selector)}\s*\{{(.*?)\}}", css, re.DOTALL)
    assert m, f"{selector} not found in style.css"
    # Strip CSS comments so words like "background-color" appearing only in an
    # explanatory comment don't produce a false positive.
    return re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.DOTALL)


def test_list_card_body_has_no_opaque_background_color():
    css = _read_css()
    rule = _rule_body(css, ".list-card-body")
    assert "background-color" not in rule, (
        "An opaque background-color on .list-card-body masks the banner on the "
        ".list-banner-strip sibling behind it - see this test's module docstring."
    )


def test_list_card_body_still_has_the_translucent_readability_gradient():
    """The fix's other half: the fade itself must still be present, just via
    background-image (which can be translucent and let the banner through) rather
    than an opaque background-color."""
    css = _read_css()
    rule = _rule_body(css, ".list-card-body")
    assert "background-image" in rule
    assert "linear-gradient" in rule
    # Translucent near the top (banner visible), fully opaque well before it, so a
    # long expanded list is never left with a washed-out background deep in its rows.
    assert re.search(r"rgba\([^)]*,\s*\.\d+\)", rule), "expected a translucent rgba() stop"
    assert re.search(r"rgba\([^)]*,\s*1\)", rule), "expected a fully-opaque rgba() stop"


def test_list_banner_strip_covers_the_whole_card_not_a_fixed_height():
    """The other requested behavior: stretched behind the whole (growing) card, not
    capped at a fixed pixel height like the version this replaced."""
    css = _read_css()
    rule = _rule_body(css, ".list-banner-strip")
    assert "position: absolute" in rule
    assert "inset: 0" in rule
    assert "height:" not in rule, "a fixed height would cap the banner instead of covering the whole card"

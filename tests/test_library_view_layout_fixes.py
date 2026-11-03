"""Coverage for Library-page layout fixes, all requested directly from
screenshots of the filter dropdown, the List view, and the Card view:

1. Hovering a single button inside the filter dropdown (Tipo/Posesión/Actualización/
   Completitud, and the health filter) lit up the *entire* row, not just the button
   under the cursor - Bootstrap's own .dropdown-item:hover paints a grey background
   behind the whole row that wraps those buttons. Fixed by tagging those specific
   wrapper rows with .filter-group-item and turning that background off for them only
   (the per-button highlight from .btn-outline-primary's own hover/checked state,
   already correct, still works).
2. In the List view, the divider line above the base-game row only ever showed up
   when a title also had Updates/DLC rows beneath it - really Bootstrap's
   list-group-flush border *between* items, never visible with just one row. Fixed by
   restoring the first row's top border specifically on the outer list
   (.list-top-group), not the nested Updates/DLC sub-lists.
3. (Removed in 6.2.5.47.) The Card view's badge overlay and its @container fix went
   away with the stage 2 cards, which keep their badges outside the artwork.
"""
import os
import re

import fixture
import pytest


CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "app", "static", "style.css")


def _read_css():
    with open(CSS_PATH) as f:
        return f.read()


@pytest.fixture
def client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


# --- 1. Filter dropdown rows should only highlight the hovered button --------------

def test_every_filter_groups_wrapper_div_is_tagged_filter_group_item(client):
    html = client.get("/").get_data(as_text=True)
    # Type, Ownership, Update and Completion filters (inside #filterDropdownBtn's menu)...
    for aria_label in ("Type filter", "Ownership filter", "Update filter", "Completion filter"):
        # the wrapping dropdown-item sits directly above the aria-labelled btn-group
        assert re.search(
            r'<div class="dropdown-item filter-group-item">\s*<div class="btn-group[^"]*" role="group" aria-label="%s"'
            % re.escape(aria_label),
            html,
        ), f"filter-group-item wrapper not found above the {aria_label!r} btn-group"
    # ...and the library health filter (#listHealthDropdownBtn's menu).
    assert re.search(
        r'<div class="dropdown-item filter-group-item">\s*<div class="btn-group-vertical w-100" role="group" aria-label="Library health filter"',
        html,
    )


def test_the_items_per_page_custom_input_row_is_not_tagged(client):
    """Only the radio-button filter rows get the class - the custom items-per-page
    input is a real interactive dropdown row and should keep Bootstrap's normal
    hover/focus feedback."""
    html = client.get("/").get_data(as_text=True)
    # Whitespace-agnostic: the row moved into the View menu in stage 2.
    assert re.search(r'<div class="dropdown-item">\s*<input type="number" id="customItemsPerPage"', html)


def test_filter_group_item_hover_and_focus_have_no_background(client):
    css = _read_css()
    m = re.search(r"\.filter-group-item:hover,\s*\.filter-group-item:focus\s*\{(.*?)\}", css, re.DOTALL)
    assert m, ".filter-group-item:hover/:focus rule not found in style.css"
    assert re.search(r"background-color:\s*transparent", m.group(1))


# --- 2. List view: the base-game row always gets its divider line ------------------

def test_the_outer_list_group_is_tagged_list_top_group_but_nested_sections_are_not(client):
    html = client.get("/static/js/library.js").get_data(as_text=True)  # the page logic, since stage 2
    assert 'list-group list-group-flush list-top-group mt-3' in html
    # The nested Updates/DLC/"older versions" sub-lists must NOT carry the new class -
    # they keep Bootstrap's normal border-between-items behavior.
    assert "list-group list-group-flush list-top-group mt-1" not in html
    assert "list-group list-group-flush mt-1" in html


def test_css_rule_only_targets_the_top_level_list_not_every_list_group_flush(client):
    css = _read_css()
    m = re.search(
        r"\.list-top-group\.list-group-flush > \.list-group-item:first-child\s*\{(.*?)\}",
        css, re.DOTALL,
    )
    assert m, "expected a .list-top-group.list-group-flush > .list-group-item:first-child rule"
    assert "border-top-width" in m.group(1)
    # Making sure this doesn't regress into the broader (and wrong) selector that
    # would also restore the border on every nested Updates/DLC section.
    assert ".list-game-card .list-group-flush > .list-group-item:first-child {" not in css

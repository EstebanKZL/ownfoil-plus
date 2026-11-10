"""Saves, redesigned (asked for): one row a game - its icon, name and totals fixed on the
left, its backups as blocks in a strip to the right, the newest first, scrolling
sideways when they don't fit (a server keeping every backup made a column that never
ended). Clicking a block downloads it; its bin shows on hover or focus (always on touch
screens). The games go by pages with the shared pager."""
import os
import re

import i18n

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _function(js, name):
    start = js.index(f"function {name}(")
    depth, i = 0, js.index("{", js.index(")", start))
    while True:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        i += 1
        if depth == 0:
            return js[start:i]


def _rule(css, selector):
    return re.search(rf"(?:^|\n){re.escape(selector)} \{{([^}}]*)\}}", css).group(1)


def test_a_game_is_one_row_with_its_backups_in_a_strip():
    js = _read("app", "static", "js", "saves.js")
    card = _function(js, "gameCard")
    assert "saves-game__info" in card and "saves-strip" in card
    tile = _function(js, "backupTile")
    # The block is the download; the bin is its own button, outside the link.
    assert "'a', 'saves-tile__main'" in tile and "download.href = '/api/saves/download?'" in tile
    assert "'button', 'saves-tile__remove" in tile
    # The newest first (the API sends them so) and marked.
    assert "index === 0" in tile and "I18N.newest" in tile
    assert "backupRow" not in js


def test_the_strip_scrolls_sideways_and_the_row_stacks_on_phones():
    css = _read("app", "static", "style.css")
    game = _rule(css, ".saves-game")
    assert "grid-template-columns" in game
    strip = _rule(css, ".saves-strip")
    assert "overflow-x: auto" in strip and "flex-wrap: nowrap" in strip
    assert "scroll-snap-type" in strip
    remove = _rule(css, ".saves-tile__remove")
    assert "opacity: 0" in remove
    assert ".saves-tile:hover .saves-tile__remove" in css and ".saves-tile:focus-within .saves-tile__remove" in css
    assert "@media (hover: none)" in css[css.index(".saves-tile__remove"):]


def test_the_games_go_by_pages():
    js = _read("app", "static", "js", "saves.js")
    assert "Pager.perPage('saves', SAVES_SIZES, 10)" in js
    assert "Pager.render(document.getElementById('savesPager')" in _function(js, "renderSaves")
    assert '<div id="savesPager"' in _read("app", "templates", "saves.html")


def test_the_new_strings_exist():
    assert i18n.TRANSLATIONS["saves.newest"]["es"] == "Más reciente"
    html = _read("app", "templates", "saves.html")
    assert "newest: {{ t('saves.newest') | tojson }}" in html

"""One pager for every paged list (static/js/pager.js), Switch Library Manager style -
asked for: "Mostrando 1-24 de 42" on the left, the pages in the middle, "Por página" on
the right, each page remembering its own choice in the browser."""
import os
import re

import i18n

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _js(name):
    return _read("app", "static", "js", name)


def _function(js, name):
    start = js.index(f"function {name}(")
    depth, i = 0, js.index("{", js.index(")", start))
    while True:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        i += 1
        if depth == 0:
            return js[start:i]


def test_every_page_gets_the_pager_and_its_strings():
    base = _read("app", "templates", "base.html")
    head = base[:base.index("</head>")]
    assert "js/pager.js" in head
    block = base[base.index('id="pagerI18n"'):][:600]
    for key in ("showing", "perPage", "previous", "next", "pages"):
        assert f"'{key}'" in block, key
    for key in ("pager.showing", "pager.per_page", "pager.pages"):
        assert key in i18n.TRANSLATIONS
    assert "{first}" in i18n.TRANSLATIONS["pager.showing"]["es"]
    assert i18n.TRANSLATIONS["pager.showing"]["es"].startswith("Mostrando")
    assert i18n.TRANSLATIONS["pager.per_page"]["es"] == "Por página"


def test_the_bar_has_its_three_parts():
    js = _js("pager.js")
    render = _function(js, "render")
    for part in ("op-pager__range", "op-pager__pages", "op-pager__size", "op-pager__select"):
        assert part in render, part
    assert "container.hidden = total === 0" in render
    assert "localStorage" in _function(js, "perPage")
    css = _read("app", "static", "style.css")
    assert re.search(r"\.op-pager \{[^}]*grid-template-columns", css)


def test_the_library_uses_it_top_and_bottom():
    js = _js("library.js")
    body = _function(js, "updatePaginationControls")
    assert "Pager.render(" in body and "pageSizeOptions(" in body
    assert "paginationControlsTop" in body and "paginationControlsBottom" in body
    html = _read("app", "templates", "index.html")
    assert '<div id="paginationControlsTop"' in html and '<div id="paginationControlsBottom"' in html
    assert '<ul class="pagination' not in html


def test_sagas_use_it():
    js = _js("sagas.js")
    assert "renderSagaPager" not in js
    assert "Pager.perPage('sagas', SAGA_SIZES, 24)" in js and "Pager.render(" in js
    assert "SAGA_SIZES = [12, 24, 48, 96]" in js
    assert '<div id="sagasPager"' in _read("app", "templates", "sagas.html")


def test_all_files_use_it_at_the_bottom():
    js = _js("files.js")
    pager = _function(js, "renderPager")
    assert "Pager.render(document.getElementById('filesPages')" in pager
    assert "pageSize: ${PAGE_SIZE}" not in js and "$pageSize: Int!" in js
    assert 'id="filesPages"' in _read("app", "templates", "files.html")


def test_compress_and_combine_use_it_at_the_bottom():
    js = _js("packing.js")
    assert "Pager.render(" in js and "Pager.perPage('packing'" in js
    render = _function(js, "render")
    assert "pagesBar(kind, shown.length)" in render


def test_the_users_list_uses_it():
    js = _js("settings.js")
    assert "Pager.render(document.getElementById('userPager')" in js
    assert "#userPrev" not in js and "usersPage:" not in _read("app", "templates", "settings.html")
    assert "users.page" not in i18n.TRANSLATIONS

"""Files keeps each tab's rows until the files change (app/files_events.py and
static/js/files.js).

Asked for: a file cleaned in Duplicates still showed in All files until a page reload,
and every tab reloaded on entering it even when nothing had changed. The server
publishes a signature of the files table on the realtime feed; when it moves, the open
tab and the tiles follow, and every other tab reloads the next time it is entered - and
only then.
"""
import datetime
import os
import re

import fixture
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _function_body(js, name):
    start = js.index(f"function {name}(")
    depth, i = 0, js.index(") {", start) + 2
    while True:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        i += 1
        if depth == 0:
            return js[start:i]


@pytest.fixture
def files_env(shop_app):
    import files_events
    from db import Files, Libraries, db
    with shop_app.app.app_context():
        lib = Libraries.query.first()
        if lib is None:
            lib = Libraries(path="/games")
            db.session.add(lib)
            db.session.commit()
        files_events._state = None
        yield types_ns(app=shop_app.app, lib_id=lib.id, Files=Files, db=db, events=files_events)


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


def _add(env, name, **extra):
    f = env.Files(library_id=env.lib_id, filepath=f"/games/{name}", filename=name, extension="nsp",
                  size=100, **extra)
    env.db.session.add(f)
    env.db.session.commit()
    return f


# --- the server's signature -------------------------------------------------------------------

def test_the_signature_moves_with_every_kind_of_change(files_env):
    sig = files_env.events.signature
    start = sig()
    assert sig() == start                                   # nothing changed: the same
    f = _add(files_env, "A.nsp")
    added = sig()
    assert added != start
    f.verified_at = datetime.datetime(2026, 11, 10, 10, 0)
    f.hash_valid = True
    files_env.db.session.commit()
    verified = sig()
    assert verified != added
    f.filepath, f.filename = "/games/Renamed/A.nsp", "A.nsp"
    files_env.db.session.commit()
    moved = sig()
    assert moved != verified
    f.extension, f.compressed, f.size = "nsz", True, 60
    files_env.db.session.commit()
    compressed = sig()
    assert compressed != moved
    files_env.db.session.delete(f)
    files_env.db.session.commit()
    assert sig() not in (compressed, moved)


def test_the_topic_tells_only_when_the_files_changed(files_env):
    ev = files_env.events
    first = ev.files_snapshot()
    assert first and first[0]["revision"]
    ev.files_poll()                                        # the poller's first read settles it
    assert ev.files_poll() == []                           # nothing new since
    _add(files_env, "B.nsp")
    events = ev.files_poll()
    assert len(events) == 1 and events[0][0] == "update" and events[0][1]["revision"] != first[0]["revision"]
    assert ev.files_poll() == []


def test_a_page_connecting_never_swallows_a_change_for_another(files_env):
    ev = files_env.events
    ev.files_poll()
    _add(files_env, "C.nsp")
    ev.files_snapshot()                                    # a second page connects meanwhile
    assert len(ev.files_poll()) == 1                       # the first page is still told


def test_the_topic_is_for_the_admin_pages_and_read_calmly():
    import realtime
    import files_events  # noqa: F401 - registers the topic
    topic = realtime.TOPICS["files"]
    assert topic.access == "admin"
    assert topic.delay() >= 2


# --- the page -------------------------------------------------------------------------------------

def test_the_page_follows_the_feed(shop_app):
    client = shop_app.client
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    html = client.get("/admin/files").get_data(as_text=True)
    assert html.index("/static/js/realtime.js") < html.index("/static/js/files.js")
    js = _read("app", "static", "js", "files.js")
    assert "new Realtime(['files'])" in js
    changed = _function_body(js, "filesChanged")
    assert "markStale(current)" in changed and "loadStats()" in changed


def test_a_tab_reloads_on_entering_only_when_stale():
    js = _read("app", "static", "js", "files.js")
    stale = _function_body(js, "markStale")
    assert "rows = null" in stale and "packingStale" in stale
    load = _function_body(js, "loadTab")
    assert "Packing.load(kind, force || packingStale[kind])" in load


def test_an_action_here_marks_every_other_tab_at_once():
    js = _read("app", "static", "js", "files.js")
    for name in ("deleteOneCopy", "cleanOneFile", "runRemoval", "checkWatched"):
        assert "markStale(current)" in _function_body(js, name), name
    # The tiles' figures are asked once per change, not on a timer per call.
    assert "setInterval" not in _function_body(js, "loadStats")

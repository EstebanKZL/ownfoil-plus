"""Resumable web uploads (Files page): start/resume, chunk appends, finishing into the
library, refusals, and the API around them."""
import datetime
import json
import os

import fixture
import pytest

import uploads


@pytest.fixture(autouse=True)
def session_dir(tmp_path, monkeypatch):
    path = tmp_path / "upload-sessions"
    monkeypatch.setattr(uploads, "SESSION_DIR", str(path))
    return path


@pytest.fixture
def library(shop_app):
    """The fixture library, registered as a library path in settings."""
    from settings import settings_transaction
    with settings_transaction() as settings:
        settings['library']['paths'] = [shop_app.library_root]
    return shop_app.library_root


@pytest.fixture
def admin_client(shop_app, library):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code == 302
    return shop_app.client


@pytest.fixture
def queued(monkeypatch):
    import tasks
    got = []
    monkeypatch.setattr(tasks, "enqueue_task", lambda name, data=None, **k: got.append((name, data)))
    return got


NAME = "New Game [0100000000050000][v0].nsp"
DATA = os.urandom(300_000)


def _start(client, library, name=NAME, size=len(DATA)):
    return client.post("/api/uploads", json={"library": library, "filename": name, "size": size})


def _chunk(client, upload_id, offset, data):
    return client.patch(f"/api/uploads/{upload_id}", data=data,
                        headers={"Upload-Offset": str(offset), "Content-Type": "application/offset+octet-stream"})


# --- the module ---------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Game [0100000000010000][v0].nsp", "Game [0100000000010000][v0].nsp"),
    ("../../etc/Game.nsp", "Game.nsp"),
    ("C:\\Users\\me\\Pokémon: Edición.XCI", "Pokémon Edición.XCI"),
    ("  .hidden.nsz  ", "hidden.nsz"),
])
def test_sanitize_keeps_brackets_and_unicode(raw, expected):
    assert uploads.sanitize_filename(raw) == expected


@pytest.mark.parametrize("raw", ["", "..", "notes.txt", "game", "game.nsp.part"])
def test_sanitize_rejects(raw):
    with pytest.raises(uploads.UploadError):
        uploads.sanitize_filename(raw)


def test_partial_file_is_hidden_from_scans(library):
    state = uploads.start(library, NAME, 10, [library])
    partial = [n for n in os.listdir(library) if n.endswith(".part")]
    assert len(partial) == 1 and partial[0].startswith(".")
    from constants import ALLOWED_EXTENSIONS
    assert not any(partial[0].endswith(ext) for ext in ALLOWED_EXTENSIONS)
    uploads.cancel(state["id"])
    assert not [n for n in os.listdir(library) if n.endswith(".part")]


# --- API: full flow ------------------------------------------------------------------

def test_chunked_upload_lands_in_the_library_and_is_queued(admin_client, library, queued):
    body = _start(admin_client, library).get_json()
    assert body["success"] and body["offset"] == 0
    upload_id = body["id"]

    for start in range(0, len(DATA), 100_000):
        resp = _chunk(admin_client, upload_id, start, DATA[start:start + 100_000]).get_json()
        assert resp["success"] and resp["offset"] == min(start + 100_000, len(DATA))

    assert resp["finished"] is True
    final = os.path.join(library, NAME)
    with open(final, "rb") as f:
        assert f.read() == DATA
    assert ("add_file", {"library_path": library, "filepath": final}) in queued
    assert not [n for n in os.listdir(library) if n.endswith(".part")]
    assert admin_client.get("/api/uploads").get_json()["uploads"] == []


def test_starting_again_resumes_from_what_the_server_has(admin_client, library, queued):
    upload_id = _start(admin_client, library).get_json()["id"]
    _chunk(admin_client, upload_id, 0, DATA[:120_000])

    again = _start(admin_client, library).get_json()
    assert again["id"] == upload_id and again["offset"] == 120_000
    listed = admin_client.get("/api/uploads").get_json()["uploads"]
    assert [(u["filename"], u["offset"]) for u in listed] == [(NAME, 120_000)]

    assert _chunk(admin_client, upload_id, 120_000, DATA[120_000:]).get_json()["finished"]


def test_wrong_offset_reports_the_real_one(admin_client, library):
    upload_id = _start(admin_client, library).get_json()["id"]
    _chunk(admin_client, upload_id, 0, DATA[:50_000])
    resp = _chunk(admin_client, upload_id, 0, DATA[:50_000])
    assert resp.status_code == 409
    assert resp.get_json() == {"success": False, "error": "offset_mismatch",
                               "message": "Offset does not match", "offset": 50_000}


def test_more_data_than_declared_is_refused(admin_client, library):
    upload_id = _start(admin_client, library, size=10).get_json()["id"]
    assert _chunk(admin_client, upload_id, 0, b"x" * 11).status_code == 400


def test_missing_offset_header_is_refused(admin_client, library):
    upload_id = _start(admin_client, library).get_json()["id"]
    assert admin_client.patch(f"/api/uploads/{upload_id}", data=b"abc").status_code == 400


def test_cancel_removes_the_partial(admin_client, library):
    upload_id = _start(admin_client, library).get_json()["id"]
    _chunk(admin_client, upload_id, 0, DATA[:1000])
    assert admin_client.delete(f"/api/uploads/{upload_id}").get_json()["success"]
    assert admin_client.get(f"/api/uploads/{upload_id}").status_code == 404
    assert not [n for n in os.listdir(library) if n.endswith(".part")]


# --- API: refusals ---------------------------------------------------------------------

def test_existing_file_is_refused(admin_client, library):
    open(os.path.join(library, "Taken.nsp"), "wb").close()
    resp = _start(admin_client, library, name="Taken.nsp")
    assert resp.status_code == 409 and resp.get_json()["error"] == "exists"


def test_unknown_library_is_refused(admin_client, tmp_path):
    resp = _start(admin_client, str(tmp_path))
    assert resp.status_code == 400 and resp.get_json()["error"] == "bad_library"


def test_wrong_extension_is_refused(admin_client, library):
    assert _start(admin_client, library, name="readme.txt").get_json()["error"] == "bad_extension"


def test_not_enough_space_is_refused(admin_client, library, monkeypatch):
    import collections
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(uploads.shutil, "disk_usage", lambda path: usage(100, 90, 10))
    resp = _start(admin_client, library, size=1000)
    assert resp.status_code == 507 and resp.get_json()["error"] == "no_space"


def test_uploads_are_admin_only(shop_app, library):
    shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    assert shop_app.client.get("/api/uploads").status_code == 403
    assert _start(shop_app.client, library).status_code == 403


def test_unknown_or_malformed_ids_are_404(admin_client):
    assert admin_client.get("/api/uploads/ffffffffffffffffffffffffffffffff").status_code == 404
    assert admin_client.delete("/api/uploads/not-hex").status_code == 404


# --- cleanup ---------------------------------------------------------------------------

def test_abandoned_uploads_are_cleaned_up(library, session_dir):
    old = uploads.start(library, "Old.nsp", 10, [library])
    fresh = uploads.start(library, "Fresh.nsp", 10, [library])
    path = session_dir / f"{old['id']}.json"
    session = json.loads(path.read_text())
    session["touched"] = (datetime.datetime.now() - datetime.timedelta(days=8)).isoformat()
    path.write_text(json.dumps(session))

    assert uploads.cleanup_stale() == 1
    assert [s["id"] for s in uploads.list_sessions()] == [fresh["id"]]


def test_files_page_has_the_upload_dialog(admin_client):
    html = admin_client.get("/admin/files").get_data(as_text=True)
    assert 'id="uploadModal"' in html and 'id="uploadDrop"' in html

"""Update versions from more sources than the TitleDB release (app/titledb/extra_versions.py).

blawar/titledb - what the TitleDB release is built from - goes weeks without changes, and
then new updates go unseen. borntohonk/titledb's versions.json and 16BitWonder's
nx-versions (with its changelog for the dates) add the versions they know; the release's
own stay first. The same sources and checks as Switch Library Manager Web.
"""
import json
import os
import sqlite3
import types

import pytest

import titledb
from titledb import extra_versions
from titledb import update as update_mod

GAME = "0100AAAA00010000"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# --- reading each source -------------------------------------------------------------------

def test_nx_versions_gives_each_update_under_its_game(tmp_path):
    versions = tmp_path / "nx-versions.txt"
    changelog = tmp_path / "nx-changelog.md"
    _write(str(versions), "id|version\n"
                          "0100AAAA00010800|196608\n"      # an update: kept under its game
                          "0100AAAA00011001|65536\n"       # a DLC: left to the catalogue
                          "0100AAAA00011800|65536\n"       # a DLC whose index is 0x800: not an update
                          "0100BBBB00010800|12345\n"       # not a multiple of 0x10000
                          "garbage line\n")
    _write(str(changelog), "## 2026-10-29 17:24\n```\n[0100AAAA00010800][v131072]->[v196608]\n```\n"
                           "## 2026-10-01 10:00\n```\n[0100AAAA00010800][v196608]\n```\n")
    got = extra_versions.read_nx_versions(str(versions), str(changelog))
    # The oldest day a version was listed is its date.
    assert got == {GAME: {196608: "2026-10-01"}}


def test_a_versions_txt_must_look_like_one(tmp_path):
    path = tmp_path / "nx-versions.txt"
    _write(str(path), "<html>rate limited</html>")
    with pytest.raises(ValueError):
        extra_versions.read_nx_versions(str(path), None)


def test_another_versions_json_is_checked(tmp_path):
    path = tmp_path / "borntohonk.versions.json"
    _write(str(path), json.dumps({
        GAME: {"65536": "2026-01-02", "70000": "2026-01-03", "131072": "not a date"},
        "not-an-id": {"65536": "2026-01-02"},
    }))
    assert extra_versions.read_versions(str(path)) == {GAME: {65536: "2026-01-02", 131072: None}}


# --- into titles.db ---------------------------------------------------------------------------

@pytest.fixture
def built(tmp_path, monkeypatch):
    """titles.db built from a release whose versions.json stops at v65536, with the
    extra sources knowing v131072 (borntohonk) and v196608 (nx-versions)."""
    config = tmp_path / "config"
    config.mkdir()
    titles_dir = tmp_path / "titledb"
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    _write(str(titles_dir / "titles.US.en.json"), json.dumps({GAME: {"id": GAME, "name": "Game"}}))
    _write(str(titles_dir / "cnmts.json"), "{}")
    _write(str(titles_dir / "versions.json"), json.dumps({GAME.lower(): {"65536": "2026-01-01"}}))
    extra = titles_dir / "extra"
    _write(str(extra / "borntohonk.versions.json"),
           json.dumps({GAME: {"65536": "2025-12-31", "131072": "2026-02-01"}}))
    _write(str(extra / "nx-versions.txt"), "id|version\n0100AAAA00010800|196608\n")
    titledb.store.create_titledb(str(config / "titles.db"))
    titledb.store.import_from_json(str(titles_dir / "titles.US.en.json"), "US.en")
    with sqlite3.connect(str(config / "titles.db")) as conn:
        return dict(conn.execute("SELECT version, release_date FROM versions WHERE title_id = ?", (GAME,)))


def test_the_extra_sources_add_the_versions_the_release_lacks(built):
    assert set(built) == {65536, 131072, 196608}


def test_the_release_keeps_its_own_dates(built):
    assert built[65536] == "2026-01-01"        # not borntohonk's 2025-12-31
    assert built[131072] == "2026-02-01"
    assert built[196608] is None               # nx-versions without its changelog: no date


# --- downloading them -------------------------------------------------------------------------

class _Response:
    def __init__(self, status, body=b"", etag=None):
        self.status_code, self.content = status, body
        self.headers = {"ETag": etag} if etag else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise extra_versions.requests.HTTPError(str(self.status_code))


def test_a_source_is_downloaded_only_when_it_changed(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(headers or {})
        if (headers or {}).get("If-None-Match") == '"v1"':
            return _Response(304)
        return _Response(200, b'{"0100AAAA00010000": {"65536": "2026-01-01"}}', etag='"v1"')

    monkeypatch.setattr(extra_versions, "SOURCES", {"borntohonk.versions.json": "https://example.test/v.json"})
    monkeypatch.setattr(extra_versions.requests, "get", fake_get)
    folder = str(tmp_path / "extra")
    assert extra_versions.refresh(folder) is True
    assert extra_versions.refresh(folder) is False
    assert calls[1].get("If-None-Match") == '"v1"'
    assert os.path.isfile(os.path.join(folder, "borntohonk.versions.json"))


def test_a_source_that_fails_keeps_the_last_copy(tmp_path, monkeypatch):
    folder = tmp_path / "extra"
    _write(str(folder / "borntohonk.versions.json"), '{"0100AAAA00010000": {"65536": "2026-01-01"}}')

    def down(url, headers=None, timeout=None):
        raise extra_versions.requests.ConnectionError("offline")

    monkeypatch.setattr(extra_versions, "SOURCES", {"borntohonk.versions.json": "https://example.test/v.json"})
    monkeypatch.setattr(extra_versions.requests, "get", down)
    assert extra_versions.refresh(str(folder)) is False
    assert (folder / "borntohonk.versions.json").read_text() == '{"0100AAAA00010000": {"65536": "2026-01-01"}}'


def test_a_bad_download_never_replaces_a_good_copy(tmp_path, monkeypatch):
    folder = tmp_path / "extra"
    _write(str(folder / "nx-versions.txt"), "id|version\n0100AAAA00010800|65536\n")
    monkeypatch.setattr(extra_versions, "SOURCES", {"nx-versions.txt": "https://example.test/v.txt"})
    monkeypatch.setattr(extra_versions.requests, "get",
                        lambda url, headers=None, timeout=None: _Response(200, b"<html>busy</html>", etag='"x"'))
    assert extra_versions.refresh(str(folder)) is False
    assert (folder / "nx-versions.txt").read_text().startswith("id|version")


def test_a_titledb_update_rebuilds_when_only_the_extra_sources_changed(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(update_mod, "TITLEDB_DIR", str(tmp_path))
    monkeypatch.setattr(update_mod, "update_titledb_files", lambda settings: ([], "same-commit"))
    monkeypatch.setattr(update_mod.extra_versions, "refresh", lambda folder: True)
    monkeypatch.setattr(update_mod.store, "get_imported_locale", lambda: "US.en")
    monkeypatch.setattr(update_mod.store, "import_from_json", lambda path, locale: calls.append(locale))
    monkeypatch.setattr(update_mod, "get_local_commit", lambda: "same-commit", raising=False)
    settings = {"titles": {"region": "US", "language": "en"}, "library": {"management": {"organizer": {}}}}
    try:
        update_mod.update_titledb(settings)
    except Exception:
        pass                                    # what follows the rebuild is not this test's business
    assert calls == ["US.en"]


# --- notifications ----------------------------------------------------------------------------

def test_each_catalogue_revision_silences_its_own_first_pass(tmp_path, monkeypatch):
    """The updates the extra sources add were out there already: the first pass after
    this change announces none of them, like the first one that read DLC from the
    catalogue (revision 1)."""
    import library
    import settings as settings_mod
    store = {"server": {"catalogue_revision": 1}}
    monkeypatch.setattr(settings_mod, "get_settings", lambda: store)

    class _Txn:
        def __enter__(self):
            return store

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(settings_mod, "settings_transaction", lambda: _Txn())
    assert library.CATALOGUE_REVISION == 2
    assert settings_mod.mark_catalogue_revision(library.CATALOGUE_REVISION) is True
    assert store["server"]["catalogue_revision"] == 2
    assert settings_mod.mark_catalogue_revision(library.CATALOGUE_REVISION) is False

"""The organizer's naming-language override needs its own locale file fetched and
imported into `organizer_names`, independent of the display locale in `titles`. Reuses
the same fake-release harness as test_titledb_update.py.
"""
import json
import os
import types

import pytest
import zstandard

import titledb
from titledb import update as update_mod

DEFAULTS = ["cnmts.json", "versions.json", "languages.json"]
REGION_FILE = "titles.US.en.json"
ORGANIZER_FILE = "titles.GB.en.json"

SETTINGS_NO_ORGANIZER_LOCALE = {"titles": {"region": "US", "language": "en"}}
SETTINGS_WITH_ORGANIZER_LOCALE = {
    "titles": {"region": "US", "language": "en"},
    "library": {"management": {"organizer": {"name_region": "GB", "name_language": "en"}}},
}


@pytest.fixture
def remote(tmp_path, monkeypatch):
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    monkeypatch.setattr(update_mod, "TITLEDB_DIR", str(titledb_dir))

    imported = []
    organizer_imported = []
    reset_calls = []
    import db as db_mod
    monkeypatch.setattr(update_mod.store, "get_imported_locale", lambda: "US.en")
    monkeypatch.setattr(update_mod.store, "import_from_json", lambda path, locale: imported.append((path, locale)))
    monkeypatch.setattr(update_mod.store, "get_organizer_names_locale", lambda: None)
    monkeypatch.setattr(update_mod.store, "import_organizer_names",
                         lambda path, locale: organizer_imported.append((path, locale)))
    # reset_files_organized needs a Flask app context these tests don't set up - it's
    # only relevant here as a "did it get called" signal, not its actual DB effect,
    # which test_missing_files_guard.py and friends already cover with a real app.
    monkeypatch.setattr(db_mod, "reset_files_organized", lambda: reset_calls.append(True))

    class FakeResponse:
        def __init__(self, body, status=200):
            self._body = body
            self.status = status

        @property
        def text(self):
            return self._body.decode()

        def iter_content(self, size):
            for i in range(0, len(self._body), size):
                yield self._body[i:i + size]

        def raise_for_status(self):
            if self.status != 200:
                raise Exception(f"{self.status}")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    state = types.SimpleNamespace(
        dir=titledb_dir, commit="2222222222222222222222222222222222222222",
        assets={}, requested=[], imported=imported, organizer_imported=organizer_imported,
        reset_calls=reset_calls,
    )

    def publish(name, payload):
        state.assets[name] = zstandard.ZstdCompressor().compress(json.dumps(payload).encode())

    for name in DEFAULTS + [REGION_FILE, ORGANIZER_FILE]:
        publish(name, {"file": name})

    def fake_get(url, **kwargs):
        name = url.rsplit("/", 1)[-1]
        state.requested.append(name)
        if name == "latest":
            return FakeResponse(state.commit.encode())
        asset = name[: -len(".zst")]
        if asset not in state.assets:
            return FakeResponse(b"", status=404)
        return FakeResponse(state.assets[asset])

    monkeypatch.setattr(update_mod.requests, "get", fake_get)
    return state


def downloaded(remote):
    return sorted(f for f in os.listdir(remote.dir) if f.endswith(".json"))


def test_no_organizer_locale_configured_does_not_fetch_an_extra_file(remote):
    titledb.update_titledb(SETTINGS_NO_ORGANIZER_LOCALE)

    assert downloaded(remote) == sorted(DEFAULTS + [REGION_FILE])
    assert remote.organizer_imported == []


def test_organizer_locale_file_is_fetched_and_imported_on_first_run(remote):
    titledb.update_titledb(SETTINGS_WITH_ORGANIZER_LOCALE)

    assert ORGANIZER_FILE in downloaded(remote)
    assert remote.organizer_imported == [(str(remote.dir / ORGANIZER_FILE), "GB.en")]


def test_organizer_locale_file_already_present_is_still_imported_when_missing_from_store(remote, monkeypatch):
    """A fresh titles.db rebuild wipes organizer_names, so the file being on disk
    already is not enough - it has to be (re)imported whenever the main rebuild ran."""
    (remote.dir / ORGANIZER_FILE).write_text('{"file": "titles.GB.en.json"}')
    (remote.dir / ".latest").write_text(remote.commit)

    titledb.update_titledb(SETTINGS_WITH_ORGANIZER_LOCALE)

    # Marker matched, so nothing should have been re-downloaded...
    assert "titles.GB.en.json.zst" not in remote.requested
    # ...but store.get_organizer_names_locale() is stubbed to None (never imported), so
    # the existing file must still get imported.
    assert remote.organizer_imported == [(str(remote.dir / ORGANIZER_FILE), "GB.en")]


def test_organizer_locale_change_reimports_even_without_a_main_rebuild(remote, monkeypatch):
    """The organizer locale itself changing must trigger an import even when nothing
    else about titledb changed (marker matches, display locale unchanged)."""
    for name in DEFAULTS + [REGION_FILE, ORGANIZER_FILE]:
        (remote.dir / name).write_text(json.dumps({"file": name}))
    (remote.dir / ".latest").write_text(remote.commit)
    monkeypatch.setattr(update_mod.store, "get_organizer_names_locale", lambda: "FR.fr")

    titledb.update_titledb(SETTINGS_WITH_ORGANIZER_LOCALE)

    assert remote.organizer_imported == [(str(remote.dir / ORGANIZER_FILE), "GB.en")]
    # And the main store was untouched - only the organizer names needed a refresh.
    assert remote.imported == []


def test_organizer_locale_up_to_date_does_not_reimport(remote, monkeypatch):
    for name in DEFAULTS + [REGION_FILE, ORGANIZER_FILE]:
        (remote.dir / name).write_text(json.dumps({"file": name}))
    (remote.dir / ".latest").write_text(remote.commit)
    monkeypatch.setattr(update_mod.store, "get_organizer_names_locale", lambda: "GB.en")

    titledb.update_titledb(SETTINGS_WITH_ORGANIZER_LOCALE)

    assert remote.organizer_imported == []
    assert remote.imported == []


def test_organizer_locale_change_resets_organized_flag(remote, monkeypatch):
    monkeypatch.setattr(update_mod.store, "get_organizer_names_locale", lambda: "FR.fr")
    for name in DEFAULTS + [REGION_FILE, ORGANIZER_FILE]:
        (remote.dir / name).write_text(json.dumps({"file": name}))
    (remote.dir / ".latest").write_text(remote.commit)

    titledb.update_titledb(SETTINGS_WITH_ORGANIZER_LOCALE)

    assert remote.reset_calls == [True]

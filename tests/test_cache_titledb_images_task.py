"""cache_titledb_images_task walks every title ownfoil tracks (see
titledb.images.titles_needing_images) and caches its banner/icon locally. requests.get
is mocked - no real network calls.
"""
import json
import types
from unittest.mock import patch

import pytest

import db as db_mod
import tasks
import titledb
from titledb import images as images_lib
from app import create_app
from constants import APP_TYPE_BASE
from db import Apps, Libraries, Titles, db, init_db


class FakeResponse:
    def __init__(self, body=b"BYTES", status=200):
        self._body = body
        self.status_code = status
        self.headers = {"Content-Type": "image/jpeg"}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(images_lib, "IMAGES_DIR", str(tmp_path / "images"))

    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    init_db(app)

    title_id = "0100000000010000"
    region_file = titledb_dir / "titles.US.en.json"
    region_file.write_text(json.dumps({
        title_id: {"id": title_id, "name": "Game",
                   "bannerUrl": "https://example.com/banner.jpg",
                   "iconUrl": "https://example.com/icon.jpg"},
    }))
    (titledb_dir / "cnmts.json").write_text("{}")
    (titledb_dir / "versions.json").write_text("{}")
    with app.app_context():
        titledb.store.import_from_json(str(region_file), "US.en")
        lib_row = Libraries(path=str(tmp_path / "games"))
        db.session.add(lib_row)
        db.session.flush()
        title_row = Titles(title_id=title_id, have_base=True)
        db.session.add(title_row)
        db.session.flush()
        app_row = Apps(title_id=title_row.id, app_id=title_id, app_version="0",
                       app_type=APP_TYPE_BASE, owned=True)
        db.session.add(app_row)
        db.session.commit()

    yield types.SimpleNamespace(app=app, title_id=title_id)


def _settings(cache_images=True):
    return {"titles": {"region": "US", "language": "en", "cache_images": cache_images}}


def test_caches_banner_and_icon_for_a_tracked_title(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(tasks.time, "sleep", lambda *a: None)
    with env.app.app_context(), patch("titledb.images.requests.get", return_value=FakeResponse()) as mock_get:
        tasks.cache_titledb_images_task()

    assert mock_get.call_count == 2  # banner + icon
    assert images_lib.image_cache_path(env.title_id, "banner") is not None
    assert images_lib.image_cache_path(env.title_id, "icon") is not None


def test_does_nothing_when_the_setting_is_off(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(False))
    with env.app.app_context(), patch("titledb.images.requests.get") as mock_get:
        tasks.cache_titledb_images_task()

    mock_get.assert_not_called()
    assert images_lib.image_cache_path(env.title_id, "banner") is None


def test_a_second_run_does_not_redownload_already_cached_art(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(tasks.time, "sleep", lambda *a: None)
    with env.app.app_context():
        with patch("titledb.images.requests.get", return_value=FakeResponse()) as mock_get:
            tasks.cache_titledb_images_task()
            assert mock_get.call_count == 2
            tasks.cache_titledb_images_task()
            assert mock_get.call_count == 2  # nothing new to fetch


def test_a_network_failure_on_one_title_does_not_crash_the_whole_pass(env, monkeypatch):
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(True))
    monkeypatch.setattr(tasks.time, "sleep", lambda *a: None)
    import requests
    with env.app.app_context(), patch("titledb.images.requests.get",
                                      side_effect=requests.ConnectionError("offline")):
        tasks.cache_titledb_images_task()  # must not raise

    assert images_lib.image_cache_path(env.title_id, "banner") is None


def test_pauses_between_real_downloads_but_not_after_a_cache_hit(env, monkeypatch):
    """A burst of requests to the same third-party host is what gets an IP
    rate-limited - the pause only needs to happen for actual network hits, never for
    art that was already cached (no request was made, nothing to space out)."""
    monkeypatch.setattr(tasks, "get_settings", lambda: _settings(True))
    sleep_calls = []
    monkeypatch.setattr(tasks.time, "sleep", lambda s: sleep_calls.append(s))

    with env.app.app_context(), patch("titledb.images.requests.get", return_value=FakeResponse()):
        tasks.cache_titledb_images_task()  # 2 real downloads (banner + icon)
        assert len(sleep_calls) == 2
        assert all(s == images_lib.DOWNLOAD_DELAY for s in sleep_calls)

        sleep_calls.clear()
        tasks.cache_titledb_images_task()  # both already cached now
        assert sleep_calls == []

"""titledb/images.py: local caching of banner/icon artwork, so the library page's
images don't depend on titledb's own remote image host being reachable on every page
load. requests.get is mocked throughout - no real network calls.
"""
import json
import os
import types
from unittest.mock import patch

import pytest

import db as db_mod
import titledb
from titledb import images as images_lib
from app import create_app
from constants import APP_TYPE_BASE
from db import Apps, Libraries, Titles, db, init_db


class FakeResponse:
    """Minimal stand-in for requests.Response, streaming-compatible."""
    def __init__(self, body=b"FAKEIMAGEBYTES", status=200, content_type="image/jpeg"):
        self._body = body
        self.status_code = status
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}")

    def iter_content(self, chunk_size):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(images_lib, "TITLEDB_DIR", str(tmp_path / "titledb"))
    monkeypatch.setattr(images_lib, "IMAGES_DIR", str(tmp_path / "titledb" / "images"))
    return tmp_path / "titledb" / "images"


def test_image_cache_path_is_none_before_anything_is_cached(cache_dir):
    assert images_lib.image_cache_path("0100000000010000", "banner") is None


def test_cache_image_downloads_and_reports_the_cached_path(cache_dir):
    with patch("titledb.images.requests.get", return_value=FakeResponse()) as mock_get:
        result = images_lib.cache_image("0100000000010000", "banner",
                                        "https://example.com/art.jpg")

    assert result is True
    mock_get.assert_called_once()
    path = images_lib.image_cache_path("0100000000010000", "banner")
    assert path is not None
    assert path.endswith(".jpg")
    with open(path, "rb") as f:
        assert f.read() == b"FAKEIMAGEBYTES"


def test_cache_image_is_a_noop_once_already_cached(cache_dir):
    with patch("titledb.images.requests.get", return_value=FakeResponse()) as mock_get:
        images_lib.cache_image("0100000000010000", "icon", "https://example.com/icon.png")
        assert mock_get.call_count == 1

        # Second call for the same title/kind must not hit the network again.
        result = images_lib.cache_image("0100000000010000", "icon", "https://example.com/icon.png")
        assert result is True
        assert mock_get.call_count == 1


def test_cache_image_returns_false_and_leaves_nothing_behind_on_network_failure(cache_dir):
    import requests

    with patch("titledb.images.requests.get", side_effect=requests.ConnectionError("offline")):
        result = images_lib.cache_image("0100000000010000", "banner", "https://example.com/x.jpg")

    assert result is False
    assert images_lib.image_cache_path("0100000000010000", "banner") is None
    # No stray .tmp file left around either.
    assert not os.path.isdir(images_lib.IMAGES_DIR) or os.listdir(images_lib.IMAGES_DIR) == []


def test_cache_image_returns_false_for_an_http_error_status(cache_dir):
    with patch("titledb.images.requests.get", return_value=FakeResponse(status=404)):
        result = images_lib.cache_image("0100000000010000", "banner", "https://example.com/x.jpg")

    assert result is False
    assert images_lib.image_cache_path("0100000000010000", "banner") is None


@pytest.mark.parametrize("url,content_type,expected_ext", [
    ("https://example.com/art.png", "image/jpeg", ".png"),       # URL wins over content-type
    ("https://example.com/art.PNG?x=1", "image/jpeg", ".png"),   # case-insensitive, query stripped
    ("https://example.com/art", "image/webp", ".webp"),          # falls back to content-type
    ("https://example.com/art", "image/png; charset=binary", ".png"),
    ("https://example.com/art", "text/html", ".jpg"),            # unknown type: safe default
])
def test_guess_extension(url, content_type, expected_ext):
    assert images_lib._guess_extension(url, content_type) == expected_ext


def test_cache_image_is_a_noop_with_no_url_or_title_id(cache_dir):
    assert images_lib.cache_image("", "banner", "https://example.com/x.jpg") is False
    assert images_lib.cache_image("0100000000010000", "banner", "") is False
    assert images_lib.cache_image("0100000000010000", "poster", "https://example.com/x.jpg") is False


# --- titles_needing_images ---------------------------------------------------------

@pytest.fixture
def library(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))

    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    init_db(app)

    title_id = "0100000000010000"
    dlc_id = "0100000000010001"
    region_file = titledb_dir / "titles.US.en.json"
    region_file.write_text(json.dumps({
        title_id: {"id": title_id, "name": "Game"},
        dlc_id: {"id": dlc_id, "name": "DLC"},
    }))
    cnmts = {dlc_id.lower(): {"0": {"titleId": dlc_id.lower(), "titleType": 130,
                                    "version": 0, "otherApplicationId": title_id.lower()}}}
    (titledb_dir / "cnmts.json").write_text(json.dumps(cnmts))
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

    return types.SimpleNamespace(app=app, title_id=title_id, dlc_id=dlc_id)


def test_titles_needing_images_includes_owned_title_and_its_dlc(library):
    with library.app.app_context():
        result = images_lib.titles_needing_images()

    assert result == sorted([library.title_id, library.dlc_id])


def test_titles_needing_images_empty_with_no_titles_tracked(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    init_db(app)
    with app.app_context():
        assert images_lib.titles_needing_images() == []

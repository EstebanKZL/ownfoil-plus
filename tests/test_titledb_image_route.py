"""GET /api/titledb-image/<title_id>/<kind> serves locally-cached artwork when it
exists, and falls back to a live redirect to titledb's own URL otherwise - the
frontend always points here, never at the remote host directly (see
titledb/images.py and the List view's use of it in index.html).
"""
import copy

import pytest

import constants
import fixture
import titledb
from titledb import images as images_lib


@pytest.fixture
def shop(shop_app):
    import settings as _settings_mod
    orig = _settings_mod.DEFAULT_SETTINGS
    _settings_mod.DEFAULT_SETTINGS = copy.deepcopy(constants.DEFAULT_SETTINGS)
    yield shop_app
    _settings_mod.DEFAULT_SETTINGS = orig


def _login(shop, user, password):
    resp = shop.client.post("/login", data={"user": user, "password": password}, follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)


TITLE_ID = "0100000000010000"


def test_serves_the_cached_file_when_one_exists(shop, tmp_path, monkeypatch):
    monkeypatch.setattr(images_lib, "IMAGES_DIR", str(tmp_path))
    (tmp_path / f"{TITLE_ID}_banner.jpg").write_bytes(b"CACHEDBYTES")
    _login(shop, "shopper", fixture.PASSWORDS["shopper"])

    resp = shop.client.get(f"/api/titledb-image/{TITLE_ID}/banner")

    assert resp.status_code == 200
    assert resp.data == b"CACHEDBYTES"


def test_redirects_to_the_remote_url_when_nothing_is_cached(shop, tmp_path, monkeypatch):
    monkeypatch.setattr(images_lib, "IMAGES_DIR", str(tmp_path / "empty"))
    with shop.app.app_context():
        monkeypatch.setattr("app.titles_lib.get_game_info", lambda tid: {
            "name": "Game", "bannerUrl": "https://example.com/banner.jpg", "iconUrl": "https://example.com/icon.jpg",
        })
    _login(shop, "shopper", fixture.PASSWORDS["shopper"])

    resp = shop.client.get(f"/api/titledb-image/{TITLE_ID}/banner", follow_redirects=False)

    assert resp.status_code in (301, 302, 303, 307, 308)
    assert resp.headers["Location"] == "https://example.com/banner.jpg"


def test_icon_kind_redirects_to_the_icon_url_not_the_banner(shop, tmp_path, monkeypatch):
    monkeypatch.setattr(images_lib, "IMAGES_DIR", str(tmp_path / "empty"))
    with shop.app.app_context():
        monkeypatch.setattr("app.titles_lib.get_game_info", lambda tid: {
            "name": "Game", "bannerUrl": "https://example.com/banner.jpg", "iconUrl": "https://example.com/icon.jpg",
        })
    _login(shop, "shopper", fixture.PASSWORDS["shopper"])

    resp = shop.client.get(f"/api/titledb-image/{TITLE_ID}/icon", follow_redirects=False)

    assert resp.headers["Location"] == "https://example.com/icon.jpg"


def test_unknown_title_with_no_url_is_a_404(shop, tmp_path, monkeypatch):
    monkeypatch.setattr(images_lib, "IMAGES_DIR", str(tmp_path / "empty"))
    with shop.app.app_context():
        monkeypatch.setattr("app.titles_lib.get_game_info", lambda tid: None)
    _login(shop, "shopper", fixture.PASSWORDS["shopper"])

    resp = shop.client.get(f"/api/titledb-image/{TITLE_ID}/banner")

    assert resp.status_code == 404


def test_invalid_kind_is_a_400(shop):
    _login(shop, "shopper", fixture.PASSWORDS["shopper"])

    resp = shop.client.get(f"/api/titledb-image/{TITLE_ID}/poster")

    assert resp.status_code == 400


def test_requires_at_least_shop_access(shop, tmp_path, monkeypatch):
    monkeypatch.setattr(images_lib, "IMAGES_DIR", str(tmp_path))
    (tmp_path / f"{TITLE_ID}_banner.jpg").write_bytes(b"CACHEDBYTES")

    resp = shop.client.get(f"/api/titledb-image/{TITLE_ID}/banner", follow_redirects=False)

    assert resp.status_code in (302, 303)  # redirected to login, not served the image

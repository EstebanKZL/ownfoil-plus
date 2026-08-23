"""`/api/library/download/<file_id>` is the List view's download button target. It has
two independent gates - the caller must be a logged-in admin, AND the Settings toggle
must be on - unlike the shop's own `/api/get_game/<id>`, which is Basic-Auth/shop-access
gated and has no such toggle. Both gates are enforced server-side regardless of what the
frontend chooses to draw a button for.
"""
import copy
import io
import types

import pytest

import constants
import fixture
import settings as settings_mod
from db import Files
from settings import set_library_management_settings


@pytest.fixture
def shop(shop_app):
    # When settings.yaml doesn't exist yet, load_settings() hands back
    # settings_mod.DEFAULT_SETTINGS itself (by reference, not a copy) - mutating it in
    # one test (e.g. enabling web_downloads) would otherwise leak into every other test
    # sharing this process, since shop_app's tmp settings.yaml is fresh per test but
    # this shared dict object is not.
    import settings as _settings_mod
    orig = _settings_mod.DEFAULT_SETTINGS
    _settings_mod.DEFAULT_SETTINGS = copy.deepcopy(constants.DEFAULT_SETTINGS)
    yield shop_app
    _settings_mod.DEFAULT_SETTINGS = orig


def _login(shop, user, password):
    resp = shop.client.post("/login", data={"user": user, "password": password}, follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)


def _enable_web_downloads(enabled=True):
    set_library_management_settings({"web_downloads": {"enabled": enabled}})


def _first_owned_file_id(shop):
    with shop.app.app_context():
        f = Files.query.filter(Files.identified.is_(True)).first()
        assert f is not None, "fixture library has no identified file to target"
        return f.id


def test_admin_can_download_when_enabled(shop):
    _enable_web_downloads(True)
    _login(shop, "admin", fixture.PASSWORDS["admin"])
    file_id = _first_owned_file_id(shop)

    resp = shop.client.get(f"/api/library/download/{file_id}")

    assert resp.status_code == 200
    assert resp.headers.get("Content-Disposition", "").startswith("attachment")


def test_disabled_by_default_even_for_admin(shop):
    """web_downloads.enabled defaults to False - an admin gets a clear 403, not a file,
    until the setting is explicitly turned on."""
    _login(shop, "admin", fixture.PASSWORDS["admin"])
    file_id = _first_owned_file_id(shop)

    resp = shop.client.get(f"/api/library/download/{file_id}")

    assert resp.status_code == 403


def test_non_admin_shop_user_is_forbidden_even_when_enabled(shop):
    """shop-only access is not enough - this route requires the 'admin' role
    specifically, matching how the rest of the web UI's own admin actions are gated."""
    _enable_web_downloads(True)
    _login(shop, "shopper", fixture.PASSWORDS["shopper"])
    file_id = _first_owned_file_id(shop)

    resp = shop.client.get(f"/api/library/download/{file_id}")

    assert resp.status_code == 403


def test_unauthenticated_request_is_redirected_to_login(shop):
    _enable_web_downloads(True)
    file_id = _first_owned_file_id(shop)

    resp = shop.client.get(f"/api/library/download/{file_id}", follow_redirects=False)

    assert resp.status_code in (302, 303)


def test_unknown_file_id_is_a_404_not_a_500(shop):
    _enable_web_downloads(True)
    _login(shop, "admin", fixture.PASSWORDS["admin"])

    resp = shop.client.get("/api/library/download/999999")

    assert resp.status_code == 404


def test_a_file_missing_from_disk_is_a_404(shop):
    """The database row exists but the physical file doesn't (e.g. deleted outside
    ownfoil) - must not try to serve a nonexistent path."""
    _enable_web_downloads(True)
    _login(shop, "admin", fixture.PASSWORDS["admin"])
    file_id = _first_owned_file_id(shop)

    with shop.app.app_context():
        f = Files.query.get(file_id)
        f.filepath = f.filepath + ".moved-away"
        from db import db
        db.session.commit()

    resp = shop.client.get(f"/api/library/download/{file_id}")

    assert resp.status_code == 404


def test_disabling_after_being_enabled_takes_effect_immediately(shop):
    _enable_web_downloads(True)
    _login(shop, "admin", fixture.PASSWORDS["admin"])
    file_id = _first_owned_file_id(shop)
    assert shop.client.get(f"/api/library/download/{file_id}").status_code == 200

    _enable_web_downloads(False)

    assert shop.client.get(f"/api/library/download/{file_id}").status_code == 403

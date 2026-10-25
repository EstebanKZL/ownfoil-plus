"""`/api/library/download/<file_id>` is the List view's download button target. It has
two independent gates - the caller must be logged in with at least shop access (admin
or a plain shop user), AND the Settings toggle must be on - unlike the shop's own
`/api/get_game/<id>`, which is Basic-Auth/shop-access gated and has no such toggle.
Both gates are enforced server-side regardless of what the frontend chooses to draw a
button for.
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


def test_shop_only_user_can_also_download_when_enabled(shop):
    """A user with shop access but no admin role - a "Tienda" account - can download
    too, as long as the setting is on. Shop access is the bar, not the admin role."""
    _enable_web_downloads(True)
    _login(shop, "shopper", fixture.PASSWORDS["shopper"])
    file_id = _first_owned_file_id(shop)

    resp = shop.client.get(f"/api/library/download/{file_id}")

    assert resp.status_code == 200
    assert resp.headers.get("Content-Disposition", "").startswith("attachment")


def test_shop_only_user_is_forbidden_when_disabled(shop):
    _login(shop, "shopper", fixture.PASSWORDS["shopper"])
    file_id = _first_owned_file_id(shop)

    resp = shop.client.get(f"/api/library/download/{file_id}")

    assert resp.status_code == 403


def test_a_user_with_neither_admin_nor_shop_access_is_still_forbidden(shop):
    """The bar is shop access, not "logged in at all" - a login-only account with
    neither role must still be turned away, setting or no setting."""
    _enable_web_downloads(True)
    _login(shop, "noshop", fixture.PASSWORDS["noshop"])
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


# --- The IS_SHOP flag the page itself renders with, per user type -------------------

def _is_shop_flag(html):
    """Pull the boolean literal the template injected for IS_SHOP, without depending
    on exact surrounding whitespace."""
    import re
    m = re.search(r"const IS_SHOP = (true|false);", html)
    assert m, "IS_SHOP was not found in the rendered page"
    return m.group(1) == "true"


def test_admin_page_render_carries_is_shop_true(shop):
    _login(shop, "admin", fixture.PASSWORDS["admin"])
    html = shop.client.get("/").get_data(as_text=True)
    assert _is_shop_flag(html) is True


def test_shop_only_user_page_render_carries_is_shop_true(shop):
    """The whole point of this change: a shop-only account also gets IS_SHOP=true,
    not just an admin - it used to be IS_ADMIN gating the download button here."""
    _login(shop, "shopper", fixture.PASSWORDS["shopper"])
    html = shop.client.get("/").get_data(as_text=True)
    assert _is_shop_flag(html) is True


def test_no_access_user_page_render_carries_is_shop_false(shop):
    """The shop is private by default, and a no-access user gets turned away before
    ever reaching the page - so this makes the shop public first, specifically to
    observe IS_SHOP=false in the rendered output rather than a redirect/403."""
    import settings as settings_mod
    settings_mod.set_shop_settings({"public": True})
    _login(shop, "noshop", fixture.PASSWORDS["noshop"])
    html = shop.client.get("/").get_data(as_text=True)
    assert _is_shop_flag(html) is False

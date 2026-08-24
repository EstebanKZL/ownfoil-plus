"""App.downloadableFile: the minimal (id/size/verificationStatus) slice of a file a
download button needs, visible to any shop-access viewer - unlike App.files, which
stays admin-only. Both are backed by the same underlying hydration now (see
resolve_title/resolve_titles' hydrate_apps_files), so the critical thing to prove is
that files still comes back null for a non-admin even when both fields are requested
in the very same query - not just when downloadableFile is requested alone.
"""
import copy
import json

import pytest

import constants
import fixture
from db import Files


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


def _owned_title_id(shop):
    with shop.app.app_context():
        f = Files.query.filter(Files.identified.is_(True)).first()
        assert f is not None, "fixture library has no identified file to target"
        app = f.apps[0]
        return app.title.title_id if app.title else app.app_id


def _query(shop, query, **variables):
    resp = shop.client.get("/api/graphql", query_string={
        "query": query, "variables": json.dumps(variables)})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    return body["data"]


BOTH_FIELDS_QUERY = """
    query($titleId: ID!) {
        title(titleId: $titleId) {
            apps(owned: true) {
                downloadableFile { id size verificationStatus }
                files { id filename }
            }
        }
    }"""

DOWNLOADABLE_ONLY_QUERY = """
    query($titleId: ID!) {
        title(titleId: $titleId) {
            apps(owned: true) { downloadableFile { id size verificationStatus } }
        }
    }"""


def test_a_shop_only_user_gets_downloadable_file_data(shop):
    _login(shop, "shopper", fixture.PASSWORDS["shopper"])
    tid = _owned_title_id(shop)

    data = _query(shop, DOWNLOADABLE_ONLY_QUERY, titleId=tid)

    apps_with_file = [a for a in data["title"]["apps"] if a["downloadableFile"]]
    assert apps_with_file, "expected at least one owned app to carry a downloadableFile"
    assert apps_with_file[0]["downloadableFile"]["id"]
    assert apps_with_file[0]["downloadableFile"]["size"] is not None


def test_a_shop_only_users_files_field_is_still_null_even_requested_alongside_downloadable_file(shop):
    """The critical security case: both fields trigger the same underlying fetch, so
    this proves files() checks admin access itself rather than trusting "was
    something fetched" - a non-admin must never see filename/folder just because they
    also asked for the shop-safe field in the same query."""
    _login(shop, "shopper", fixture.PASSWORDS["shopper"])
    tid = _owned_title_id(shop)

    data = _query(shop, BOTH_FIELDS_QUERY, titleId=tid)

    apps = data["title"]["apps"]
    assert any(a["downloadableFile"] for a in apps), "downloadableFile should still work"
    assert all(a["files"] is None for a in apps), "files must stay null for a shop-only user"


def test_an_admin_gets_both_fields_populated(shop):
    _login(shop, "admin", fixture.PASSWORDS["admin"])
    tid = _owned_title_id(shop)

    data = _query(shop, BOTH_FIELDS_QUERY, titleId=tid)

    apps_with_data = [a for a in data["title"]["apps"] if a["downloadableFile"]]
    assert apps_with_data
    assert any(a["files"] for a in apps_with_data)
    # Same file, both ways - not two different fetches disagreeing with each other.
    matching = apps_with_data[0]
    assert matching["downloadableFile"]["id"] == matching["files"][0]["id"]


def test_a_no_access_user_gets_neither_field(shop):
    """A user with neither admin nor shop access can't even reach the GraphQL
    endpoint at all - it 403s before any resolver runs, let alone leaks download info."""
    _login(shop, "noshop", fixture.PASSWORDS["noshop"])
    tid = _owned_title_id(shop)

    resp = shop.client.get("/api/graphql", query_string={
        "query": BOTH_FIELDS_QUERY, "variables": json.dumps({"titleId": tid})})

    assert resp.status_code == 403

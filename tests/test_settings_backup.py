"""GET /api/settings/export and POST /api/settings/import: back up and restore
settings.yaml from the web UI. Import merges into the current settings rather than
replacing them outright, so an older/partial export doesn't blank out sections it
doesn't know about.
"""
import io
import re

import fixture
import pytest
import yaml

from settings import get_settings


@pytest.fixture
def client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


@pytest.fixture
def shopper_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def test_export_serves_a_yaml_attachment(client):
    resp = client.get("/api/settings/export")

    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    assert resp.headers.get("Content-Disposition", "").endswith('.yaml"')
    parsed = yaml.safe_load(resp.get_data(as_text=True))
    assert isinstance(parsed, dict)
    assert "library" in parsed  # a real, populated settings tree, not an empty file


def test_export_reflects_a_change_made_before_exporting(client):
    with client.application.app_context():
        from settings import set_library_management_settings
        set_library_management_settings({"delete_older_updates": True})

    resp = client.get("/api/settings/export")
    parsed = yaml.safe_load(resp.get_data(as_text=True))

    assert parsed["library"]["management"]["delete_older_updates"] is True


def test_import_merges_an_exported_file_back_in(client):
    with client.application.app_context():
        from settings import set_library_management_settings
        set_library_management_settings({"delete_older_updates": True})
    exported = client.get("/api/settings/export").get_data(as_text=True)

    with client.application.app_context():
        from settings import set_library_management_settings
        set_library_management_settings({"delete_older_updates": False})

    resp = client.post("/api/settings/import",
                       data={"file": (io.BytesIO(exported.encode()), "backup.yaml")},
                       content_type="multipart/form-data")

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    with client.application.app_context():
        assert get_settings()["library"]["management"]["delete_older_updates"] is True


def test_import_does_not_wipe_sections_the_file_does_not_mention(client):
    """A deep merge, not a replace: importing a file that only talks about one setting
    must leave everything else - including settings the file predates - untouched."""
    with client.application.app_context():
        settings_before = get_settings()
        assert "titles" in settings_before  # sanity: a real section exists to preserve

    minimal_yaml = yaml.safe_dump({"library": {"management": {"delete_older_updates": True}}})
    resp = client.post("/api/settings/import",
                       data={"file": (io.BytesIO(minimal_yaml.encode()), "minimal.yaml")},
                       content_type="multipart/form-data")

    assert resp.status_code == 200
    with client.application.app_context():
        after = get_settings()
        assert after["library"]["management"]["delete_older_updates"] is True
        assert "titles" in after  # untouched, not dropped by the partial import


def test_import_rejects_a_missing_file(client):
    resp = client.post("/api/settings/import", data={}, content_type="multipart/form-data")

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_import_rejects_invalid_yaml(client):
    resp = client.post("/api/settings/import",
                       data={"file": (io.BytesIO(b": : not: yaml: at: all: ["), "bad.yaml")},
                       content_type="multipart/form-data")

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_import_rejects_a_yaml_list_instead_of_a_mapping(client):
    resp = client.post("/api/settings/import",
                       data={"file": (io.BytesIO(b"- one\n- two\n"), "list.yaml")},
                       content_type="multipart/form-data")

    assert resp.status_code == 400
    assert "mapping" in resp.get_json()["error"]


def test_import_rejects_non_utf8_content(client):
    resp = client.post("/api/settings/import",
                       data={"file": (io.BytesIO(b"\xff\xfe\x00\x01"), "bad-encoding.yaml")},
                       content_type="multipart/form-data")

    assert resp.status_code == 400


def test_export_requires_admin_not_just_shop_access(shopper_client):
    resp = shopper_client.get("/api/settings/export", follow_redirects=False)

    assert resp.status_code in (302, 303, 403)


def test_import_requires_admin_not_just_shop_access(shopper_client):
    resp = shopper_client.post("/api/settings/import", data={},
                               content_type="multipart/form-data", follow_redirects=False)

    assert resp.status_code in (302, 303, 403)


def test_unauthenticated_export_redirects_to_login(shop_app):
    resp = shop_app.client.get("/api/settings/export", follow_redirects=False)

    assert resp.status_code in (302, 303)


# --- UI wiring on the Settings page ------------------------------------------------

@pytest.fixture
def settings_page_client(client):
    """/admin/settings additionally reads TITLEDB_DIR/languages.json, which the
    shop_app fixture's bare titledb dir doesn't seed - not something this feature
    touches, just a pre-existing dependency of that one route."""
    import json
    from constants import TITLEDB_DIR
    import os
    os.makedirs(TITLEDB_DIR, exist_ok=True)
    with open(os.path.join(TITLEDB_DIR, "languages.json"), "w") as f:
        json.dump({"US": ["en"]}, f)
    return client


def test_settings_page_has_the_backup_controls(settings_page_client):
    resp = settings_page_client.get("/admin/settings")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert '/api/settings/export' in html
    assert 'importSettingsFile' in html
    assert 'importSettingsBtn' in html


def test_settings_page_script_is_not_split_by_a_stray_closing_tag(settings_page_client):
    """Same regression class as the stats/tasks pages' equivalent tests."""
    resp = settings_page_client.get("/admin/settings")
    html = resp.get_data(as_text=True)

    script_blocks = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(script_blocks) == 1, (
        f"Expected exactly one inline <script>...</script> block, found {len(script_blocks)}")
    assert "function importSettings" in script_blocks[0]
    assert "function submitWorkerSettings" in script_blocks[0]

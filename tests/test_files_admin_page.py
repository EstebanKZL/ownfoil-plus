"""Coverage for the Files admin page (ported from upstream ownfoil 2.5.0 to match its
tiles/search/filter/drawer/duplicates-review layout, adapted to this fork's own
GraphQL schema - including the "Outdated updates" and "Pending" tiles and the per-file
Verify/Compress/Decompress/Retry actions, see CHANGELOG 6.2.4.10), the
deleteFileRecord/resolveDuplicateFiles/retryIdentification/verifyFile/compressFile/
decompressFile mutations it's built on, and the Setup page's updated Sphaira
instructions (the native "Ownfoil" menu / discovery flow, replacing the old
manual-mount instructions).
"""
import json
import os

import fixture
import pytest


@pytest.fixture
def client(shop_app):
    os.makedirs(__import__("constants").TITLEDB_DIR, exist_ok=True)
    with open(os.path.join(__import__("constants").TITLEDB_DIR, "languages.json"), "w") as f:
        json.dump({"US": ["en"]}, f)

    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def gql(client, query, variables=None):
    resp = client.post("/api/graphql", json={"query": query, "variables": variables or {}})
    body = resp.get_json()
    assert "errors" not in body or not body["errors"], body.get("errors")
    return body["data"]


# --- Page and nav -----------------------------------------------------------------

def test_files_page_requires_admin(shop_app):
    resp = shop_app.client.get("/admin/files", follow_redirects=False)
    assert resp.status_code in (302, 303)


def test_files_page_renders_for_admin(client):
    html = client.get("/admin/files").get_data(as_text=True)
    assert "filesTiles" in html
    assert "filesBody" in html
    assert "filesSearch" in html
    assert "filesDrawer" in html
    # The six tiles this port ships, matching the real shop's own Files page:
    # All/Unidentified/Verification issues/Duplicates/Outdated updates/Pending.
    for tile in ("all", "unidentified", "verification", "duplicates", "outdated", "pending"):
        assert f'data-tile="{tile}"' in html


def test_files_nav_link_is_present_on_the_settings_sidebar(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    assert '/admin/files' in html


def test_files_page_has_the_search_box_and_filter_dropdown_from_the_real_shop(client):
    html = client.get("/admin/files").get_data(as_text=True)
    assert 'placeholder="File name"' in html
    assert 'id="filesAddFilter"' in html
    assert 'files-pager' in html


def test_files_page_wires_the_outdated_and_pending_queries_and_the_four_file_actions(client):
    html = client.get("/admin/files").get_data(as_text=True)
    assert "outdatedUpdateGroups" in html
    assert "pendingFiles" in html
    for mutation in ("retryIdentification", "verifyFile", "compressFile", "decompressFile", "deleteFileRecord"):
        assert mutation in html


# --- Backend data the page's tiles and table are built from ------------------------

def test_stats_report_the_fixture_librarys_file_and_unidentified_counts(client):
    data = gql(client, "{ stats { totalFiles unidentifiedFiles } }")
    # fixture.LIBRARY: 5 files, 1 of them (Mystery File.nsp) marked unidentified.
    assert data["stats"]["totalFiles"] == 5
    assert data["stats"]["unidentifiedFiles"] == 1


def test_files_filter_by_identified_false_returns_only_the_unidentified_file(client):
    data = gql(client, """
        query { files(filter: {identified: false}) { total items { filename } } }
    """)
    assert data["files"]["total"] == 1
    assert data["files"]["items"][0]["filename"] == "Mystery File.nsp"


def test_libraries_query_lists_the_fixture_library_for_the_filter_dropdown(client):
    data = gql(client, "{ libraries { id path } }")
    assert len(data["libraries"]) == 1


def test_files_filter_by_content_matches_any_of_the_given_types(client):
    """The Files page's own "Content" chip (Base/Update/DLC/Bundle) is a client-side
    multi-select with OR semantics - this is the server-side filter it sends so
    sorting/paging stays correct instead of only filtering whatever page happened to
    load (the bug this was added to fix: picking "Base" still showed Update rows,
    because `FileFilter` had nothing for it and the chip silently did nothing)."""
    data = gql(client, """
        query { files(filter: {content: [BASE]}) { total items { filename } } }
    """)
    assert data["files"]["total"] == 1
    assert "0100000000010000" in data["files"]["items"][0]["filename"]

    data = gql(client, """
        query { files(filter: {content: [BASE, UPDATE]}) { total items { filename } } }
    """)
    assert data["files"]["total"] == 2


def test_files_filter_by_content_multi_matches_the_bundle(client):
    data = gql(client, """
        query { files(filter: {content: [MULTI]}) { total items { filename } } }
    """)
    assert data["files"]["total"] == 1
    assert "Multi Pack" in data["files"]["items"][0]["filename"]


def test_files_filter_by_content_empty_list_is_no_constraint(client):
    data = gql(client, """
        query { files(filter: {content: []}) { total } }
    """)
    assert data["files"]["total"] == 5


# --- Duplicates tab visual design, ported from upstream 2.5.0 ----------------------
#
# Upstream's own Duplicates tab is a side-by-side comparison table (one column per
# file, rows are the attributes that tell the copies apart, with the kept copy
# marked "Keep" and the losing one(s) marked "Delete" plus the reason). This fork's
# tab used to be a plain list of neutral "Keep this copy"/"Delete" button pairs with
# no indication of which copy would actually be kept - this ports the comparison
# layout onto this fork's own settings model (verification rank, then its own
# "prefer larger on tie"/compression-preference settings - not upstream's unrelated
# "prefer bundles"/added-time reasoning, which this fork's automatic resolution
# never uses).

def test_files_page_ships_the_comparison_table_and_bulk_delete_bar(client):
    html = client.get("/admin/files").get_data(as_text=True)
    # The per-file column header (Keep/Delete pill + reason + "..." actions) and the
    # attribute-row table upstream's own duplicates view uses, ported as-is.
    assert "function copyHeader" in html
    assert "function attributes" in html
    assert "files-cmp" in html
    # The bottom summary bar's bulk delete action, wired to the existing per-group
    # removal helper (previously dead code - defined but never bound to a button).
    assert 'class="btn btn-sm files-btn-danger files-delete"' in html
    assert "$('.files-delete').on('click', runRemoval);" in html
    # A second toggle alongside "Automatic resolution", matching upstream's own
    # two-control row ("Automatic deletion" + "Prefer bundles") - adapted to this
    # fork's actual tie-break setting rather than upstream's unrelated one.
    assert "preferLargerOnTieCheck" in html
    assert "Prefer larger on tie" in html


def test_duplicate_decides_reason_is_about_rank_not_time(client):
    """This fork's automatic duplicate resolution never compares when a copy was
    added (library.py's duplicate_winner_with_preferences ranks by verification
    status, then the compression preference, then size) - so the reason text next
    to a losing copy must never claim "Added later", only reasons this fork's own
    logic can actually produce."""
    html = client.get("/admin/files").get_data(as_text=True)
    assert "Added later" not in html
    for reason in ("Worse verification", "Not the preferred compression", "Smaller copy", "Not the recommended copy"):
        assert reason in html


# --- deleteFileRecord mutation ------------------------------------------------------

def test_delete_file_record_removes_the_row_and_the_file_from_disk(client, shop_app):
    before = gql(client, """
        query { files(filter: {filename: {eq: "Mystery File.nsp"}}) { items { id } } }
    """)
    file_id = before["files"]["items"][0]["id"]

    with shop_app.app.app_context():
        from db import Files
        filepath = Files.query.get(int(file_id)).filepath
    assert os.path.exists(filepath)

    data = gql(client, "mutation($id: ID!) { deleteFileRecord(fileId: $id) }", {"id": file_id})
    assert data["deleteFileRecord"] is True
    assert not os.path.exists(filepath)

    after = gql(client, """
        query { files(filter: {filename: {eq: "Mystery File.nsp"}}) { total } }
    """)
    assert after["files"]["total"] == 0


def test_delete_file_record_returns_false_for_an_unknown_id(client):
    data = gql(client, "mutation($id: ID!) { deleteFileRecord(fileId: $id) }", {"id": "999999"})
    assert data["deleteFileRecord"] is False


def test_delete_file_record_tolerates_the_file_already_being_gone_from_disk(client, shop_app):
    before = gql(client, """
        query { files(filter: {filename: {eq: "Mystery File.nsp"}}) { items { id } } }
    """)
    file_id = before["files"]["items"][0]["id"]

    with shop_app.app.app_context():
        from db import Files
        os.remove(Files.query.get(int(file_id)).filepath)

    data = gql(client, "mutation($id: ID!) { deleteFileRecord(fileId: $id) }", {"id": file_id})
    assert data["deleteFileRecord"] is True


def test_delete_file_record_requires_admin(shop_app):
    resp = shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303)
    resp = shop_app.client.post("/api/graphql", json={
        "query": "mutation($id: ID!) { deleteFileRecord(fileId: $id) }",
        "variables": {"id": "1"},
    })
    body = resp.get_json()
    assert body.get("errors"), "a non-admin must not be able to delete a file record"


# --- Setup page: Sphaira discovery flow --------------------------------------------

def test_setup_page_shows_the_native_ownfoil_menu_flow(client):
    html = client.get("/setup").get_data(as_text=True)
    assert "Menus" in html and "Ownfoil" in html
    # The old, per-file manual-mount flow is no longer the primary Sphaira instructions -
    # it only still appears, if at all, collapsed under "Legacy clients" for the separate
    # file-browser client, well after the new native-menu card.
    native_end = html.index("Add the server manually")
    legacy_start = html.find("Legacy clients")
    assert "Add / modify mounts" not in html[:native_end]
    if "Add / modify mounts" in html:
        assert legacy_start != -1 and html.index("Add / modify mounts") > legacy_start


def test_setup_page_shows_the_discovery_banner_when_discovery_is_enabled(client):
    html = client.get("/setup").get_data(as_text=True)
    assert "Discovery is enabled" in html
    assert "Discover local servers" in html


def test_setup_page_falls_back_to_manual_add_instructions_when_discovery_is_off(client):
    client.post("/api/settings/services", json={"discovery": {"enabled": False}})
    html = client.get("/setup").get_data(as_text=True)
    assert "Discovery is enabled" not in html


def test_setup_page_still_shows_discovery_when_viewed_through_the_configured_remote_host(client):
    """Discovery is a LAN-broadcast capability of the server, not a property of which URL
    the admin's own browser used to open /setup - an admin who always reaches the panel
    through their public domain (DuckDNS, etc.), even from the same WiFi the Switch is on,
    still needs these instructions. Regression guard for the bug where the Discovery
    section disappeared entirely whenever `shop.host` matched the request's Host header
    (it used to be gated by `show_local_tab`, which should only hide the *local
    address/port* fields, not Discovery itself)."""
    client.post("/api/settings/shop", json={"host": "example.duckdns.org"})
    # The test client's cookie jar scopes the session cookie to whatever Host the login
    # request used, so overriding the Host only on this later /setup request makes the jar
    # withhold the cookie and bounces us to the login page instead of exercising the real
    # view - log back in under the same overridden Host first so the cookie actually matches.
    overrides = {"environ_overrides": {"HTTP_HOST": "example.duckdns.org"}}
    resp = client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                        follow_redirects=False, **overrides)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    html = client.get("/setup", **overrides).get_data(as_text=True)
    assert "Discovery is enabled" in html
    assert "Discover local servers" in html


def test_setup_page_shows_both_local_and_remote_access_tabs_through_the_remote_host(client):
    """Same reasoning as the Discovery regression above, for the separate "Connection
    instructions" card's Local/Remote tabs further down the page: which URL loaded /setup
    says nothing about which access method actually works for the Switch, so both tabs -
    and a real local address to show in them - must be there regardless. Previously the
    "Local" tab (and local_address itself) vanished whenever `shop.host` matched the
    request's Host header."""
    client.post("/api/settings/shop", json={"host": "example.duckdns.org"})
    overrides = {"environ_overrides": {"HTTP_HOST": "example.duckdns.org"}}
    resp = client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                        follow_redirects=False, **overrides)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    html = client.get("/setup", **overrides).get_data(as_text=True)
    assert 'id="local-tab"' in html
    assert 'id="remote-tab"' in html
    # The "Add server manually" card's own local-address row is populated too, not just
    # the legacy tabs - local_address is computed unconditionally now.
    assert "Local address:" in html


def test_setup_page_renders_in_spanish_when_the_language_cookie_is_set(client):
    client.set_cookie("ownfoil_lang", "es")
    html = client.get("/setup").get_data(as_text=True)
    # Spot-check a handful of the setup.* translation keys actually used on the page.
    assert "Guía de configuración" in html
    assert "El descubrimiento está habilitado" in html
    assert "Agregar el servidor manualmente" in html
    assert "Clientes antiguos" in html
    # And the pink-highlighted connection details are still present either way.
    assert 'class="setup-highlight"' in html

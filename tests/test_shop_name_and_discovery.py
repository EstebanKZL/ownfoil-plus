"""Coverage for two features ported from upstream ownfoil 2.5.0: the configurable Shop
name (replacing the "Ownfoil-Plus" brand in the navbar/title/PWA meta) and the Services
admin page with its LAN discovery (UDP) toggle, used by Sphaira to find this shop on the
network without the console's user having to type an address.
"""
import json
import os
import socket

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


# --- Shop name -----------------------------------------------------------------------

def test_default_shop_name_is_ownfoil_plus_everywhere_it_is_shown(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    assert "<title>Ownfoil-Plus | Settings</title>" in html
    assert 'content="Ownfoil-Plus"' in html  # apple-mobile-web-app-title
    assert ">\n        Ownfoil-Plus\n        </a>" in html or "Ownfoil-Plus" in html


def test_shop_name_setting_defaults_to_empty_so_the_field_starts_blank(client):
    settings = client.get("/api/settings").get_json()
    assert settings["shop"]["name"] == ""


def test_setting_a_shop_name_replaces_the_brand_in_the_navbar_and_title(client):
    resp = client.post("/api/settings/shop", json={"name": "Esteban Switch Shop"})
    assert resp.get_json()["success"] is True

    settings = client.get("/api/settings").get_json()
    assert settings["shop"]["name"] == "Esteban Switch Shop"

    html = client.get("/admin/settings").get_data(as_text=True)
    assert "<title>Esteban Switch Shop | Settings</title>" in html
    # The navbar brand switches too - other mentions of the product name elsewhere on the
    # page (e.g. help text referencing "Ownfoil-Plus" by name) are unrelated and untouched.
    assert ">\n        Esteban Switch Shop\n        </a>" in html


def test_clearing_the_shop_name_falls_back_to_the_default_brand(client):
    client.post("/api/settings/shop", json={"name": "Temp Name"})
    client.post("/api/settings/shop", json={"name": ""})

    html = client.get("/admin/settings").get_data(as_text=True)
    assert "<title>Ownfoil-Plus | Settings</title>" in html


def test_shop_settings_save_still_keeps_the_other_shop_fields_intact(client):
    """The 'name' key was added to the save loop alongside host/public/motd - guard
    against it accidentally replacing them instead of sitting beside them."""
    client.post("/api/settings/shop", json={
        "name": "My Shop", "host": "myshop.example.com", "public": True, "motd": "hi",
    })
    settings = client.get("/api/settings").get_json()
    assert settings["shop"]["name"] == "My Shop"
    assert settings["shop"]["host"] == "myshop.example.com"
    assert settings["shop"]["public"] is True
    assert settings["shop"]["motd"] == "hi"


# --- Services page / API --------------------------------------------------------------

def test_services_page_requires_admin(shop_app):
    resp = shop_app.client.get("/admin/services", follow_redirects=False)
    assert resp.status_code in (302, 303)


def test_services_page_renders_for_admin_with_discovery_toggle(client):
    html = client.get("/admin/services").get_data(as_text=True)
    assert "discoveryEnabledCheck" in html
    assert "8465" in html  # the UDP port is shown in the help text


def test_services_page_shows_the_docker_note_as_a_warning_with_code_highlighting(client):
    """Matches upstream's own treatment of this note (a yellow alert with an icon and
    <code> highlighting on the Docker flags/compose key) - this had been downgraded to
    a plain blue alert with the markup stripped entirely, though the fork's own longer
    wording (which also covers the Windows firewall) was kept rather than replaced."""
    html = client.get("/admin/services").get_data(as_text=True)
    assert 'alert alert-warning' in html
    assert 'bi-exclamation-triangle-fill' in html
    assert '<code>network_mode: host</code>' in html
    assert '<code>--network host</code>' in html
    assert '<code>docker run</code>' in html
    # The Windows-firewall addition the fork made on top of upstream's note survives.
    assert 'firewall' in html.lower()


def test_services_nav_link_is_present_on_the_settings_sidebar(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    assert '/admin/services' in html


def test_discovery_enabled_by_default(client):
    settings = client.get("/api/settings").get_json()
    assert settings["services"]["discovery"]["enabled"] is True


def test_disabling_discovery_via_the_api_persists(client):
    resp = client.post("/api/settings/services", json={"discovery": {"enabled": False}})
    assert resp.get_json()["success"] is True

    settings = client.get("/api/settings").get_json()
    assert settings["services"]["discovery"]["enabled"] is False


def test_services_settings_ignore_an_unknown_service_key(client):
    """set_services_settings only updates keys already present in settings['services'] -
    an unrecognized service name in the payload must not get silently added."""
    client.post("/api/settings/services", json={"made_up_service": {"enabled": True}})
    settings = client.get("/api/settings").get_json()
    assert "made_up_service" not in settings["services"]


# --- Server UID ------------------------------------------------------------------------

def test_server_uid_is_minted_once_and_stable_across_reads(shop_app):
    import settings as settings_mod
    uid1 = settings_mod.get_server_uid()
    uid2 = settings_mod.get_server_uid()
    assert uid1 == uid2
    assert len(uid1) == 32  # uuid4().hex


# --- Discovery responder (real UDP socket, no network settings touched) ---------------

def test_discovery_payload_describes_this_shop(shop_app):
    import discovery
    payload = discovery.discovery_payload()
    assert payload["magic"] == "OWNFOIL"
    assert payload["name"] == "Ownfoil-Plus"
    assert payload["port"] == 8465
    assert "uid" in payload and len(payload["uid"]) == 32


def test_discovery_responder_answers_a_udp_discovery_request(shop_app):
    import discovery
    from constants import DISCOVERY_REQUEST

    responder = discovery.DiscoveryResponder(port=0)  # port 0: let the OS pick a free one
    assert responder.bind() is True
    responder.start()
    try:
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_sock.settimeout(5)
        client_sock.sendto(DISCOVERY_REQUEST, ('127.0.0.1', responder.port))
        data, _ = client_sock.recvfrom(4096)
        reply = json.loads(data.decode())
        assert reply["magic"] == "OWNFOIL"
        client_sock.close()
    finally:
        responder.stop()


def test_discovery_responder_ignores_a_request_with_the_wrong_magic_bytes(shop_app):
    import discovery

    responder = discovery.DiscoveryResponder(port=0)
    assert responder.bind() is True
    responder.start()
    try:
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_sock.settimeout(1)
        client_sock.sendto(b'NOT_A_REAL_REQUEST', ('127.0.0.1', responder.port))
        with pytest.raises(socket.timeout):
            client_sock.recvfrom(4096)
        client_sock.close()
    finally:
        responder.stop()


def test_reconcile_starts_and_stops_the_responder_to_match_settings(shop_app):
    import discovery
    import settings as settings_mod

    discovery.stop()  # clean slate regardless of what an earlier test left running
    try:
        settings_mod.set_services_settings({"discovery": {"enabled": True}})
        discovery.reconcile()
        assert discovery._responder is not None

        settings_mod.set_services_settings({"discovery": {"enabled": False}})
        discovery.reconcile()
        assert discovery._responder is None
    finally:
        discovery.stop()


# --- Duplicate tie-break controls follow auto-resolve ----------------------------------

def test_duplicate_tie_break_controls_are_disabled_when_auto_resolve_is_off(client):
    """library.management.duplicates.prefer_larger_on_tie and .compression_preference
    only ever take effect once auto_resolve is itself on (tasks.py's
    resolve_duplicate_files_task no-ops entirely while it's off) - the Settings page
    greys the two controls out to match, instead of leaving them checkable while
    inert."""
    html = client.get("/admin/settings").get_data(as_text=True)
    assert "function syncDuplicateTieBreakControls" in html
    assert "#preferMulticontentCheck').prop('disabled', !auto)" in html
    assert "#preferLargerOnTieCheck').prop('disabled', !auto)" in html
    assert "#compressionPreferenceSelect').prop('disabled', !auto)" in html
    assert "$('#autoResolveDuplicatesCheck').on('change', syncDuplicateTieBreakControls)" in html

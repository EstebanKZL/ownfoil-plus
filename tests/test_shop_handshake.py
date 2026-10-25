"""Coverage for the OPTIONS handshake on `/` (CHANGELOG 6.2.4.11): Sphaira's native
"Ownfoil" menu sends OPTIONS / before anything else, to learn the server's name, uid
and protocol version and decide whether it can talk to it. Without a route claiming
that method, Flask auto-answers OPTIONS with an empty 200 - Sphaira then "detects" the
server (sees a 200) but never proceeds to the GraphQL API, which is exactly the
"detects but doesn't connect" symptom reported against a real production shop, and
confirmed by its own access log showing nothing but repeated OPTIONS / with no
following POST /api/graphql - unlike upstream ownfoil, which answers this handshake.
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
    # A public shop, like the handshake's own happy path - the private-shop-specific
    # auth rules get their own tests below.
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    shop_app.client.post("/api/settings/shop", json={"public": True})
    return shop_app.client


def test_options_on_root_answers_the_handshake_instead_of_an_empty_200(client):
    resp = client.options("/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None, "an empty body is exactly the bug this guards against"
    assert set(body) >= {"uid", "name", "version", "protocol_version", "motd", "public",
                         "remote", "features"}
    assert len(body["uid"]) == 32
    assert body["protocol_version"] == 1
    assert body["features"]["shop"] is True
    assert body["features"]["resumable_download"] is True


def test_handshake_reports_the_configured_shop_name_and_motd(client):
    client.post("/api/settings/shop", json={"name": "Esteban Switch Shop", "motd": "hi there"})

    body = client.options("/").get_json()
    assert body["name"] == "Esteban Switch Shop"
    assert body["motd"] == "hi there"


def test_handshake_on_a_private_shop_requires_authentication(client):
    client.post("/api/settings/shop", json={"public": False})
    client.get("/logout")

    resp = client.options("/")
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


def test_handshake_on_a_private_shop_succeeds_with_basic_auth_for_a_shop_user(client):
    import base64
    client.post("/api/settings/shop", json={"public": False})
    client.get("/logout")

    creds = base64.b64encode(f"admin:{fixture.PASSWORDS['admin']}".encode()).decode()
    resp = client.options("/", headers={"Authorization": f"Basic {creds}"})
    assert resp.status_code == 200
    assert resp.get_json()["uid"]


def test_handshake_on_a_public_shop_needs_no_authentication(client):
    client.get("/logout")

    resp = client.options("/")
    assert resp.status_code == 200
    assert resp.get_json()["public"] is True

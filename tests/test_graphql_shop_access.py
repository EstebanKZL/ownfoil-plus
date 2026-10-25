"""Coverage for the GraphQL shop gate (auth.resolve_shop_caller / gql/view.py's
graphql_dispatch, gql/context.py's build_context): regression guard for a real bug
reported against a production shop.

Once the OPTIONS handshake (CHANGELOG 6.2.4.11) let a console reach the GraphQL API
at all, its queries kept 401ing - `graphql_dispatch`'s own gate only ever checked the
flask-login session cookie a browser carries, never the Basic Auth header a console
client (Sphaira, Tinfoil) sends instead, and never let a public shop's anonymous
reads through either, even though every other shop-facing route (file_access routes,
the OPTIONS handshake itself) already does both of those things. Confirmed against
the real shop's own access log: `OPTIONS /` now 200s, but the very next `POST
/api/graphql` still 401'd for the same request.
"""
import base64
import json

import fixture
import pytest


@pytest.fixture
def client(shop_app):
    return shop_app.client


def _basic(user, password):
    creds = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


def _query(client, query, headers=None):
    return client.get("/api/graphql", query_string={"query": query}, headers=headers or {})


TITLES_QUERY = "{ titles { items { titleId } } }"


def test_a_console_client_authenticates_to_graphql_with_basic_auth_on_a_private_shop(client):
    """The exact symptom reported: OPTIONS succeeds, but the GraphQL call right
    after it must not 401 for a shop user sending the same Basic Auth credentials."""
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    client.post("/api/settings/shop", json={"public": False})
    client.get("/logout")

    resp = _query(client, TITLES_QUERY, headers=_basic("shopper", fixture.PASSWORDS["shopper"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")


def test_an_admin_passes_basic_auth_without_explicit_shop_access(client):
    """An admin account always carries shop access elsewhere in the API (see
    signup_post) - the GraphQL gate must honor that too, not just users created
    with shop_access explicitly set."""
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    client.post("/api/settings/shop", json={"public": False})
    client.get("/logout")

    resp = _query(client, TITLES_QUERY, headers=_basic("admin", fixture.PASSWORDS["admin"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert "errors" not in resp.get_json()


def test_a_user_without_shop_access_is_forbidden_not_unauthorized(client):
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    client.post("/api/settings/shop", json={"public": False})
    client.get("/logout")

    resp = _query(client, TITLES_QUERY, headers=_basic("noshop", fixture.PASSWORDS["noshop"]))
    assert resp.status_code == 403, resp.get_data(as_text=True)


def test_an_unauthenticated_request_on_a_private_shop_gets_401_with_a_challenge(client):
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    client.post("/api/settings/shop", json={"public": False})
    client.get("/logout")

    resp = _query(client, TITLES_QUERY)
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


def test_an_unauthenticated_request_on_a_public_shop_still_reads(client):
    """A public shop lets anyone browse without credentials at all, the same way
    file_access routes already do - this is what lets an anonymous console query
    the catalogue once it's pointed at the shop, no login dialog involved."""
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    client.post("/api/settings/shop", json={"public": True})
    client.get("/logout")

    resp = _query(client, TITLES_QUERY)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert "errors" not in resp.get_json()


def test_a_logged_in_browser_session_still_works_without_any_basic_auth_header(client):
    """The fix adds a Basic Auth fallback - it must not have cost the browser's own
    session-cookie path, which carried every query before this change."""
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    client.post("/api/settings/shop", json={"public": False})

    resp = _query(client, TITLES_QUERY)  # still logged in, no Authorization header
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert "errors" not in resp.get_json()


def test_wrong_basic_auth_credentials_are_rejected(client):
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    client.post("/api/settings/shop", json={"public": False})
    client.get("/logout")

    resp = _query(client, TITLES_QUERY, headers=_basic("shopper", "wrong-password"))
    assert resp.status_code == 401


def test_a_mutation_still_requires_real_admin_rights_even_on_a_public_shop(client):
    """The shop-wide gate opening up for anonymous reads on a public shop must not
    also open up admin mutations - those stay behind the resolver's own ctx.can_admin
    check (see gql/mutations.py), independent of this endpoint-level gate."""
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    client.post("/api/settings/shop", json={"public": True})
    client.get("/logout")

    resp = client.post("/api/graphql", json={
        "query": 'mutation { resetLibraryTracking(confirm: "RESET") }'})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body.get("errors"), "an anonymous caller on a public shop must not be able to mutate"

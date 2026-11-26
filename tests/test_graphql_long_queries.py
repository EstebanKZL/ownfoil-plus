"""Long GraphQL queries never reach gunicorn as a GET it refuses.

Gunicorn answered "Request Line is too large (4789 > 4094)": Files batches one alias per
watched task into a single query (checkWatched), and a list fetching icons does the
same per title - sent by GET, dozens of them overflow the request line. The pages now
send a long query by POST (static/js/graphql.js), and gunicorn takes a longer line.
"""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_every_page_has_the_one_query_helper():
    head = _read("app", "templates", "base.html").split("</head>")[0]
    assert "js/graphql.js" in head
    js = _read("app", "static", "js", "graphql.js")
    assert "function gqlRequest" in js and "GQL_MAX_GET_URL = 2000" in js
    assert "method: 'POST'" in js


def test_no_page_builds_a_graphql_get_by_hand():
    js_dir = os.path.join(ROOT, "app", "static", "js")
    for name in os.listdir(js_dir):
        if name.endswith(".js") and name != "graphql.js":
            assert not re.search(r"fetch\('/api/graphql\?", _read("app", "static", "js", name)), name


def test_gunicorn_takes_a_longer_request_line():
    assert "'limit_request_line': 8190" in _read("app", "run.py")


def test_a_query_can_be_sent_by_post(shop_app):
    import fixture
    client = shop_app.client
    client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    aliases = " ".join(f"t{i}: task(id: {i + 1}) {{ status }}" for i in range(80))
    resp = client.post("/api/graphql", json={"query": "{ " + aliases + " }"})
    assert resp.status_code == 200
    assert "errors" not in resp.get_json()

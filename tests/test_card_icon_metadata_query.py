"""Card and Icon view covers now open the same metadata modal the List view's info
button does, on click. This pins the real CARDS_QUERY/ICONS_QUERY strings from
app/templates/index.html - with the enriched fields (description, developer,
publisher, releaseDate, category, numberOfPlayers, rating, languages, size,
screenshots) the modal needs - against the actual schema, so a future field rename
surfaces here instead of only as a blank modal in the browser.
"""
import json
import types

import pytest

import db as db_mod
import titledb
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC
from db import Apps, Titles, db, init_db
from gql import graphql_dispatch

ALPHA = "0100000000AAAAA0"[:16]
ALPHA_DLC = ALPHA[:-4] + "1001"

TITLEDB_JSON = {
    ALPHA: {"id": ALPHA, "name": "Alpha Game", "description": "Alpha desc",
            "developer": "Dev Co", "publisher": "Pub Co", "releaseDate": "20220624",
            "category": ["Action", "Adventure"], "numberOfPlayers": "1-4", "rating": "Teen",
            "languages": ["en", "es"], "size": "13547089920",
            "screenshots": ["https://img/s1.jpg"]},
    ALPHA_DLC: {"id": ALPHA_DLC, "name": "Alpha DLC", "description": "DLC desc",
               "category": ["Action"], "screenshots": ["https://img/dlc1.jpg"]},
}

CNMTS_JSON = {
    ALPHA_DLC.lower(): {"0": {"titleId": ALPHA_DLC.lower(), "titleType": 130,
                              "version": 0, "otherApplicationId": ALPHA.lower()}},
}

# The exact production query strings from app/templates/index.html.
CARDS_QUERY = """
    query Cards($page: Int!, $pageSize: Int!, $appType: [AppType!], $search: String,
                $owned: Boolean, $upToDate: Boolean, $complete: Boolean) {
        apps(groupByAppId: true, orderBy: {field: NAME}, page: $page, pageSize: $pageSize,
             appType: $appType, search: $search, owned: $owned,
             upToDate: $upToDate, complete: $complete) {
            total
            items {
                appId
                appType
                owned
                titledb {
                    name description developer publisher releaseDate
                    category numberOfPlayers rating languages size screenshots
                }
                title { titleId name ownership { haveBase upToDate complete } }
                versions { version owned releaseDate }
            }
        }
    }"""

ICONS_QUERY = """
    query Icons($page: Int!, $pageSize: Int!, $appType: [AppType!], $search: String,
                $owned: Boolean, $upToDate: Boolean, $complete: Boolean) {
        apps(groupByAppId: true, orderBy: {field: NAME}, page: $page, pageSize: $pageSize,
             appType: $appType, search: $search, owned: $owned,
             upToDate: $upToDate, complete: $complete) {
            total
            items {
                appId
                appType
                titledb {
                    name description developer publisher releaseDate
                    category numberOfPlayers rating languages size screenshots
                }
                title { titleId name }
            }
        }
    }"""


@pytest.fixture
def library(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))

    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    app.add_url_rule("/api/graphql", view_func=graphql_dispatch, methods=["GET", "POST"])
    init_db(app)

    region_file = titledb_dir / "titles.US.en.json"
    region_file.write_text(json.dumps(TITLEDB_JSON))
    (titledb_dir / "cnmts.json").write_text(json.dumps(CNMTS_JSON))
    (titledb_dir / "versions.json").write_text("{}")

    with app.app_context():
        titledb.store.import_from_json(str(region_file), "US.en")
        title = Titles(title_id=ALPHA, have_base=True, up_to_date=True, complete=True)
        db.session.add(title)
        db.session.flush()
        base_app = Apps(title_id=title.id, app_id=ALPHA, app_version="0",
                        app_type=APP_TYPE_BASE, owned=True)
        dlc_app = Apps(title_id=title.id, app_id=ALPHA_DLC, app_version="0",
                       app_type=APP_TYPE_DLC, owned=True)
        db.session.add_all([base_app, dlc_app])
        db.session.commit()

    return types.SimpleNamespace(app=app, client=app.test_client())


def _run(library, query, **variables):
    variables.setdefault("page", 1)
    variables.setdefault("pageSize", 20)
    variables.setdefault("appType", [APP_TYPE_BASE, APP_TYPE_DLC])
    resp = library.client.get("/api/graphql", query_string={
        "query": query, "variables": json.dumps(variables)})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    return body["data"]["apps"]["items"]


def test_cards_query_returns_the_enriched_fields_for_a_base_app(library):
    items = _run(library, CARDS_QUERY)
    base = next(i for i in items if i["appType"] == "BASE")

    td = base["titledb"]
    assert td["description"] == "Alpha desc"
    assert td["developer"] == "Dev Co"
    assert td["publisher"] == "Pub Co"
    assert td["releaseDate"] == "20220624"
    assert td["category"] == ["Action", "Adventure"]
    assert td["numberOfPlayers"] == "1-4"
    assert td["rating"] == "Teen"
    assert td["languages"] == ["en", "es"]
    assert td["size"] == "13547089920"
    assert td["screenshots"] == ["https://img/s1.jpg"]


def test_cards_query_returns_the_enriched_fields_for_a_dlc_app(library):
    items = _run(library, CARDS_QUERY)
    dlc = next(i for i in items if i["appType"] == "DLC")

    assert dlc["titledb"]["category"] == ["Action"]
    assert dlc["titledb"]["screenshots"] == ["https://img/dlc1.jpg"]


def test_icons_query_returns_the_enriched_fields_too(library):
    """Icon view previously fetched almost nothing (just the icon URL) - it needs
    the same detail fields as Card view now, for the same cover-click modal."""
    items = _run(library, ICONS_QUERY)
    base = next(i for i in items if i["appType"] == "BASE")

    td = base["titledb"]
    assert td["description"] == "Alpha desc"
    assert td["numberOfPlayers"] == "1-4"
    assert td["screenshots"] == ["https://img/s1.jpg"]
    assert base["title"]["titleId"] == ALPHA


def test_neither_query_fetches_titledbs_own_image_urls_anymore(library):
    """Card and Icon views build cover URLs from the local cache proxy (title/app id
    + /api/titledb-image/.../banner|icon) client-side now, not titledb's own
    bannerUrl/iconUrl - fetching those would just be unused payload."""
    assert "bannerUrl" not in CARDS_QUERY
    assert "iconUrl" not in CARDS_QUERY
    assert "iconUrl" not in ICONS_QUERY


# --- Regression guard: the query strings *actually shipped* in index.html, not just
# this file's own hand-kept copy above ------------------------------------------------

def _extract_query(js_source, const_name):
    import re
    m = re.search(rf"const {const_name} = `(.*?)`;", js_source, re.DOTALL)
    assert m, f"{const_name} not found in index.html - the template's own definition may have moved"
    return m.group(1)


def test_the_real_template_file_has_syntactically_valid_cards_and_icons_queries(library):
    """The hand-kept CARDS_QUERY/ICONS_QUERY constants above are useful for readable
    assertions, but they're a separate copy - a mistake in the real template (like a
    JS-style `//` comment accidentally left inside the GraphQL string, which template
    literals don't strip and GraphQL has no syntax for) would still pass every test in
    this file while breaking Card/Icon view outright in the browser. This extracts the
    *actual* query strings from app/templates/index.html and sends them to the real
    schema, so that specific class of bug can't slip through silently again."""
    import os
    template_path = os.path.join(os.path.dirname(__file__), "..", "app", "templates", "index.html")
    with open(template_path) as f:
        source = f.read()

    real_cards_query = _extract_query(source, "CARDS_QUERY")
    real_icons_query = _extract_query(source, "ICONS_QUERY")

    for name, real_query in [("CARDS_QUERY", real_cards_query), ("ICONS_QUERY", real_icons_query)]:
        resp = library.client.get("/api/graphql", query_string={
            "query": real_query,
            "variables": json.dumps({"page": 1, "pageSize": 5, "appType": [APP_TYPE_BASE, APP_TYPE_DLC]}),
        })
        assert resp.status_code == 200, f"{name}: {resp.get_data(as_text=True)}"
        body = resp.get_json()
        assert "errors" not in body, f"{name} has a real syntax/field error: {body.get('errors')}"
        assert body["data"]["apps"]["items"], f"{name} returned no items against the seeded fixture"

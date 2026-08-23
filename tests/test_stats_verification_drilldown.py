"""End-to-end check for the query the Stats page's verification drill-down modal runs:
`files(filter: {verificationStatus: ...})`, naming the title behind each file. Uses the
same fixture pattern as test_gql_graph.py, since it exercises the same GraphQL entrypoint
against a real titledb attach.
"""
import json
import types

import pytest

import db as db_mod
import titledb
from app import create_app
from constants import APP_TYPE_BASE
from db import Apps, Files, Libraries, Titles, db, init_db
from gql import graphql_dispatch

ALPHA = "0100000000AAAAA0"[:16]
BETA = "0100000000BBBBB0"[:16]

TITLEDB_JSON = {
    ALPHA: {"id": ALPHA, "name": "Alpha Game", "publisher": "Nintendo"},
    BETA: {"id": BETA, "name": "Beta Game", "publisher": "Nintendo"},
}


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
    (titledb_dir / "cnmts.json").write_text("{}")
    (titledb_dir / "versions.json").write_text("{}")
    with app.app_context():
        titledb.store.import_from_json(str(region_file), "US.en")

        library_row = Libraries(path=str(tmp_path / "games"))
        db.session.add(library_row)
        db.session.flush()

        # Alpha: verified valid. Beta: never verified.
        alpha_title = Titles(title_id=ALPHA, have_base=True)
        beta_title = Titles(title_id=BETA, have_base=True)
        db.session.add_all([alpha_title, beta_title])
        db.session.flush()

        alpha_app = Apps(title_id=alpha_title.id, app_id=ALPHA, app_version="0",
                         app_type=APP_TYPE_BASE, owned=True)
        beta_app = Apps(title_id=beta_title.id, app_id=BETA, app_version="0",
                        app_type=APP_TYPE_BASE, owned=True)
        db.session.add_all([alpha_app, beta_app])

        alpha_file = Files(library_id=library_row.id,
                           filepath=str(tmp_path / "games" / "Alpha.nsp"),
                           filename="Alpha.nsp", extension="nsp", size=3000,
                           identified=True, signature_valid=True, hash_valid=True)
        beta_file = Files(library_id=library_row.id,
                          filepath=str(tmp_path / "games" / "Beta.nsp"),
                          filename="Beta.nsp", extension="nsp", size=1000,
                          identified=True)
        db.session.add_all([alpha_file, beta_file])
        db.session.flush()
        alpha_app.files.append(alpha_file)
        beta_app.files.append(beta_file)
        db.session.commit()

    return types.SimpleNamespace(app=app, client=app.test_client())


def query(library, text_query, **variables):
    params = {"query": text_query}
    if variables:
        params["variables"] = json.dumps(variables)
    resp = library.client.get("/api/graphql", query_string=params)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body["errors"]
    return body["data"]


FILES_BY_STATUS_QUERY = """
    query FilesByStatus($status: VerificationStatus!, $page: Int!, $pageSize: Int!) {
        files(filter: {verificationStatus: $status}, page: $page, pageSize: $pageSize,
              orderBy: {field: ADDED_AT, direction: DESC}) {
            total
            items { filename size apps { appType title { name } } }
        }
    }"""


def test_valid_status_returns_only_the_verified_title(library):
    data = query(library, FILES_BY_STATUS_QUERY, status="VALID", page=1, pageSize=10)
    items = data["files"]["items"]
    assert data["files"]["total"] == 1
    assert items[0]["filename"] == "Alpha.nsp"
    assert items[0]["apps"][0]["title"]["name"] == "Alpha Game"


def test_unverified_status_returns_the_unchecked_title(library):
    data = query(library, FILES_BY_STATUS_QUERY, status="UNVERIFIED", page=1, pageSize=10)
    items = data["files"]["items"]
    assert data["files"]["total"] == 1
    assert items[0]["filename"] == "Beta.nsp"
    assert items[0]["apps"][0]["title"]["name"] == "Beta Game"


def test_pagination_fields_are_present_for_the_modals_page_count(library):
    data = query(library, FILES_BY_STATUS_QUERY, status="VALID", page=1, pageSize=1)
    assert data["files"]["total"] == 1
    assert len(data["files"]["items"]) == 1

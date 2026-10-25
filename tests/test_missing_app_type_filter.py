"""titles(missingAppType:) answers the exact question the Stats page's "App Types"
table raises but doesn't answer on its own: BASE shows 217 registered / 215 owned -
which 2 titles is that gap? An app row can exist (and count toward "registered")
without being owned - e.g. a title an update or DLC was scanned for, where the base
game's own file was never added.
"""
import json
import types

import pytest

import db as db_mod
import titledb
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC, APP_TYPE_UPD
from db import Apps, Files, Libraries, Titles, db, init_db
from gql import graphql_dispatch

ALPHA = "0100000000AAAAA0"[:16]  # Owns base fully - not in the gap for anything
BETA = "0100000000BBBBB0"[:16]   # Owns an update, but base is registered-not-owned
GAMMA = "0100000000CCCCC0"[:16]  # Owns nothing at all - no apps registered here either

TITLEDB_JSON = {t: {"id": t, "name": f"Title {t}"} for t in (ALPHA, BETA, GAMMA)}

MISSING_QUERY = """
    query($type: AppType, $owned: Boolean) {
        titles(owned: $owned, missingAppType: $type, page: 1, pageSize: 20, orderBy: {field: NAME}) {
            total
            items { titleId name }
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
    (titledb_dir / "cnmts.json").write_text("{}")
    (titledb_dir / "versions.json").write_text("{}")

    with app.app_context():
        titledb.store.import_from_json(str(region_file), "US.en")
        library_row = Libraries(path=str(tmp_path / "games"))
        db.session.add(library_row)
        db.session.flush()

        def seed_file(app_row, name):
            path = tmp_path / name
            path.write_bytes(b"X")
            f = Files(library_id=library_row.id, filepath=str(path), filename=name,
                     extension="nsp", size=1, identified=True)
            db.session.add(f)
            db.session.flush()
            app_row.files.append(f)

        alpha = Titles(title_id=ALPHA, have_base=True)
        beta = Titles(title_id=BETA, have_base=True)
        gamma = Titles(title_id=GAMMA, have_base=False)
        db.session.add_all([alpha, beta, gamma])
        db.session.flush()

        # Alpha: owns its base outright - not part of any gap.
        alpha_base = Apps(title_id=alpha.id, app_id=ALPHA, app_version="0",
                          app_type=APP_TYPE_BASE, owned=True)
        db.session.add(alpha_base)
        db.session.flush()
        seed_file(alpha_base, "AlphaBase.nsp")

        # Beta: owns an update, but its base app row is registered, not owned - the
        # exact "217 registered / 215 owned" gap scenario for BASE.
        beta_base = Apps(title_id=beta.id, app_id=BETA, app_version="0",
                         app_type=APP_TYPE_BASE, owned=False)
        beta_update = Apps(title_id=beta.id, app_id=BETA[:-4] + "1000", app_version="65536",
                           app_type=APP_TYPE_UPD, owned=True)
        db.session.add_all([beta_base, beta_update])
        db.session.flush()
        seed_file(beta_update, "BetaUpdate.nsp")

        # Gamma: owns nothing, no apps registered for it at all - shouldn't show up
        # in the missing-BASE gap either, since it was never "registered" in the
        # first place (nothing to be missing from).
        db.session.commit()

    return types.SimpleNamespace(app=app, client=app.test_client())


def _query(library, app_type=None, owned=True):
    resp = library.client.get("/api/graphql", query_string={
        "query": MISSING_QUERY,
        "variables": json.dumps({"type": app_type, "owned": owned}),
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    return {t["titleId"] for t in body["data"]["titles"]["items"]}


def test_missing_base_finds_only_the_title_with_a_registered_but_unowned_base(library):
    assert _query(library, "BASE") == {BETA}


def test_a_title_that_fully_owns_its_base_is_not_in_the_gap(library):
    result = _query(library, "BASE")
    assert ALPHA not in result


def test_a_title_with_nothing_registered_at_all_is_not_in_the_gap_either(library):
    """Gamma owns nothing and has no app rows for any type - there's nothing for it
    to be "registered but not owned" in, so it correctly never appears."""
    for app_type in ("BASE", "UPDATE", "DLC"):
        result = _query(library, app_type)
        assert GAMMA not in result


def test_missing_update_and_dlc_return_nothing_here_since_none_are_registered_unowned(library):
    assert _query(library, "UPDATE") == set()
    assert _query(library, "DLC") == set()


def test_missing_app_type_with_owned_false_matches_nothing(library):
    """Same rule as libraryHealth: only meaningful for owned:true - a catalogue-only
    query has no apps to inspect at all."""
    assert _query(library, "BASE", owned=False) == set()


def test_omitting_missing_app_type_returns_everything_unfiltered(library):
    assert _query(library, None) == {ALPHA, BETA, GAMMA}

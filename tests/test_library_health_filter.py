"""titles(libraryHealth:) buckets every owned title into exactly one of four states,
checked in priority order (Corrupt > Repack > Complete > Incomplete), based on the
verification status of every file attached to any of its apps (base, update, DLC
alike) plus the existing up_to_date/complete ownership flags. Requested for the List
view, which previously had no filter at all unlike Card/Icon.
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

ALPHA = "0100000000AAAAA0"[:16]    # Complete: up to date, all DLC, nothing corrupt/repack
BETA = "0100000000BBBBB0"[:16]     # Incomplete: missing an update, nothing corrupt/repack
GAMMA = "0100000000CCCCC0"[:16]    # Corrupt: otherwise "complete", but one file is corrupt
DELTA = "0100000000DDDDD0"[:16]    # Repack: otherwise "complete", but one file is a repack
EPSILON = "0100000000EEEEE0"[:16]  # Both corrupt and repack files - corrupt wins priority

TITLEDB_JSON = {t: {"id": t, "name": f"Title {t}"} for t in (ALPHA, BETA, GAMMA, DELTA, EPSILON)}

VALID = dict(signature_valid=True, hash_valid=True)
CORRUPT = dict(signature_valid=True, hash_valid=False, hash_modified=False)
REPACK = dict(signature_valid=False, hash_valid=True)

LIBRARY_HEALTH_QUERY = """
    query($health: LibraryHealth, $owned: Boolean) {
        titles(owned: $owned, libraryHealth: $health, page: 1, pageSize: 20, orderBy: {field: NAME}) {
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

        def seed_title(title_id, up_to_date, complete, base_verdict):
            title = Titles(title_id=title_id, have_base=True,
                           up_to_date=up_to_date, complete=complete)
            db.session.add(title)
            db.session.flush()
            base_app = Apps(title_id=title.id, app_id=title_id, app_version="0",
                            app_type=APP_TYPE_BASE, owned=True)
            db.session.add(base_app)
            db.session.flush()
            f = Files(library_id=library_row.id, filepath=str(tmp_path / f"{title_id}.nsp"),
                     filename=f"{title_id}.nsp", extension="nsp", size=1000,
                     identified=True, **base_verdict)
            db.session.add(f)
            db.session.flush()
            base_app.files.append(f)
            db.session.commit()
            return title, base_app

        seed_title(ALPHA, up_to_date=True, complete=True, base_verdict=VALID)
        seed_title(BETA, up_to_date=False, complete=True, base_verdict=VALID)
        seed_title(GAMMA, up_to_date=True, complete=True, base_verdict=CORRUPT)
        seed_title(DELTA, up_to_date=True, complete=True, base_verdict=REPACK)

        # Epsilon: two files, one corrupt and one repack - corrupt must win.
        epsilon_title, epsilon_app = seed_title(EPSILON, up_to_date=True, complete=True,
                                                base_verdict=CORRUPT)
        f2 = Files(library_id=library_row.id, filepath=str(tmp_path / f"{EPSILON}-2.nsp"),
                  filename=f"{EPSILON}-2.nsp", extension="nsp", size=1000,
                  identified=True, **REPACK)
        db.session.add(f2)
        db.session.flush()
        epsilon_app.files.append(f2)
        db.session.commit()

    return types.SimpleNamespace(app=app, client=app.test_client())


def _query(library, health=None, owned=True):
    resp = library.client.get("/api/graphql", query_string={
        "query": LIBRARY_HEALTH_QUERY,
        "variables": json.dumps({"health": health, "owned": owned}),
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    return {t["titleId"] for t in body["data"]["titles"]["items"]}


def test_complete_matches_only_the_fully_healthy_up_to_date_title(library):
    assert _query(library, "COMPLETE") == {ALPHA}


def test_incomplete_matches_the_title_missing_an_update(library):
    assert _query(library, "INCOMPLETE") == {BETA}


def test_corrupt_matches_titles_with_any_corrupt_file(library):
    """Both Gamma (corrupt only) and Epsilon (corrupt + repack) land here - corrupt
    always wins the priority order, regardless of what else is going on."""
    assert _query(library, "CORRUPT") == {GAMMA, EPSILON}


def test_repack_matches_only_the_title_whose_worst_problem_is_a_repack(library):
    """Delta has a repack file and nothing corrupt. Epsilon has both, but it was
    already claimed by Corrupt above - it must NOT also appear here."""
    assert _query(library, "REPACK") == {DELTA}


def test_every_title_is_covered_by_exactly_one_bucket(library):
    """The four buckets partition the whole set - nothing missing, nothing doubled."""
    buckets = [_query(library, h) for h in ("COMPLETE", "INCOMPLETE", "CORRUPT", "REPACK")]
    all_matched = set().union(*buckets)
    assert all_matched == {ALPHA, BETA, GAMMA, DELTA, EPSILON}
    # No title in more than one bucket.
    total_membership = sum(len(b) for b in buckets)
    assert total_membership == len(all_matched)


def test_library_health_with_owned_false_matches_nothing_rather_than_being_ignored(library):
    """A catalogue-only (unowned) title has no apps/files to inspect - explicitly
    matching nothing here is safer than silently pretending the filter wasn't given,
    which would return the *unfiltered* unowned catalogue instead."""
    assert _query(library, "COMPLETE", owned=False) == set()


def test_omitting_library_health_returns_everything_unfiltered(library):
    assert _query(library, None) == {ALPHA, BETA, GAMMA, DELTA, EPSILON}

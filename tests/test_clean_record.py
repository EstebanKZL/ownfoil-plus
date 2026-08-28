"""The Stats page's per-library detail view (titles(libraryPath:)) and the two pairs
of admin-only actions it exposes on each app row:

- cleanAppRecord / cleanTitleRecord: database-only. Forgets the tracked row(s) and
  file(s), never touches anything on disk - for recovering a stuck or inconsistent
  entry (a leftover DB row with nothing real behind it) without risking a real file
  still on disk.
- deleteAppRecord / deleteTitleRecord: real, irreversible. Deletes the underlying
  file(s) from disk *and* forgets the tracked row(s) together, in one action - no
  separate confirmation for the database half, it always goes with the file.

Both pairs share the same "one specific app" vs. "this title's base plus every
update and DLC together" shape. Neither pair is gated behind a settings toggle
(admin access is the only gate) - the toggle that used to exist was removed.
"""
import json
import os
import types

import pytest

import db as db_mod
import titledb
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC, APP_TYPE_UPD
from db import Apps, Files, Libraries, Titles, db, init_db
from gql import graphql_dispatch

ALPHA = "0100000000AAAAA0"[:16]
BETA = "0100000000BBBBB0"[:16]

TITLEDB_JSON = {t: {"id": t, "name": f"Title {t}"} for t in (ALPHA, BETA)}

LIBRARY_PATH_QUERY = """
    query($path: String, $owned: Boolean) {
        titles(owned: $owned, libraryPath: $path, page: 1, pageSize: 20, orderBy: {field: NAME}) {
            total
            items { titleId name }
        }
    }"""

CLEAN_APP_MUTATION = """
    mutation($id: ID!) { cleanAppRecord(appRowId: $id) }"""
CLEAN_TITLE_MUTATION = """
    mutation($id: String!) { cleanTitleRecord(titleId: $id) }"""
DELETE_APP_MUTATION = """
    mutation($id: ID!) { deleteAppRecord(appRowId: $id) }"""
DELETE_TITLE_MUTATION = """
    mutation($id: String!) { deleteTitleRecord(titleId: $id) }"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    lib_a_dir = tmp_path / "games_a"
    lib_b_dir = tmp_path / "games_b"
    lib_a_dir.mkdir()
    lib_b_dir.mkdir()
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
        lib_a = Libraries(path=str(lib_a_dir))
        lib_b = Libraries(path=str(lib_b_dir))
        db.session.add_all([lib_a, lib_b])
        db.session.flush()

        def seed_file(library_row, folder, app_row, name):
            path = folder / name
            path.write_bytes(b"X")
            f = Files(library_id=library_row.id, filepath=str(path), filename=name,
                     extension="nsp", size=1, identified=True)
            db.session.add(f)
            db.session.flush()
            app_row.files.append(f)
            return f

        alpha_title = Titles(title_id=ALPHA, have_base=True)
        beta_title = Titles(title_id=BETA, have_base=True)
        db.session.add_all([alpha_title, beta_title])
        db.session.flush()

        # Alpha: base in library A, one update (v0) also in library A.
        alpha_base = Apps(title_id=alpha_title.id, app_id=ALPHA, app_version="0",
                          app_type=APP_TYPE_BASE, owned=True)
        alpha_update = Apps(title_id=alpha_title.id, app_id=ALPHA[:-4] + "1000",
                            app_version="65536", app_type=APP_TYPE_UPD, owned=True)
        db.session.add_all([alpha_base, alpha_update])
        db.session.flush()
        alpha_base_file = seed_file(lib_a, lib_a_dir, alpha_base, "AlphaBase.nsp")
        alpha_update_file = seed_file(lib_a, lib_a_dir, alpha_update, "AlphaUpdate.nsp")

        # Beta: base in library B only - never appears in library A's detail view.
        beta_base = Apps(title_id=beta_title.id, app_id=BETA, app_version="0",
                         app_type=APP_TYPE_BASE, owned=True)
        db.session.add(beta_base)
        db.session.flush()
        beta_base_file = seed_file(lib_b, lib_b_dir, beta_base, "BetaBase.nsp")

        db.session.commit()

        ids = types.SimpleNamespace(
            alpha_title_id=alpha_title.id, beta_title_id=beta_title.id,
            alpha_base_row_id=alpha_base.id, alpha_update_row_id=alpha_update.id,
            beta_base_row_id=beta_base.id,
            alpha_base_file_id=alpha_base_file.id, alpha_update_file_id=alpha_update_file.id,
            alpha_base_filepath=alpha_base_file.filepath, alpha_update_filepath=alpha_update_file.filepath,
            beta_base_filepath=beta_base_file.filepath,
        )

    return types.SimpleNamespace(app=app, client=app.test_client(),
                                 lib_a_path=str(lib_a_dir), lib_b_path=str(lib_b_dir), ids=ids)


def _query(env, path=None, owned=True):
    resp = env.client.get("/api/graphql", query_string={
        "query": LIBRARY_PATH_QUERY, "variables": json.dumps({"path": path, "owned": owned})})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body.get("errors")
    return {t["titleId"] for t in body["data"]["titles"]["items"]}


def _mutate(env, query, **variables):
    resp = env.client.post("/api/graphql", json={"query": query, "variables": variables})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


# --- titles(libraryPath:) -------------------------------------------------------------

def test_library_path_finds_only_titles_with_a_file_in_that_library(env):
    assert _query(env, env.lib_a_path) == {ALPHA}
    assert _query(env, env.lib_b_path) == {BETA}


def test_library_path_with_owned_false_matches_nothing(env):
    assert _query(env, env.lib_a_path, owned=False) == set()


def test_omitting_library_path_returns_everything_unfiltered(env):
    assert _query(env, None) == {ALPHA, BETA}


# --- db.clean_app_record / clean_title_apps: database only, disk untouched ----------

def test_clean_app_record_removes_only_that_apps_files_and_row(env):
    with env.app.app_context():
        result = db_mod.clean_app_record(env.ids.alpha_update_row_id)

        assert result is True
        assert db.session.get(Apps, env.ids.alpha_update_row_id) is None
        assert db.session.get(Files, env.ids.alpha_update_file_id) is None
        # The base app and its file are untouched.
        assert db.session.get(Apps, env.ids.alpha_base_row_id) is not None
        assert db.session.get(Files, env.ids.alpha_base_file_id) is not None


def test_clean_app_record_never_touches_the_file_on_disk(env):
    with env.app.app_context():
        db_mod.clean_app_record(env.ids.alpha_update_row_id)

        assert os.path.exists(env.ids.alpha_update_filepath), (
            "clean_app_record must never delete the real file - only the tracked row"
        )


def test_clean_app_record_returns_false_for_an_unknown_row(env):
    with env.app.app_context():
        assert db_mod.clean_app_record(999999) is False


def test_clean_title_apps_removes_every_app_and_file_under_that_title(env):
    with env.app.app_context():
        count = db_mod.clean_title_apps(ALPHA)

        assert count == 2  # base + the one update
        assert db.session.get(Apps, env.ids.alpha_base_row_id) is None
        assert db.session.get(Apps, env.ids.alpha_update_row_id) is None
        assert db.session.get(Files, env.ids.alpha_base_file_id) is None
        assert db.session.get(Files, env.ids.alpha_update_file_id) is None
        # The title row itself survives.
        assert db.session.get(Titles, env.ids.alpha_title_id) is not None
        # A different title's apps are untouched.
        assert db.session.get(Apps, env.ids.beta_base_row_id) is not None


def test_clean_title_apps_never_touches_files_on_disk(env):
    with env.app.app_context():
        db_mod.clean_title_apps(ALPHA)

        assert os.path.exists(env.ids.alpha_base_filepath)
        assert os.path.exists(env.ids.alpha_update_filepath)


def test_clean_title_apps_on_a_title_with_nothing_tracked_is_a_harmless_no_op(env):
    with env.app.app_context():
        empty_title = Titles(title_id="0100000000FFFFF0")
        db.session.add(empty_title)
        db.session.commit()

        assert db_mod.clean_title_apps("0100000000FFFFF0") == 0


# --- db.delete_app_record / delete_title_apps: real, deletes the file too -----------

def test_delete_app_record_removes_the_row_and_the_real_file(env):
    with env.app.app_context():
        result = db_mod.delete_app_record(env.ids.alpha_update_row_id)

        assert result is True
        assert db.session.get(Apps, env.ids.alpha_update_row_id) is None
        assert db.session.get(Files, env.ids.alpha_update_file_id) is None
        assert not os.path.exists(env.ids.alpha_update_filepath), (
            "deleteAppRecord must actually remove the file from disk"
        )
        # The base app, its file, and the file itself are untouched.
        assert db.session.get(Apps, env.ids.alpha_base_row_id) is not None
        assert os.path.exists(env.ids.alpha_base_filepath)


def test_delete_app_record_returns_false_for_an_unknown_row(env):
    with env.app.app_context():
        assert db_mod.delete_app_record(999999) is False


def test_delete_app_record_tolerates_a_file_already_gone_from_disk(env):
    """A file removed by hand outside ownfoil (or already cleaned up some other way)
    must not block the row from being deleted - there's nothing left to delete on
    disk, but the tracked record still needs to go."""
    with env.app.app_context():
        os.remove(env.ids.alpha_update_filepath)

        result = db_mod.delete_app_record(env.ids.alpha_update_row_id)

        assert result is True
        assert db.session.get(Apps, env.ids.alpha_update_row_id) is None


def test_delete_title_apps_removes_every_row_and_every_real_file(env):
    with env.app.app_context():
        count = db_mod.delete_title_apps(ALPHA)

        assert count == 2
        assert db.session.get(Apps, env.ids.alpha_base_row_id) is None
        assert db.session.get(Apps, env.ids.alpha_update_row_id) is None
        assert not os.path.exists(env.ids.alpha_base_filepath)
        assert not os.path.exists(env.ids.alpha_update_filepath)
        # The title row survives; a different title's app and file are untouched.
        assert db.session.get(Titles, env.ids.alpha_title_id) is not None
        assert db.session.get(Apps, env.ids.beta_base_row_id) is not None
        assert os.path.exists(env.ids.beta_base_filepath)


def test_delete_title_apps_on_a_title_with_nothing_tracked_is_a_harmless_no_op(env):
    with env.app.app_context():
        empty_title = Titles(title_id="0100000000FFFFF0")
        db.session.add(empty_title)
        db.session.commit()

        assert db_mod.delete_title_apps("0100000000FFFFF0") == 0


# --- GraphQL mutations: admin-only, no settings toggle gates them anymore -----------

def test_clean_app_record_mutation_works_with_no_settings_toggle_involved(env):
    body = _mutate(env, CLEAN_APP_MUTATION, id=str(env.ids.alpha_update_row_id))

    assert "errors" not in body, body.get("errors")
    assert body["data"]["cleanAppRecord"] is True
    with env.app.app_context():
        assert db.session.get(Apps, env.ids.alpha_update_row_id) is None
        assert os.path.exists(env.ids.alpha_update_filepath)  # database-only


def test_clean_title_record_mutation_works_with_no_settings_toggle_involved(env):
    body = _mutate(env, CLEAN_TITLE_MUTATION, id=ALPHA)

    assert "errors" not in body, body.get("errors")
    assert body["data"]["cleanTitleRecord"] == 2
    with env.app.app_context():
        assert db.session.get(Apps, env.ids.alpha_base_row_id) is None
        assert os.path.exists(env.ids.alpha_base_filepath)


def test_delete_app_record_mutation_deletes_the_real_file(env):
    body = _mutate(env, DELETE_APP_MUTATION, id=str(env.ids.alpha_update_row_id))

    assert "errors" not in body, body.get("errors")
    assert body["data"]["deleteAppRecord"] is True
    with env.app.app_context():
        assert db.session.get(Apps, env.ids.alpha_update_row_id) is None
        assert not os.path.exists(env.ids.alpha_update_filepath)


def test_delete_title_record_mutation_deletes_every_real_file(env):
    body = _mutate(env, DELETE_TITLE_MUTATION, id=ALPHA)

    assert "errors" not in body, body.get("errors")
    assert body["data"]["deleteTitleRecord"] == 2
    with env.app.app_context():
        assert db.session.get(Apps, env.ids.alpha_base_row_id) is None
        assert db.session.get(Apps, env.ids.alpha_update_row_id) is None
        assert not os.path.exists(env.ids.alpha_base_filepath)
        assert not os.path.exists(env.ids.alpha_update_filepath)

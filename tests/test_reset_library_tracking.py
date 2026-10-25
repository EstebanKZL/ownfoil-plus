"""reset_library_tracking / resetLibraryTracking: the explicit, deliberate escape
hatch for a real mass change (moving to a smaller drive in batches, rebuilding a
library from scratch) that remove_missing_files_from_db's own proportional guard
would otherwise refuse to touch, on purpose, since it can't tell that apart from a
disconnected drive. Never triggered automatically - only by an admin explicitly
confirming exactly this action.
"""
import json
import types

import pytest

import db as db_mod
from app import create_app
from constants import APP_TYPE_BASE
from db import Apps, Files, Libraries, Titles, db, init_db, reset_library_tracking
from gql import graphql_dispatch


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))

    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    app.add_url_rule("/api/graphql", view_func=graphql_dispatch, methods=["GET", "POST"])
    ctx = app.app_context()
    ctx.push()
    init_db(app)

    library = Libraries(path=str(tmp_path / "games"))
    db.session.add(library)
    db.session.commit()
    title = Titles(title_id="0100000000000000")
    db.session.add(title)
    db.session.commit()
    app_row = Apps(title_id=title.id, app_id="0100000000000000", app_version="0",
                   app_type=APP_TYPE_BASE, owned=True)
    db.session.add(app_row)
    db.session.commit()
    f = Files(filepath=str(tmp_path / "games" / "Game.nsp"), library_id=library.id,
             folder=str(tmp_path / "games"), filename="Game.nsp", extension="nsp",
             size=7, identified=True, hash_valid=True, signature_valid=True)
    db.session.add(f)
    db.session.commit()
    app_row.files.append(f)
    db.session.commit()

    yield types.SimpleNamespace(app=app, client=app.test_client(),
                                library=library, title=title, app_row=app_row)
    ctx.pop()


def test_reset_removes_every_file_row(env):
    count = reset_library_tracking()

    assert count == 1
    assert Files.query.count() == 0


def test_reset_recomputes_app_ownership(env):
    reset_library_tracking()

    db.session.refresh(env.app_row)
    assert env.app_row.owned is False


def test_reset_leaves_the_association_table_clean(env):
    """The many-to-many app_files link must go with its file, not linger as an
    orphaned row - covered by the files.id foreign key's ON DELETE CASCADE."""
    reset_library_tracking()

    orphans = db.session.execute(db.text("SELECT COUNT(*) FROM app_files")).scalar()
    assert orphans == 0


def test_reset_leaves_titles_apps_and_libraries_untouched(env):
    """Only tracked files and derived ownership are in scope - the catalogue
    structure, library configuration, and everything else survives."""
    reset_library_tracking()

    assert Titles.query.count() == 1
    assert Apps.query.count() == 1
    assert Libraries.query.count() == 1


def test_reset_on_an_already_empty_library_is_a_harmless_no_op(env):
    reset_library_tracking()  # empties it
    assert reset_library_tracking() == 0  # second call: nothing left to remove


# --- GraphQL mutation: the confirm-phrase safety gate --------------------------------

RESET_MUTATION = """
    mutation($confirm: String!) { resetLibraryTracking(confirm: $confirm) }"""


def _mutate(env, confirm):
    resp = env.client.post("/api/graphql", json={
        "query": RESET_MUTATION, "variables": {"confirm": confirm}})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def test_the_exact_confirm_phrase_performs_the_reset(env):
    body = _mutate(env, "RESET")

    assert "errors" not in body, body.get("errors")
    assert body["data"]["resetLibraryTracking"] == 1
    assert Files.query.count() == 0


def test_a_wrong_confirm_phrase_does_nothing(env):
    """The critical safety case: a boolean would be too easy to send by accident -
    the exact phrase must be rejected outright, with the data left untouched."""
    body = _mutate(env, "reset")  # wrong case

    assert "errors" in body, "a wrong confirm phrase must be rejected, not silently accepted"
    assert Files.query.count() == 1, "no file should have been removed"


def test_an_empty_confirm_phrase_does_nothing(env):
    body = _mutate(env, "")

    assert "errors" in body
    assert Files.query.count() == 1


def test_a_close_but_wrong_confirm_phrase_does_nothing(env):
    body = _mutate(env, "RESET ")  # trailing space

    assert "errors" in body
    assert Files.query.count() == 1

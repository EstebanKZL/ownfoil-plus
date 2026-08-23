"""End-to-end GraphQL coverage for manual duplicate resolution: the
`duplicateFileGroups` query (admin-only, lists every app currently backed by more than
one physical file) and the `resolveDuplicateFiles` mutation (keeps one file, deletes
the app's other copies, regardless of verification status - a person choosing here has
already made the call).
"""
import json
import os
import types

import fixture
import pytest

import db as db_mod
import titledb
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC
from db import Apps, Files, Libraries, Titles, db, init_db
from gql import graphql_dispatch

ALPHA = "0100000000AAAAA0"[:16]
ALPHA_DLC = ALPHA[:-4] + "1001"
ALPHA_UPD = ALPHA[:-3] + "800"
TITLEDB_JSON = {
    ALPHA: {"id": ALPHA, "name": "Alpha Game"},
    ALPHA_DLC: {"id": ALPHA_DLC, "name": "Alpha DLC"},
}


@pytest.fixture
def library(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    games_dir = tmp_path / "games"
    games_dir.mkdir()
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
        title = Titles(title_id=ALPHA, have_base=True)
        library_row = Libraries(path=str(games_dir))
        db.session.add_all([title, library_row])
        db.session.flush()

        base_app = Apps(title_id=title.id, app_id=ALPHA, app_version="0",
                        app_type=APP_TYPE_BASE, owned=True)
        dlc_app = Apps(title_id=title.id, app_id=ALPHA_DLC, app_version="0",
                       app_type=APP_TYPE_DLC, owned=True)
        db.session.add_all([base_app, dlc_app])
        db.session.flush()

        def seed(app_row, name, content, **verdict):
            path = games_dir / name
            path.write_bytes(content)
            f = Files(library_id=library_row.id, filepath=str(path), folder=str(games_dir),
                     filename=name, extension="nsp", size=len(content), identified=True, **verdict)
            db.session.add(f)
            db.session.flush()
            app_row.files.append(f)
            return f

        # Base game: two copies, one Valid one Corrupt - an unambiguous case a person
        # could resolve manually even before/without the automatic pass touching it.
        valid = seed(base_app, "Alpha.nsp", b"GOOD",
                    signature_valid=True, hash_valid=True)
        corrupt = seed(base_app, "Alpha(2).nsp", b"BAD",
                       signature_valid=True, hash_valid=False, hash_modified=False)

        # DLC: two copies, both Unverified - the kind of tie/ambiguity the manual UI
        # exists for.
        dlc_a = seed(dlc_app, "AlphaDLC.nsp", b"X")
        dlc_b = seed(dlc_app, "AlphaDLC(2).nsp", b"Y")

        # Update: the exact case reported - two copies, both Valid, differing only in
        # size - a tie the strict mutation would need one-by-one, but the bulk
        # by-size mutation can resolve on its own.
        from constants import APP_TYPE_UPD
        update_app = Apps(title_id=title.id, app_id=ALPHA_UPD, app_version="0",
                          app_type=APP_TYPE_UPD, owned=True)
        db.session.add(update_app)
        db.session.flush()
        upd_small = seed(update_app, "AlphaUpd.nsp", b"SMALL",
                         signature_valid=True, hash_valid=True)
        upd_big = seed(update_app, "AlphaUpd(2).nsp", b"A LOT BIGGER CONTENT",
                       signature_valid=True, hash_valid=True)

        db.session.commit()
        ids = types.SimpleNamespace(valid=valid.id, corrupt=corrupt.id,
                                    dlc_a=dlc_a.id, dlc_b=dlc_b.id,
                                    upd_small=upd_small.id, upd_big=upd_big.id)

    return types.SimpleNamespace(app=app, client=app.test_client(), games_dir=games_dir, ids=ids)


def query(library, document, variables=None):
    params = {"query": document}
    if variables:
        params["variables"] = json.dumps(variables)
    resp = library.client.get("/api/graphql", query_string=params)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body["errors"]
    return body["data"]


def mutate(library, document, variables=None, expect_error=False):
    resp = library.client.post("/api/graphql", json={"query": document, "variables": variables or {}})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    if expect_error:
        assert body.get("errors"), f"expected an error, got {body}"
        return body["errors"][0]["message"]
    assert "errors" not in body, body["errors"]
    return body["data"]


DUPLICATE_GROUPS_QUERY = """
    query {
        duplicateFileGroups {
            titleId titleName appId appType appName
            files { id filename size verificationStatus }
        }
    }"""


def test_lists_every_app_with_more_than_one_file(library):
    data = query(library, DUPLICATE_GROUPS_QUERY)

    groups = data["duplicateFileGroups"]
    assert len(groups) == 3
    by_app_type = {g["appType"]: g for g in groups}

    base_group = by_app_type["BASE"]
    assert base_group["titleId"] == ALPHA
    assert base_group["titleName"] == "Alpha Game"
    assert base_group["appName"] == "Alpha Game"
    assert {f["filename"] for f in base_group["files"]} == {"Alpha.nsp", "Alpha(2).nsp"}
    statuses = {f["filename"]: f["verificationStatus"] for f in base_group["files"]}
    assert statuses["Alpha.nsp"] == "VALID"
    assert statuses["Alpha(2).nsp"] == "CORRUPT"


def test_dlc_group_shows_the_dlcs_own_name_not_the_titles(library):
    data = query(library, DUPLICATE_GROUPS_QUERY)
    groups = {g["appType"]: g for g in data["duplicateFileGroups"]}

    dlc_group = groups["DLC"]
    assert dlc_group["appName"] == "Alpha DLC"
    assert dlc_group["titleName"] == "Alpha Game"  # still the parent title
    assert {f["filename"] for f in dlc_group["files"]} == {"AlphaDLC.nsp", "AlphaDLC(2).nsp"}


RESOLVE_MUTATION = "mutation Resolve($id: ID!) { resolveDuplicateFiles(keepFileId: $id) }"


def test_resolving_keeps_the_chosen_file_and_deletes_the_rest(library):
    corrupt_path = str(library.games_dir / "Alpha(2).nsp")
    valid_path = str(library.games_dir / "Alpha.nsp")
    assert os.path.exists(corrupt_path) and os.path.exists(valid_path)

    data = mutate(library, RESOLVE_MUTATION, {"id": str(library.ids.valid)})

    assert data["resolveDuplicateFiles"] is True
    assert os.path.exists(valid_path)
    assert not os.path.exists(corrupt_path)


def test_resolving_the_worse_copy_still_honors_the_persons_choice(library):
    """The mutation doesn't second-guess a person's pick based on verdict - unlike
    the automatic pass, a manual choice here is final even if it keeps the Corrupt
    copy's content over the Valid one's."""
    data = mutate(library, RESOLVE_MUTATION, {"id": str(library.ids.corrupt)})

    assert data["resolveDuplicateFiles"] is True
    # The kept (Corrupt) file's own content survives at the plain name it took over
    # from the deleted Valid file - not the Valid content.
    plain_path = library.games_dir / "Alpha.nsp"
    assert plain_path.read_bytes() == b"BAD"


def test_resolving_a_tied_ambiguous_group_works_manually(library):
    """The exact case the automatic pass refuses to touch - two Unverified files -
    resolved fine once a person picks one."""
    data = mutate(library, RESOLVE_MUTATION, {"id": str(library.ids.dlc_a)})

    assert data["resolveDuplicateFiles"] is True
    remaining = query(library, DUPLICATE_GROUPS_QUERY)["duplicateFileGroups"]
    assert "DLC" not in {g["appType"] for g in remaining}  # no longer a duplicate group


def test_resolving_frees_the_plain_name_for_the_survivor(library):
    """The suffixed file wins; the plain name it vacated gets taken over, per the
    same rule the automatic path and library.resolve_duplicate_files already enforce."""
    mutate(library, RESOLVE_MUTATION, {"id": str(library.ids.corrupt)})  # keep Alpha(2), corrupt

    groups = query(library, DUPLICATE_GROUPS_QUERY)["duplicateFileGroups"]
    base_group = [g for g in groups if g["appType"] == "BASE"]
    assert base_group == []  # only one file left - no longer a duplicate group
    assert os.path.exists(str(library.games_dir / "Alpha.nsp"))
    assert not os.path.exists(str(library.games_dir / "Alpha(2).nsp"))


def test_an_unknown_file_id_is_a_mutation_error(library):
    message = mutate(library, RESOLVE_MUTATION, {"id": "999999"}, expect_error=True)
    assert "No file with id" in message


def test_a_file_with_no_duplicates_is_a_mutation_error(library):
    """Attached to an app, but that app has only this one file - a distinct case
    from a file with no app at all, which gets its own clearer message."""
    with library.app.app_context():
        base_app = Apps.query.filter_by(app_id=ALPHA).first()
        title = Titles.query.filter_by(title_id=ALPHA).first()
        library_row = Libraries.query.first()
        solo_app = Apps(title_id=title.id, app_id=ALPHA[:-4] + "1002",
                        app_version="0", app_type=APP_TYPE_DLC, owned=True)
        db.session.add(solo_app)
        db.session.flush()
        (library.games_dir / "Solo.nsp").write_bytes(b"Z")
        lone = Files(library_id=library_row.id, filepath=str(library.games_dir / "Solo.nsp"),
                    folder=str(library.games_dir), filename="Solo.nsp", extension="nsp",
                    size=1, identified=True)
        db.session.add(lone)
        db.session.flush()
        solo_app.files.append(lone)
        db.session.commit()
        lone_id = lone.id

    message = mutate(library, RESOLVE_MUTATION, {"id": str(lone_id)}, expect_error=True)
    assert "no duplicates" in message


def test_a_file_with_no_app_at_all_is_a_mutation_error(library):
    with library.app.app_context():
        library_row = Libraries.query.first()
        (library.games_dir / "Orphan.nsp").write_bytes(b"Z")
        orphan = Files(library_id=library_row.id, filepath=str(library.games_dir / "Orphan.nsp"),
                       folder=str(library.games_dir), filename="Orphan.nsp", extension="nsp",
                       size=1, identified=True)
        db.session.add(orphan)
        db.session.commit()
        orphan_id = orphan.id

    message = mutate(library, RESOLVE_MUTATION, {"id": str(orphan_id)}, expect_error=True)
    assert "not attached to any app" in message


def test_query_requires_admin_not_just_shop_access(library):
    """duplicateFileGroups exposes filepaths and internal file ids - same admin-only
    bar as the plain `files` query."""
    class FakeCtx:
        can_admin = False
    from gql.resolvers import resolve_duplicate_file_groups
    with library.app.app_context():
        assert resolve_duplicate_file_groups(ctx=FakeCtx(), info=None) == []


def test_mutation_requires_admin(library):
    """resolveDuplicateFiles deletes files - the same admin-only bar every other
    write in this schema enforces (NotAuthorized, not a silent no-op)."""
    from gql.mutations import Mutation, NotAuthorized

    class FakeCtx:
        can_admin = False

    class FakeInfo:
        context = FakeCtx()

    with library.app.app_context():
        with pytest.raises(NotAuthorized):
            Mutation().resolve_duplicate_files(FakeInfo(), keep_file_id=str(library.ids.valid))


# --- resolveDuplicatesBySize (bulk) ---------------------------------------------------

RESOLVE_BY_SIZE_MUTATION = "mutation { resolveDuplicatesBySize }"


def test_bulk_resolve_by_size_handles_many_groups_at_once(library):
    """The point of the bulk mutation: resolve every eligible group in one call
    rather than clicking through each one - here, the unambiguous Base group (Valid
    beats Corrupt) and the tied Update group (both Valid, bigger wins) both get
    resolved; the still-Unverified DLC group is correctly left alone."""
    data = mutate(library, RESOLVE_BY_SIZE_MUTATION)

    assert data["resolveDuplicatesBySize"] == 2  # Base + Update; DLC stays ambiguous

    remaining = query(library, DUPLICATE_GROUPS_QUERY)["duplicateFileGroups"]
    assert len(remaining) == 1
    assert remaining[0]["appType"] == "DLC"


def test_bulk_resolve_by_size_keeps_the_valid_file_over_corrupt(library):
    valid_path = str(library.games_dir / "Alpha.nsp")
    corrupt_path = str(library.games_dir / "Alpha(2).nsp")

    mutate(library, RESOLVE_BY_SIZE_MUTATION)

    assert os.path.exists(valid_path)
    assert not os.path.exists(corrupt_path)


def test_bulk_resolve_by_size_keeps_the_bigger_file_on_a_valid_tie(library):
    """The exact case reported: two Valid copies of an update, differing only in
    size - the bigger one survives, resolved automatically as part of the batch."""
    big_content = b"A LOT BIGGER CONTENT"

    mutate(library, RESOLVE_BY_SIZE_MUTATION)

    # The bigger file's content ends up at the plain (unsuffixed) name once the
    # smaller loser is gone - same rename-off-suffix behavior as everywhere else.
    plain_path = library.games_dir / "AlphaUpd.nsp"
    assert plain_path.read_bytes() == big_content
    assert not (library.games_dir / "AlphaUpd(2).nsp").exists()


def test_bulk_resolve_by_size_leaves_the_unverified_dlc_group_untouched(library):
    dlc_a_path = str(library.games_dir / "AlphaDLC.nsp")
    dlc_b_path = str(library.games_dir / "AlphaDLC(2).nsp")

    mutate(library, RESOLVE_BY_SIZE_MUTATION)

    assert os.path.exists(dlc_a_path)
    assert os.path.exists(dlc_b_path)


def test_bulk_resolve_by_size_returns_zero_when_nothing_is_eligible(library):
    """Only the Unverified DLC group left (after resolving the other two some other
    way) - a second bulk call must report 0, not error or re-resolve anything."""
    mutate(library, RESOLVE_BY_SIZE_MUTATION)  # resolves Base + Update

    data = mutate(library, RESOLVE_BY_SIZE_MUTATION)  # nothing left it can decide

    assert data["resolveDuplicatesBySize"] == 0


def test_bulk_resolve_by_size_requires_admin(library):
    from gql.mutations import Mutation, NotAuthorized

    class FakeCtx:
        can_admin = False

    class FakeInfo:
        context = FakeCtx()

    with library.app.app_context():
        with pytest.raises(NotAuthorized):
            Mutation().resolve_duplicates_by_size(FakeInfo())

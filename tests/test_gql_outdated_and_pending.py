"""Coverage for the Files admin page's two previously-deferred tiles (see CHANGELOG
6.2.4.9): Outdated updates (the `outdatedUpdateGroups` query) and Pending (the
`pendingFiles` query), plus the `retryIdentification` mutation and the
`verificationStatus` filter now accepting a list of statuses (needed for the
"Verification issues" tile, which reads as any of several statuses at once).
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

    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def gql(client, query, variables=None):
    resp = client.post("/api/graphql", json={"query": query, "variables": variables or {}})
    body = resp.get_json()
    assert "errors" not in body or not body["errors"], body.get("errors")
    return body["data"]


def test_outdated_update_groups_is_empty_with_only_one_owned_version(client):
    data = gql(client, "{ outdatedUpdateGroups { titleId } }")
    assert data["outdatedUpdateGroups"] == []


def test_outdated_update_groups_lists_the_newest_version_against_older_owned_ones(client, shop_app):
    with shop_app.app.app_context():
        from db import Apps, Files, Libraries, db
        lib = Libraries.query.first()
        newest_app = Apps.query.filter_by(app_id="0100000000010800").first()
        f = Files(library_id=lib.id, filepath="/tmp/outdated_fixture_file.nsp", folder="Test Game",
                 filename="outdated_fixture_file.nsp", extension="nsp", size=1234,
                 identified=True, multicontent=False)
        db.session.add(f)
        db.session.flush()
        older_app = Apps(title_id=newest_app.title_id, app_id="0100000000010800",
                         app_version="0", app_type="UPDATE", owned=True)
        db.session.add(older_app)
        db.session.flush()
        older_app.files.append(f)
        db.session.commit()
        old_file_id = str(f.id)

    data = gql(client, """
        { outdatedUpdateGroups { titleId titleName newestVersion
            keepFiles { id filename apps { appType title { name } } }
            remove { version file { id filename apps { appType title { name } } } } } }
    """)
    groups = data["outdatedUpdateGroups"]
    assert len(groups) == 1
    g = groups[0]
    assert g["newestVersion"] == "65536"
    assert g["keepFiles"][0]["filename"] == "Test Game [0100000000010800][v65536].nsp"
    remove_file = g["remove"][0]["file"]
    assert g["remove"][0]["version"] == "0"
    assert remove_file["id"] == old_file_id
    assert remove_file["filename"] == "outdated_fixture_file.nsp"
    # Regression guard: keepFiles/remove.file never ran through the `apps` hydration
    # machinery at all, so this always came back an empty list even for a fully
    # identified file - the Outdated updates tile's rows had no cover/name either.
    # (`title` itself may legitimately be null depending on titledb availability in a
    # given test's fixture; what matters here is that `apps` is no longer empty.)
    assert remove_file["apps"] == [{"appType": "UPDATE", "title": remove_file["apps"][0]["title"]}]
    assert g["keepFiles"][0]["apps"], "keepFiles' own apps must be hydrated too"


def test_outdated_update_groups_skips_a_removable_file_that_is_part_of_a_bundle(client, shop_app):
    """A multicontent file is never deleted by the outdated-updates cleanup - it is
    never listed as removable here either, same guard `remove_outdated_update_files`
    itself applies."""
    with shop_app.app.app_context():
        from db import Apps, Files, Libraries, db
        lib = Libraries.query.first()
        newest_app = Apps.query.filter_by(app_id="0100000000010800").first()
        f = Files(library_id=lib.id, filepath="/tmp/bundled_old_update.nsp", folder="Test Game",
                 filename="bundled_old_update.nsp", extension="nsp", size=1234,
                 identified=True, multicontent=True)
        db.session.add(f)
        db.session.flush()
        older_app = Apps(title_id=newest_app.title_id, app_id="0100000000010800",
                         app_version="0", app_type="UPDATE", owned=True)
        db.session.add(older_app)
        db.session.flush()
        older_app.files.append(f)
        db.session.commit()

    data = gql(client, "{ outdatedUpdateGroups { titleId } }")
    assert data["outdatedUpdateGroups"] == []


def test_pending_files_lists_the_fixture_librarys_unidentified_file(client):
    data = gql(client, "{ pendingFiles { total items { stages file { filename } } } }")
    pending = data["pendingFiles"]
    assert pending["total"] == 1
    assert pending["items"][0]["file"]["filename"] == "Mystery File.nsp"
    assert "identify" in pending["items"][0]["stages"]


def test_pending_files_hydrates_apps_for_an_identified_pending_file(client, shop_app):
    """Regression guard: pendingFiles never ran its File objects through the `apps`
    hydration machinery, so a perfectly identified file awaiting some other stage (not
    identification) always showed no cover/name on the Pending tile."""
    client.post("/api/settings/library/management", json={"organizer": {"enabled": True}})
    with shop_app.app.app_context():
        from db import Apps, Files, Libraries, db
        lib = Libraries.query.first()
        app_row = Apps.query.filter_by(app_id="0100000000010000").first()
        f = Files(library_id=lib.id, filepath="/tmp/pending_fixture_file.nsp", folder="Test Game",
                 filename="pending_fixture_file.nsp", extension="nsp", size=1234,
                 identified=True, organized=False)
        db.session.add(f)
        db.session.flush()
        app_row.files.append(f)
        db.session.commit()

    data = gql(client, """
        { pendingFiles { items {
            file { filename apps { appType title { name } } } } } }
    """)
    entry = next(e for e in data["pendingFiles"]["items"]
                if e["file"]["filename"] == "pending_fixture_file.nsp")
    assert entry["file"]["apps"], "a pending but identified file's apps must be hydrated"


def test_pending_files_requires_admin(shop_app):
    resp = shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303)
    data = gql(shop_app.client, "{ pendingFiles { total } }")
    assert data["pendingFiles"]["total"] == 0


def test_retry_identification_re_enqueues_a_file(client):
    data = gql(client, """
        query { files(filter: {filename: {eq: "Mystery File.nsp"}}) { items { id } } }
    """)
    file_id = data["files"]["items"][0]["id"]
    out = gql(client, "mutation($id: ID!) { retryIdentification(fileId: $id) { id taskName } }", {"id": file_id})
    assert out["retryIdentification"]["taskName"] == "process_file"


def test_retry_identification_requires_admin(shop_app):
    resp = shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303)
    resp = shop_app.client.post("/api/graphql", json={
        "query": "mutation { retryIdentification(fileId: \"1\") { id } }",
    })
    body = resp.get_json()
    assert body.get("errors"), "a non-admin must not be able to retry identification"


def test_verification_status_filter_matches_any_status_in_the_list(client):
    """The filter used to take one VerificationStatus; it now takes a list, which is
    what lets the Files page's "Verification issues" tile ask for every broken-or-
    unverified status in one query instead of four."""
    data = gql(client, """
        query { files(filter: {verificationStatus: [UNVERIFIED, CORRUPT]}) { total } }
    """)
    # Every fixture file is UNVERIFIED (none has been through verification).
    data_all = gql(client, "{ stats { totalFiles } }")
    assert data["files"]["total"] == data_all["stats"]["totalFiles"]


def test_verification_status_filter_with_an_empty_list_is_no_constraint(client):
    data = gql(client, "query { files(filter: {verificationStatus: []}) { total } }")
    data_all = gql(client, "{ stats { totalFiles } }")
    assert data["files"]["total"] == data_all["stats"]["totalFiles"]

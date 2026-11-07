"""The firmware each owned base game / update needs, read from the file's own CNMT
(RequiredSystemVersion) when TitleDB's cnmts.json has no value for that version - it
is null for many older updates."""
import json
import struct

import pytest

import tasks
from containers import cnmt
from db import Apps, Files, Libraries, Titles, db
from test_account_firmware import GAME, UPDATE, titledb_env  # noqa: F401 (fixture)


class _FakeCnmt:
    """Just enough of nsz's Cnmt: a seekable byte buffer with readInt32."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def seek(self, offset):
        self.pos = offset

    def readInt32(self):
        value = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return value


def _cnmt_bytes(required):
    data = bytearray(0x40)
    struct.pack_into("<Q", data, 0x20, 0x0100152000022800)
    struct.pack_into("<I", data, 0x28, required)
    return bytes(data)


def test_the_cnmt_extended_header_holds_the_required_firmware():
    blob = _cnmt_bytes(1006698496)
    assert cnmt.required_system_version(_FakeCnmt(blob), 0x81) == 1006698496
    assert cnmt.required_system_version(_FakeCnmt(blob), 0x80) == 1006698496
    # A DLC's extended header holds something else, and 0 means "none".
    assert cnmt.required_system_version(_FakeCnmt(blob), 0x82) is None
    assert cnmt.required_system_version(_FakeCnmt(_cnmt_bytes(0)), 0x81) is None
    # Top bit set stays an unsigned firmware number.
    assert cnmt.required_system_version(_FakeCnmt(_cnmt_bytes(0xF0000000)), 0x81) == 0xF0000000


def test_a_short_cnmt_reads_as_unknown_instead_of_failing():
    assert cnmt.required_system_version(_FakeCnmt(b"\0" * 0x22), 0x81) is None


def test_apps_store_it_and_a_migration_adds_the_column():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    import os
    assert "required_system_version" in Apps.__table__.columns
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "app", "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_revision("c3d4e5f6a7b9").down_revision == "b2c3d4e5f6a8"


def test_identification_keeps_what_the_cnmt_said(monkeypatch):
    import titles as titles_lib
    monkeypatch.setattr(titles_lib.Keys, "keys_loaded", True)
    monkeypatch.setattr(titles_lib, "identify_file_from_cnmt",
                        lambda path: [("UPDATE", UPDATE, 65536, 805437440)])
    monkeypatch.setattr(titles_lib, "read_display_versions", lambda path: {})
    monkeypatch.setattr(titles_lib, "identify_appId", lambda app_id: (GAME, "UPDATE"))
    _, ok, contents, error = titles_lib.identify_file("/x/game.nsp")
    assert ok and not error
    assert contents[0]["required_system_version"] == 805437440


def _owned_update(app, version, required=None):
    with app.app_context():
        title = Titles(title_id=GAME)
        db.session.add(title)
        db.session.flush()
        row = Apps(app_id=UPDATE, app_version=str(version), app_type="UPDATE",
                   owned=True, title_id=title.id, required_system_version=required)
        db.session.add(row)
        db.session.commit()


def test_an_owned_file_fills_in_what_titledb_doesnt_know(titledb_env, tmp_path):
    # TitleDB forgets the firmware of the first update...
    cnmts = tmp_path / "titledb" / "cnmts.json"
    data = json.loads(cnmts.read_text())
    data[UPDATE.lower()]["65536"]["requiredSystemVersion"] = None
    cnmts.write_text(json.dumps(data))
    from titledb import store
    with titledb_env.app_context():
        store.import_from_json(str(tmp_path / "titledb" / "titles.US.en.json"), "US.en")
    # ...but the file the user owns said 12.0.2.
    _owned_update(titledb_env, 65536, 805437440)
    query = """{ title(titleId: "%s") { availableVersions { version requiredFirmware } } }""" % GAME
    body = titledb_env.test_client().get("/api/graphql", query_string={"query": query}).get_json()
    assert "errors" not in body, body.get("errors")
    by_version = {v["version"]: v["requiredFirmware"] for v in body["data"]["title"]["availableVersions"]}
    assert by_version[65536] == "12.0.2"
    assert by_version[131072] == "15.0.1"


def test_files_identified_before_are_read_once(titledb_env, monkeypatch):
    import titles as titles_lib
    _owned_update(titledb_env, 65536)
    with titledb_env.app_context():
        library = Libraries(path="/lib")
        db.session.add(library)
        db.session.flush()
        file = Files(library_id=library.id, filepath="/lib/update.nsp", filename="update.nsp",
                     identified=True, identification_type="cnmt")
        db.session.add(file)
        db.session.flush()
        app_row = Apps.query.filter_by(app_id=UPDATE).one()
        app_row.files.append(file)
        db.session.commit()

    monkeypatch.setattr(titles_lib.Keys, "keys_loaded", True)
    claims = iter([True, False])
    monkeypatch.setattr(tasks.settings_lib, "mark_once", lambda key: next(claims))
    reads = []

    def fake_read(path):
        reads.append(path)
        return [("UPDATE", UPDATE, 65536, 805437440)]
    monkeypatch.setattr("containers.cnmt.identify_file_from_cnmt", fake_read)

    with titledb_env.app_context():
        tasks.backfill_required_firmware_task()
        tasks.backfill_required_firmware_task()     # already claimed: does nothing
        assert Apps.query.filter_by(app_id=UPDATE).one().required_system_version == 805437440
    assert reads == ["/lib/update.nsp"]


def test_startup_queues_it_only_with_keys():
    import inspect
    body = inspect.getsource(tasks.startup_task)
    assert "keys_loaded" in body and "enqueue_task('backfill_required_firmware')" in body
    assert "backfill_required_firmware" in tasks.TASK_DISPLAY

"""Coverage for the NACP display-version port: /admin/files showed a raw "v0" for a
perfectly normal first release because nothing here ever read the human version string
("1.0.0") out of a content's own Control NCA - unlike upstream ownfoil 2.5.0, which has
always done this. Four layers, each tested at the level that doesn't need a real NSP/XCI
file: the pure NACP blob parser, titles.identify_file's orchestration of CNMT identify +
Control NCA read, the Apps.display_version upsert in tasks._identify, and the GraphQL/
template surface that shows the result.
"""
import json
import types

import pytest

import db as db_mod
import titledb
import titles as titles_lib
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC, APP_TYPE_UPD
from containers import container, nacp
from db import Apps, Files, Libraries, Titles, db, init_db
from gql import graphql_dispatch


# --- containers/nacp.py: pure blob parsing, no container needed -----------------------

def _nacp_blob(display_version=b"1.2.1"):
    """A minimal control.nacp-shaped blob: zero-filled up to and past the
    DisplayVersion field (offset 0x3060, 16 bytes), with the given bytes written there,
    NUL-terminated like the real field is."""
    blob = bytearray(0x3070)
    if display_version is not None:
        blob[0x3060:0x3060 + len(display_version)] = display_version
    return bytes(blob)


def test_nacp_display_version_reads_the_field():
    assert nacp.nacp_display_version(_nacp_blob(b"1.2.1")) == "1.2.1"


def test_nacp_display_version_is_none_when_the_field_is_empty():
    """An all-zero field (some very old titles ship none at all) decodes to an empty
    string, which the fallback-to-None in _string turns into a clean None rather than
    an empty-string "version"."""
    assert nacp.nacp_display_version(_nacp_blob(display_version=b"")) is None


def test_nacp_display_version_stops_at_the_first_nul():
    blob = _nacp_blob(b"1.0.0\x00garbage-past-the-terminator")
    assert nacp.nacp_display_version(blob) == "1.0.0"


class _FakeRom:
    """Just enough of the RomFS/IVFC interface read_display_version needs: a seek/read
    pair and the one nested attribute (`ivfc.levels[-1].offset`) read_romfs_files uses to
    find the section. The RomFS itself is built by hand in the same layout
    read_romfs_files expects (header, then one file entry for control.nacp)."""
    def __init__(self, data):
        self._data = data
        self._pos = 0

    def seek(self, pos):
        self._pos = pos

    def read(self, size):
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


def _build_romfs(nacp_blob):
    """header (10 Q's) + meta table (one file entry + its name) + data (the blob
    itself) laid out back to back, exactly as read_romfs_files expects to find them -
    meta_offset/meta_size/data_offset in the header are all relative to the section
    (here, byte 0), matching how read_romfs_files uses them."""
    import struct
    name = b"control.nacp"
    name_padded_len = (len(name) + 3) & ~3
    # file entry fields, per read_romfs_files' own unpacking: the first two (I, I) are
    # discarded (parent/sibling pointers), then file_offset (Q), size (Q), an ignored
    # hash field (I), and name_len (I) - in that order.
    entry = struct.pack("<IIQQII", 0, 0, 0, len(nacp_blob), 0, len(name)) + \
        name.ljust(name_padded_len, b"\x00")
    header_size = _struct_size_10q()
    meta_offset, meta_size = header_size, len(entry)
    data_offset = meta_offset + meta_size
    header = struct.pack("<10Q", 0, 0, 0, 0, 0, 0, 0, meta_offset, meta_size, data_offset)
    return header + entry + nacp_blob


def _struct_size_10q():
    import struct
    return struct.calcsize("<10Q")


def test_read_display_version_walks_a_synthetic_romfs():
    romfs = _build_romfs(_nacp_blob(b"1.0.1"))
    rom = _FakeRom(romfs)
    rom.ivfc = types.SimpleNamespace(levels=[types.SimpleNamespace(offset=0)])
    assert nacp.read_display_version(rom) == "1.0.1"


def test_read_display_version_is_none_when_control_nacp_is_missing():
    """A Control NCA's RomFS always carries control.nacp in practice - this guards the
    defensive path (treated as "nothing to report", not raised) rather than a real case."""
    import struct
    header = struct.pack("<10Q", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    rom = _FakeRom(header)
    rom.ivfc = types.SimpleNamespace(levels=[types.SimpleNamespace(offset=0)])
    assert nacp.read_display_version(rom) is None


# --- containers/container.py: the partition-table reader open_nca relies on ----------

class _FakeHolder:
    """Just enough of the nsz File interface _partition_entries needs over a plain
    bytes buffer: seek/read plus the two int readers it calls."""
    def __init__(self, data):
        self._data = data
        self._pos = 0

    def seek(self, pos):
        self._pos = pos

    def read(self, size):
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk

    def readInt32(self):
        return int.from_bytes(self.read(4), "little")

    def readInt64(self):
        return int.from_bytes(self.read(8), "little")


def _build_pfs0(names_and_sizes):
    """A minimal PFS0 partition table: magic, count, string table size, padding, one
    (offset, size, name_offset) entry per file, then the string table - laid out
    exactly as container._partition_entries reads it back."""
    import struct
    names = b"".join(n.encode() + b"\x00" for n in names_and_sizes)
    entries = b""
    data_offset = 0
    name_offset = 0
    for name, size in names_and_sizes.items():
        # Entry stride is 0x18 (24 bytes) for PFS0 - offset(8) + size(8) + name_offset(4)
        # + 4 bytes of padding _partition_entries never reads but must still occupy.
        entries += struct.pack("<QQII", data_offset, size, name_offset, 0)
        data_offset += size
        name_offset += len(name) + 1
    header = b"PFS0" + struct.pack("<III", len(names_and_sizes), len(names), 0)
    return header + entries + names


def test_partition_entries_reads_a_synthetic_pfs0_table():
    holder = _FakeHolder(_build_pfs0({
        "0011223344556677.nca": 4096,
        "0011223344556677.cnmt.nca": 512,
    }))
    entries = container._partition_entries(holder)
    assert set(entries) == {"0011223344556677.nca", "0011223344556677.cnmt.nca"}
    # header_size = 0x10 + count*entry_size + string_table_size, offsets are relative to it.
    header_size = 0x10 + 2 * 0x18 + len("0011223344556677.nca\x00" "0011223344556677.cnmt.nca\x00")
    assert entries["0011223344556677.nca"] == (header_size + 0, 4096)
    assert entries["0011223344556677.cnmt.nca"] == (header_size + 4096, 512)


# --- titles.identify_file: orchestration of CNMT identify + Control NCA read ----------

BASE_ID = "0100000000010000"
UPD_ID = "0100000000010800"
DLC_ID = "0100000000010001"


def test_identify_file_attaches_display_version_per_content(monkeypatch):
    """The common case: a multicontent file (base + update) where both contents have a
    display version - each content gets its own, matched by (app_id, version)."""
    monkeypatch.setattr(titles_lib.Keys, "keys_loaded", True, raising=False)
    monkeypatch.setattr(titles_lib, "identify_file_from_cnmt", lambda fp: [
        (APP_TYPE_BASE, BASE_ID, "0"),
        (APP_TYPE_UPD, UPD_ID, "65536"),
    ])
    monkeypatch.setattr(titles_lib, "read_display_versions", lambda fp: {
        (BASE_ID, "0"): "1.0.0",
        (UPD_ID, "65536"): "1.1.0",
    })
    monkeypatch.setattr(titles_lib, "identify_appId",
                        lambda app_id: (BASE_ID, APP_TYPE_UPD))

    identification, success, contents, error = titles_lib.identify_file("/fake/Game.nsp")

    assert identification == "cnmt"
    assert success and not error
    by_app_id = {c["app_id"]: c["display_version"] for c in contents}
    assert by_app_id[BASE_ID] == "1.0.0"
    assert by_app_id[UPD_ID] == "1.1.0"


def test_identify_file_leaves_display_version_null_for_a_dlc(monkeypatch):
    """A DLC ships no Control NCA, so read_display_versions simply never has an entry
    for it - identify_file must report display_version: None rather than KeyError."""
    monkeypatch.setattr(titles_lib.Keys, "keys_loaded", True, raising=False)
    monkeypatch.setattr(titles_lib, "identify_file_from_cnmt", lambda fp: [
        (APP_TYPE_DLC, DLC_ID, "0"),
    ])
    monkeypatch.setattr(titles_lib, "read_display_versions", lambda fp: {})
    monkeypatch.setattr(titles_lib, "identify_appId",
                        lambda app_id: (BASE_ID, APP_TYPE_DLC))

    identification, success, contents, error = titles_lib.identify_file("/fake/Game.nsp")

    assert success and not error
    assert contents[0]["app_id"] == DLC_ID
    assert contents[0]["display_version"] is None


def test_identify_file_tolerates_a_display_version_read_failure(monkeypatch):
    """A Control NCA that fails to read (corrupt, or a narrower master-key gap than
    identification needed) must not turn a successful CNMT identification into a
    failed one - the content list still comes back, just without display versions."""
    monkeypatch.setattr(titles_lib.Keys, "keys_loaded", True, raising=False)
    monkeypatch.setattr(titles_lib, "identify_file_from_cnmt", lambda fp: [
        (APP_TYPE_BASE, BASE_ID, "0"),
    ])

    def boom(fp):
        raise ValueError("Missing valid master_key_99")
    monkeypatch.setattr(titles_lib, "read_display_versions", boom)

    identification, success, contents, error = titles_lib.identify_file("/fake/Game.nsp")

    assert success and not error
    assert contents[0]["app_id"] == BASE_ID
    assert contents[0]["display_version"] is None


def test_identify_file_from_filename_has_no_display_version(monkeypatch):
    """Without keys, nothing in the container can be read at all - filename-based
    identification reports display_version: None rather than omitting the key, so
    every caller can rely on it always being present."""
    monkeypatch.setattr(titles_lib.Keys, "keys_loaded", False, raising=False)

    identification, success, contents, error = titles_lib.identify_file(
        f"Game [{BASE_ID}][v0].nsp")

    assert identification == "filename"
    assert success and contents
    assert contents[0]["display_version"] is None


# --- tasks._identify: the Apps.display_version upsert ---------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    import tasks

    config = tmp_path / "config"
    config.mkdir()
    lib_dir = tmp_path / "games"
    lib_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))

    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    init_db(app)
    with app.app_context():
        library = Libraries(path=str(lib_dir))
        db.session.add(library)
        db.session.commit()

        path = lib_dir / "Game.nsp"
        path.write_bytes(b"X" * 8)
        f = Files(filepath=str(path), library_id=library.id, folder=str(lib_dir),
                 filename="Game.nsp", extension="nsp", size=8,
                 identified=False, identification_attempts=0)
        db.session.add(f)
        db.session.commit()

        yield types.SimpleNamespace(app=app, file=f, tasks=tasks)


def _identify_with(monkeypatch, tasks_mod, display_version):
    monkeypatch.setattr(tasks_mod.titles_lib, "identify_file", lambda fp: (
        "cnmt", True,
        [{"title_id": BASE_ID, "app_id": BASE_ID, "type": APP_TYPE_BASE, "version": "0",
          "display_version": display_version}],
        ""))
    tasks_mod._identify(tasks_mod.Files.query.get(1), {})


def test_identify_stores_the_display_version_on_the_apps_row(env, monkeypatch):
    with env.app.app_context():
        _identify_with(monkeypatch, env.tasks, "1.0.0")
        app_row = Apps.query.filter_by(app_id=BASE_ID, app_version="0").one()
        assert app_row.display_version == "1.0.0"


def test_a_later_identify_without_a_display_version_does_not_blank_out_the_old_one(env, monkeypatch):
    """Simulates a re-identify pass whose Control NCA read failed transiently (so
    identify_file reports display_version: None for this content) after an earlier pass
    had already found a real one - the coalesce in the upsert must keep the old value
    rather than overwrite it with the fresh null."""
    with env.app.app_context():
        _identify_with(monkeypatch, env.tasks, "1.0.0")
        _identify_with(monkeypatch, env.tasks, None)

        app_row = Apps.query.filter_by(app_id=BASE_ID, app_version="0").one()
        assert app_row.display_version == "1.0.0"


def test_a_later_identify_with_a_new_display_version_overwrites_the_old_one(env, monkeypatch):
    with env.app.app_context():
        _identify_with(monkeypatch, env.tasks, "1.0.0")
        _identify_with(monkeypatch, env.tasks, "1.0.1")

        app_row = Apps.query.filter_by(app_id=BASE_ID, app_version="0").one()
        assert app_row.display_version == "1.0.1"


# --- GraphQL exposure: App.displayVersion / AppVersion.displayVersion -----------------

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
    region_file.write_text(json.dumps({BASE_ID: {"id": BASE_ID, "name": "Alpha Game"}}))
    (titledb_dir / "cnmts.json").write_text("{}")
    (titledb_dir / "versions.json").write_text("{}")
    with app.app_context():
        titledb.store.import_from_json(str(region_file), "US.en")

        title = Titles(title_id=BASE_ID, have_base=True, up_to_date=True, complete=True)
        db.session.add(title)
        db.session.flush()

        db.session.add(Apps(title_id=title.id, app_id=BASE_ID, app_version="0",
                            app_type=APP_TYPE_BASE, owned=True, display_version="1.0.0"))
        db.session.add(Apps(title_id=title.id, app_id=UPD_ID, app_version="65536",
                            app_type=APP_TYPE_UPD, owned=True, display_version="1.1.0"))
        db.session.add(Apps(title_id=title.id, app_id=DLC_ID, app_version="0",
                            app_type=APP_TYPE_DLC, owned=True, display_version=None))
        db.session.commit()

    return types.SimpleNamespace(app=app, client=app.test_client())


def _query(library, text_query):
    resp = library.client.get("/api/graphql", query_string={"query": text_query})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "errors" not in body, body["errors"]
    return body["data"]


def test_app_display_version_resolves_from_the_db_column(library):
    data = _query(library, """
        query { apps(page: 1, pageSize: 10, filter: {appId: {eq: "%s"}}) {
            items { appId displayVersion } } }""" % BASE_ID)
    assert data["apps"]["items"][0]["displayVersion"] == "1.0.0"


def test_app_version_display_version_resolves_through_the_versions_list(library):
    """Reached a different way than App.displayVersion itself - via the base app's
    `versions` list, which is where /admin/files' own query reaches it from an UPDATE's
    own `apps` edge today, but a client reading it off the version-history list must see
    the same string."""
    data = _query(library, """
        query { apps(page: 1, pageSize: 10, filter: {appId: {eq: "%s"}}) {
            items { versions { version displayVersion } } } }""" % BASE_ID)
    versions = {v["version"]: v["displayVersion"] for v in data["apps"]["items"][0]["versions"]}
    assert versions[65536] == "1.1.0"


def test_app_display_version_is_null_for_a_dlc(library):
    """A DLC's own Apps row never gets a display_version written (no Control NCA to
    read it from), and the field reads back as a clean null rather than erroring."""
    data = _query(library, """
        query { apps(page: 1, pageSize: 10, filter: {appId: {eq: "%s"}}) {
            items { appId displayVersion } } }""" % DLC_ID)
    assert data["apps"]["items"][0]["displayVersion"] is None


# --- files.html: the JS fallback and the GraphQL query fragment -----------------------

def test_files_template_requests_and_prefers_display_version():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "app", "templates", "files.html")
    html = open(path, encoding="utf-8").read()
    assert "apps { appId appType appVersion displayVersion titleId" in html
    assert "return a.displayVersion || `v${a.appVersion}`;" in html

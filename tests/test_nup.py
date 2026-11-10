"""NUP files (.nup): decrypted games read without keys (containers/nup.py) - one file
holding a game, its update and a DLC - identified as one multi-content file, checked by
their SHA-256 list, never listed in the console shops and never a duplicate of an NSP."""
import hashlib
import os
import struct

import pytest
import zstandard

from containers import nup

GAME = 0x0100ABCD12340000
DLC = 0x0100ABCD12341001


def _tlv(kind, value):
    return struct.pack('<HHI', kind, 0, len(value)) + value


def build_nup(path, corrupt_data=False, packages=None, metas=None, file_names=None, dir_children=None):
    """A small, valid NUP: a game (raw file), its update stored with the program id
    (zstd file) and one DLC, each a root folder with one file. `metas` replaces the three
    packages' metadata blocks, `file_names` the three files' names and `dir_children` the
    (first child, count) of each folder - for the damaged and hostile cases."""
    payloads = [b'game exefs main' * 10, b'update romfs data' * 50, b'dlc romfs' * 7]
    codecs = [0, 1, 0]
    stored = [p if c == 0 else zstandard.ZstdCompressor().compress(p) for p, c in zip(payloads, codecs)]
    metas = metas or [
        _tlv(0x0005, b'Test Game [0100ABCD12340000][v0]') + _tlv(0x0006, b'Tester') + _tlv(0x0004, b'1.0.0'),
        _tlv(0x0005, b'Test Game') + _tlv(0x0004, b'1.2.0'),
        b'',
    ]
    packages = packages or [(GAME, 0, 0), (GAME, 65536, 1), (DLC, 0, 2)]

    names = b''
    name_refs = []
    for n in [b'game', b'update', b'dlc'] + (file_names or [b'main', b'data.bin', b'dlc.bin']):
        name_refs.append((len(names), len(n)))
        names += n

    header_size = 0x80
    toc_offset = header_size
    n_pkg, n_dir, n_file, n_child = 3, 3, 3, 3
    records = 0x30 + n_pkg * 0x40 + n_dir * 0x18 + n_file * 0x50
    pool_offset = records + n_child * 4
    toc_size = pool_offset + len(names)
    meta_offset = toc_offset + toc_size
    meta_offsets, pos = [], meta_offset
    for m in metas:
        meta_offsets.append(pos)
        pos += len(m)
    data_offset = (pos + 15) // 16 * 16
    extents, pos = [], data_offset
    for s in stored:
        extents.append(pos)
        pos = (pos + len(s) + 15) // 16 * 16
    file_size = pos

    toc = bytearray(toc_size)
    toc[0:4] = b'TOC\x01'
    struct.pack_into('<IQQQQ', toc, 4, n_pkg, n_dir, n_file, pool_offset, len(names))
    for i, (tid, version, kind) in enumerate(packages):
        o = 0x30 + i * 0x40
        struct.pack_into('<QIIII', toc, o, tid, i, 0xFFFFFFFF, i, version)
        toc[o + 0x18] = kind
        struct.pack_into('<QI', toc, o + 0x20, meta_offsets[i] if metas[i] else 0, len(metas[i]))
    for i in range(n_dir):
        o = 0x30 + n_pkg * 0x40 + i * 0x18
        first, count = (dir_children or [(0, 1), (1, 1), (2, 1)])[i]
        struct.pack_into('<IIII', toc, o, name_refs[i][0], name_refs[i][1], first, count)
    for i in range(n_file):
        o = 0x30 + n_pkg * 0x40 + n_dir * 0x18 + i * 0x50
        struct.pack_into('<IIQQQ', toc, o, name_refs[3 + i][0], name_refs[3 + i][1],
                         len(payloads[i]), extents[i], len(stored[i]))
        toc[o + 0x20:o + 0x40] = hashlib.sha256(payloads[i]).digest()
        toc[o + 0x40] = codecs[i]
    for i in range(n_child):
        struct.pack_into('<I', toc, records + i * 4, 0x80000000 + i)    # tagged file nodes
    toc[pool_offset:] = names

    header = bytearray(header_size)
    header[0:4] = b'NUP\x01'
    struct.pack_into('<HxxQQ', header, 4, header_size, toc_offset, toc_size)
    header[0x18:0x38] = hashlib.sha256(bytes(toc)).digest()
    struct.pack_into('<QQII', header, 0x38, data_offset, file_size, n_pkg, 0)

    blob = bytearray(file_size)
    blob[0:header_size] = header
    blob[toc_offset:toc_offset + toc_size] = toc
    for o, m in zip(meta_offsets, metas):
        blob[o:o + len(m)] = m
    for o, s in zip(extents, stored):
        blob[o:o + len(s)] = s
    if corrupt_data:
        blob[extents[0]] ^= 0xFF
    with open(path, 'wb') as f:
        f.write(bytes(blob))
    return path


@pytest.fixture
def nup_file(tmp_path):
    return build_nup(str(tmp_path / 'Test Game.nup'))


def test_a_nup_lists_its_game_update_and_dlc(nup_file):
    parts = {p['app_id']: p for p in nup.contents(nup_file)}
    assert set(parts) == {'0100ABCD12340000', '0100ABCD12340800', '0100ABCD12341001'}
    game = parts['0100ABCD12340000']
    assert game['kind'] == nup.KIND_BASE and game['version'] == 0
    assert game['name'] == 'Test Game'            # the file-name tags are dropped
    assert game['display_version'] == '1.0.0' and game['publisher'] == 'Tester'
    update = parts['0100ABCD12340800']
    assert update['kind'] == nup.KIND_UPDATE and update['version'] == 65536
    assert all(p['stored_size'] > 0 for p in parts.values())


def test_a_game_stored_without_its_id_takes_its_updates(tmp_path):
    """Seen with Switch 2 NUPs: the game's package carries no title id (a dump without
    its NPDM), only its update and DLC do - the game was dropped and the file listed as
    "Update + DLC". Its id is the update's (or a DLC's) program id."""
    path = build_nup(str(tmp_path / 'g.nup'), packages=[(0, 0, 0), (GAME, 65536, 1), (DLC, 0, 2)])
    parts = {p['app_id']: p['kind'] for p in nup.contents(path)}
    assert parts == {'0100ABCD12340000': nup.KIND_BASE, '0100ABCD12340800': nup.KIND_UPDATE,
                     '0100ABCD12341001': nup.KIND_DLC}
    only_dlc = build_nup(str(tmp_path / 'd.nup'), packages=[(0, 0, 0), (DLC, 0, 2), (DLC + 1, 0, 2)])
    assert '0100ABCD12340000' in {p['app_id'] for p in nup.contents(only_dlc)}


def test_paths_inside_each_package_are_walked(nup_file):
    container = nup.read(nup_file)
    assert [path for path, _ in nup.walk(container, 1)] == ['data.bin']


def test_a_damaged_table_of_contents_is_refused(nup_file):
    with open(nup_file, 'r+b') as f:
        f.seek(0x80 + 0x40)
        byte = f.read(1)
        f.seek(0x80 + 0x40)
        f.write(bytes([byte[0] ^ 0xFF]))
    with pytest.raises(nup.NupError, match='hash'):
        nup.read(nup_file)


def test_a_cut_short_or_foreign_file_is_refused(tmp_path, nup_file):
    data = open(nup_file, 'rb').read()
    short = tmp_path / 'short.nup'
    short.write_bytes(data[:-16])
    with pytest.raises(nup.NupError, match='cut short'):
        nup.read(str(short))
    other = tmp_path / 'other.nup'
    other.write_bytes(b'PFS0' + b'\0' * 200)
    with pytest.raises(nup.NupError, match='not a NUP'):
        nup.read(str(other))


def test_every_file_is_checked_by_its_sha256(tmp_path, nup_file):
    assert nup.verify(nup_file) == (True, None)
    bad = build_nup(str(tmp_path / 'bad.nup'), corrupt_data=True)
    ok, error = nup.verify(bad)
    assert not ok and 'main' in error


def test_it_is_identified_without_keys(monkeypatch, nup_file):
    import titles as titles_lib
    monkeypatch.setattr(titles_lib.Keys, 'keys_loaded', False)
    monkeypatch.setattr(titles_lib, 'identify_appId', lambda app_id: ('0100ABCD12340000', 'DLC'))
    identification, ok, contents, error = titles_lib.identify_file(nup_file)
    assert identification == 'nup' and ok and not error
    by_app = {c['app_id']: c for c in contents}
    assert by_app['0100ABCD12340000']['type'] == 'BASE'
    assert by_app['0100ABCD12340800']['type'] == 'UPDATE'
    assert by_app['0100ABCD12340800']['title_id'] == '0100ABCD12340000'
    assert by_app['0100ABCD12341001']['type'] == 'DLC'
    assert by_app['0100ABCD12340000']['display_version'] == '1.0.0'


def test_verification_covers_nup_without_keys(nup_file):
    from containers import verification
    assert 'nup' in verification.VERIFY_EXT and 'nup' in verification.NO_KEYS_EXT
    assert verification.verify(nup_file, verification.DEPTH_HASH) == (True, True, None, None)
    assert verification.verify(nup_file, verification.DEPTH_SIGNATURE) == (True, None, None, None)


def test_it_is_a_library_format_but_never_offered_to_consoles():
    from constants import ALLOWED_EXTENSIONS, SHOP_EXTENSIONS
    assert 'nup' in ALLOWED_EXTENSIONS and 'nup' not in SHOP_EXTENSIONS
    import inspect
    import db
    assert 'SHOP_EXTENSIONS' in inspect.getsource(db.get_filtered_files)


def test_a_nup_is_never_a_duplicate_of_an_nsp():
    import inspect
    import library
    assert "'nup'" in inspect.getsource(library.duplicate_file_groups)
    # Old updates: only files that install compare (test_nup_checks.py checks it runs).
    assert "'nup'" in inspect.getsource(library._install_files)
    assert "_install_files" in inspect.getsource(library.outdated_update_groups)
    assert "_install_files" in inspect.getsource(library.remove_outdated_update_files)


def test_nup_files_can_be_uploaded():
    root = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates', '_upload_modal.html')
    assert '.nup' in open(root, encoding='utf-8').read()

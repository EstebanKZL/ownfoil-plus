"""Files > Compress and Files > Combine: the PFS0 combining, the per-run compression
options, and the endpoints (admins run them; collaborators only look)."""
import hashlib
import os
import struct

import fixture
import pytest

from containers import merge


def _pfs0(path, files):
    """Write a minimal PFS0 holding {name: bytes}."""
    merge_files = []
    blobs = {}
    for name, data in files.items():
        blob = path.parent / f'.{path.name}.{name}.blob'
        blob.write_bytes(data)
        blobs[name] = blob
        merge_files.append((name, str(blob), 0, len(data)))
    merge.write_pfs0(str(path), merge_files)
    for blob in blobs.values():
        blob.unlink()
    return path


def _content(path):
    return {name: open(path, 'rb').read()[off:off + size] for name, off, size in merge.read_pfs0(path)}


def test_a_written_pfs0_reads_back_byte_for_byte(tmp_path):
    p = _pfs0(tmp_path / 'a.nsp', {'aa.nca': b'A' * 1000, 'aa.tik': b'T', 'x.cert': b'C' * 7})
    assert _content(p) == {'aa.nca': b'A' * 1000, 'aa.tik': b'T', 'x.cert': b'C' * 7}
    with open(p, 'rb') as f:
        head = f.read(16)
    count, strtab = struct.unpack('<II', head[4:12])
    assert head[:4] == b'PFS0' and count == 3
    assert (16 + 24 * count + strtab) % 0x20 == 0          # header padded like nsz's


def test_combining_takes_every_nca_once_and_leaves_xml_and_deltas_out(tmp_path):
    base = _pfs0(tmp_path / 'base.nsp', {'b1.nca': b'base', 'b2.cnmt.nca': b'meta', 'b1.cnmt.xml': b'<x/>',
                                         'shared.cert': b'cert'})
    upd = _pfs0(tmp_path / 'upd.nsp', {'u1.nca': b'update', 'dd.nca': b'delta', 'shared.cert': b'cert'})
    dlc = _pfs0(tmp_path / 'dlc.nsz', {'d1.ncz': b'dlc', 'd1.tik': b'tik'})
    files = merge.plan([base, upd, dlc], drop_ids={'dd'})
    names = [n for n, *_ in files]
    assert names == ['b1.nca', 'b2.cnmt.nca', 'shared.cert', 'u1.nca', 'd1.ncz', 'd1.tik']
    out = tmp_path / 'Game [0100000000010000].nsz'
    merge.write_pfs0(str(out), files)
    got = _content(out)
    assert got['u1.nca'] == b'update' and got['d1.ncz'] == b'dlc' and 'dd.nca' not in got


def test_the_output_is_nsz_when_a_part_is_compressed():
    assert merge.output_extension(['a.nsp', 'b.nsp']) == 'nsp'
    assert merge.output_extension(['a.nsp', 'b.NSZ']) == 'nsz'


def test_a_combined_file_that_does_not_match_its_parts_is_removed(tmp_path, monkeypatch):
    base = _pfs0(tmp_path / 'base.nsp', {'b1.nca': b'base'})
    upd = _pfs0(tmp_path / 'upd.nsp', {'u1.nca': b'update'})
    import containers.compression as comp
    import settings
    monkeypatch.setattr(settings, 'ensure_keys', lambda action: None)
    monkeypatch.setattr(merge, 'delta_nca_ids', lambda path: set())

    def hashes(path, sri=None):
        return {n[:-4]: hashlib.sha256(d).hexdigest() for n, d in _content(path).items()}
    monkeypatch.setattr(comp, '_nca_content_hashes', hashes)
    out = tmp_path / 'Game.nsp'
    assert merge.combine([base, upd], out, updates=[upd]) == str(out)
    assert set(_content(out)) == {'b1.nca', 'u1.nca'}

    # A part whose content the combined file doesn't hold: refused, nothing left behind.
    monkeypatch.setattr(comp, '_nca_content_hashes',
                        lambda path, sri=None: {'b1': 'x'} if str(path).endswith('Bad.nsp') else hashes(path))
    with pytest.raises(ValueError):
        merge.combine([base, upd], tmp_path / 'Bad.nsp', updates=[upd])
    assert not (tmp_path / 'Bad.nsp').exists()


def test_only_nsp_and_nsz_are_combined(tmp_path):
    with pytest.raises(ValueError):
        merge.combine([tmp_path / 'a.xci'], tmp_path / 'out.nsp', verify=False)


def test_a_foreign_file_is_refused(tmp_path):
    bad = tmp_path / 'bad.nsp'
    bad.write_bytes(b'NOPE' + b'\0' * 20)
    with pytest.raises(ValueError):
        merge.read_pfs0(bad)


# --- splitting a combined file --------------------------------------------------------

def test_a_combined_file_splits_into_one_file_per_content(tmp_path, monkeypatch):
    combined = _pfs0(tmp_path / 'Game [0100000000010000].nsp', {
        'b1.nca': b'base', 'bm.cnmt.nca': b'bmeta', '0100000000010000000000000000000a.tik': b'tb',
        'u1.nca': b'update', 'um.cnmt.nca': b'umeta', '0100000000010800000000000000000a.tik': b'tu',
        'd1.nca': b'dlc', 'dm.cnmt.nca': b'dmeta'})
    contents = [
        {'title_id': '0100000000010000', 'version': 0, 'type': 0x80, 'cnmt': 'bm.cnmt.nca', 'ncas': {'b1'}},
        {'title_id': '0100000000010800', 'version': 65536, 'type': 0x81, 'cnmt': 'um.cnmt.nca', 'ncas': {'u1'}},
        {'title_id': '0100000000011001', 'version': 0, 'type': 0x82, 'cnmt': 'dm.cnmt.nca', 'ncas': {'d1'}},
    ]
    outputs = {(c['title_id'], c['version']): str(tmp_path / f"{c['title_id']}.nsp") for c in contents}
    written = merge.split(combined, outputs, contents=contents, verify=False)
    assert len(written) == 3
    assert set(_content(outputs[('0100000000010000', 0)])) == {'b1.nca', 'bm.cnmt.nca', '0100000000010000000000000000000a.tik'}
    assert set(_content(outputs[('0100000000010800', 65536)])) == {'u1.nca', 'um.cnmt.nca', '0100000000010800000000000000000a.tik'}
    assert set(_content(outputs[('0100000000011001', 0)])) == {'d1.nca', 'dm.cnmt.nca'}


def test_a_failed_split_leaves_nothing_behind(tmp_path):
    combined = _pfs0(tmp_path / 'c.nsp', {'b1.nca': b'base', 'bm.cnmt.nca': b'm', 'u1.nca': b'u', 'um.cnmt.nca': b'n'})
    contents = [{'title_id': 'A', 'version': 0, 'type': 0, 'cnmt': 'bm.cnmt.nca', 'ncas': {'b1'}},
                {'title_id': 'B', 'version': 0, 'type': 0, 'cnmt': 'um.cnmt.nca', 'ncas': {'u1'}}]
    (tmp_path / 'B.nsp').write_bytes(b'already here')
    outputs = {('A', 0): str(tmp_path / 'A.nsp'), ('B', 0): str(tmp_path / 'B.nsp')}
    with pytest.raises(FileExistsError):
        merge.split(combined, outputs, contents=contents, verify=False)
    assert not (tmp_path / 'A.nsp').exists() and (tmp_path / 'B.nsp').read_bytes() == b'already here'


# --- options from Settings -------------------------------------------------------------

def test_delete_originals_is_a_setting_on_by_default():
    from constants import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS['library']['management']['compression']['delete_originals'] is True
    import packing
    assert [packing.compression_level_name(x) for x in (3, 18, 22)] == ['fast', 'balanced', 'max']


def test_keeping_the_source_leaves_it_on_disk(tmp_path, shop_app):
    import tasks
    from db import Files, db
    src = tmp_path / 'g.nsp'
    out = tmp_path / 'g.nsz'
    src.write_bytes(b'x' * 10)
    out.write_bytes(b'y' * 5)
    with shop_app.app.app_context():
        f = Files.query.first()
        f.filepath = str(src)
        db.session.commit()
        tasks._finalize_conversion(f, str(out), 'nsz', True, keep_source=True)
        assert src.exists() and f.filepath == str(out) and f.compressed


# --- endpoints -------------------------------------------------------------------------

def _login(shop_app, user):
    shop_app.client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    return shop_app.client


def test_admins_list_and_queue(shop_app, monkeypatch):
    import tasks as tasks_mod
    queued = []
    monkeypatch.setattr(tasks_mod, 'enqueue_task', lambda name, data=None, **kw: queued.append((name, data)))
    client = _login(shop_app, "admin")
    games = client.get('/api/files/compress').get_json()['games']
    raw = [f['id'] for g in games for f in g['files'] if not f['compressed']]
    assert raw
    r = client.post('/api/files/compress', json={'file_ids': raw, 'action': 'compress'})
    assert r.get_json()['queued'] == len(raw)
    # "Delete the originals" comes from Settings (on by default): nothing kept.
    assert all(n == 'compress_file' and d['keep_original'] is False and d['manual'] for n, d in queued)
    queued.clear()
    r = client.post('/api/files/compress', json={'file_ids': raw, 'action': 'decompress'})
    assert r.get_json()['queued'] == 0           # none of them is compressed
    assert isinstance(client.get('/api/files/combine').get_json()['games'], list)
    queued.clear()
    r = client.post('/api/files/combine', json={'title_ids': ['0100000000010000', 'nope']})
    assert r.get_json()['queued'] == 1 and queued == [('combine_title', {'title_id': '0100000000010000',
                                                                         'delete_parts': True})]


def test_collaborators_look_but_do_not_run(shop_app):
    from db import User, db
    with shop_app.app.app_context():
        User.query.filter_by(user="shopper").update({"collaborator_access": True})
        db.session.commit()
    client = _login(shop_app, "shopper")
    assert client.get('/api/files/compress').status_code == 200
    assert client.post('/api/files/compress', json={'file_ids': [1]}).status_code == 403
    assert client.post('/api/files/combine', json={'title_ids': ['0100000000010000']}).status_code == 403


def test_a_combined_file_is_listed_and_split_on_request(shop_app, monkeypatch):
    import tasks as tasks_mod
    from db import Files, db
    queued = []
    monkeypatch.setattr(tasks_mod, 'enqueue_task', lambda name, data=None, **kw: queued.append((name, data)))
    with shop_app.app.app_context():
        f = Files.query.filter(Files.extension == 'nsp').first()
        f.multicontent = True
        db.session.commit()
        fid = f.id
    client = _login(shop_app, "admin")
    games = client.get('/api/files/combine').get_json()['games']
    assert any(g['state'] == 'combined' and g['file_id'] == fid for g in games)
    r = client.post('/api/files/combine', json={'action': 'split', 'file_ids': [fid, 999999]})
    assert r.get_json()['queued'] == 1
    assert queued == [('split_file', {'file_id': fid, 'delete_original': True})]


def test_every_cnmt_of_a_bundled_nsp_is_read():
    """A combined NSP holds one CNMT per content; nsz's Nsp.cnmt() returns only the first,
    which identified a bundle as its base game alone (seen: a combined file listed as a
    duplicate of its base, named like it, and never offered to split)."""
    from nsz.Fs import Nca, Nsp
    from containers.cnmt import get_cnmts

    def nca(path):
        n = Nca.Nca.__new__(Nca.Nca)
        n._path = path
        return n

    class Bundle(Nsp.Nsp):
        def __init__(self, files):
            self._files = files

        def __iter__(self):
            return iter(self._files)

    files = [nca('aa.cnmt.nca'), nca('b1.nca'), nca('bb.cnmt.nca'), nca('u1.nca'), nca('cc.cnmt.nca')]
    assert [c._path for c in get_cnmts(Bundle(files))] == ['aa.cnmt.nca', 'bb.cnmt.nca', 'cc.cnmt.nca']


def test_identifying_again_organizes_again(shop_app):
    from db import Files, db, reset_file_identification
    with shop_app.app.app_context():
        f = Files.query.first()
        f.organized = True
        reset_file_identification(f)
        assert f.organized is False and f.multicontent is False


def test_a_bundle_tells_the_library_what_it_holds(shop_app):
    from db import Files, db
    with shop_app.app.app_context():
        f = Files.query.filter(Files.extension == 'nsp').first()
        f.multicontent = True
        db.session.commit()
    client = _login(shop_app, "admin")
    q = '{ apps(groupByAppId: true, appType: [BASE], page: 1, pageSize: 50) { items { downloadableFile { format contents } } } }'
    items = client.post('/api/graphql', json={'query': q}).get_json()['data']['apps']['items']
    contents = [i['downloadableFile']['contents'] for i in items if i['downloadableFile']]
    assert any(c and c[0] == 'BASE' for c in contents)
    js = open(os.path.join(os.path.dirname(__file__), '..', 'app', 'static', 'js', 'library.js'), encoding='utf-8').read()
    # A badge inside the card ("Bundle 1G+1U+5D"), not text on the cover.
    assert 'bundleBadge(game.contents, I18N.bundle)' in js and 'downloadableFile { format contents }' in js
    assert 'library-cover-bundle' not in js
    common = open(os.path.join(os.path.dirname(__file__), '..', 'app', 'static', 'js', 'library-common.js'), encoding='utf-8').read()
    assert 'function bundleCounts(contents)' in common and "'G'" in common


def test_two_copies_of_a_nup_are_duplicates_of_each_other_only(shop_app):
    """Seen: "Donkey Kong Bananza [...].nup" and its "(3)" copy never showed under
    Duplicates - NUPs were left out of the comparison. They're compared with NUPs now
    (never with an NSP of the same game), and a bundle's copies make one group, not one
    per app they hold."""
    import library
    from db import Apps, Files, db
    with shop_app.app.app_context():
        nsp = Files.query.filter(Files.extension == 'nsp').first()
        apps = list(nsp.apps)
        extra = Apps.query.filter(Apps.id.notin_([a.id for a in apps])).first()
        nups = []
        for n in (1, 2):
            f = Files(library_id=nsp.library_id, filepath=f'{nsp.filepath}.{n}.nup', folder=nsp.folder,
                      filename=f'copy{n}.nup', extension='nup', size=10, identified=True, multicontent=True)
            db.session.add(f)
            db.session.flush()
            for a in apps + ([extra] if extra else []):
                a.files.append(f)
            nups.append(f.id)
        if extra:
            extra.owned = True
        db.session.commit()
        groups = [{f.id for f in files} for _, files in library.duplicate_file_groups()]
        assert groups.count(set(nups)) == 1                      # one group for the pair
        assert not any(nsp.id in g and (g & set(nups)) for g in groups)   # never mixed with the NSP

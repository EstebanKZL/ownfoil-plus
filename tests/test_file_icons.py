"""A game titledb has no cover of takes the official icon its own file carries: a NUP's
from its metadata, an NSP/XCI's from its Control NCA (with keys) - used only while
titledb has none."""
import struct

import pytest

from containers import nup
from containers.container import pick_icon
from test_nup import GAME, DLC, _tlv, build_nup

JPEG = b'\xff\xd8\xff\xe0' + b'icon' * 20


def _icons(**by_lang):
    out = b''
    for lang, data in by_lang.items():
        tag = lang.encode('ascii')
        out += bytes([len(tag)]) + tag + struct.pack('<I', len(data)) + data
    return out


def test_the_preferred_language_icon_is_taken():
    assert pick_icon({'icon_Japanese.dat': b'J', 'icon_AmericanEnglish.dat': b'E'}) == b'E'
    assert pick_icon({'Japanese': b'J', 'Spanish': b'S'}) == b'S'
    assert pick_icon({'Klingon': b'K'}) == b'K'
    assert pick_icon({}) is None


def test_a_nup_gives_the_icon_of_its_game(tmp_path):
    path = tmp_path / 'game.nup'
    build_nup(str(path), metas=[
        _tlv(0x0005, b'Test Game [0100ABCD12340000][v0]') + _tlv(0x000A, _icons(Japanese=b'J', AmericanEnglish=JPEG)),
        _tlv(0x0005, b'Test Game'),
        b'',
    ])
    assert nup.read_icon(str(path)) == JPEG


def test_a_nup_without_icons_gives_none(tmp_path):
    path = tmp_path / 'game.nup'
    build_nup(str(path))
    assert nup.read_icon(str(path)) is None


def test_the_files_artwork_only_fills_in_for_titledb():
    from titledb import schema, store
    sql = store._merge_sql(single_id=False)
    # icon_url: custom, then titledb, then the file's; a name: custom, extract, titledb.
    assert 'COALESCE(o_custom.icon_url, o_titledb.icon_url, o_extract.icon_url)' in sql
    assert 'COALESCE(o_custom.name, o_extract.name, o_titledb.name)' in sql
    assert schema.ARTWORK_PRIORITY == ('custom', 'titledb', 'extract')


def test_identification_stores_the_files_icon_when_titledb_has_none(monkeypatch, tmp_path):
    import tasks
    import titledb
    calls = []
    monkeypatch.setattr(tasks.titles_lib, 'get_title_record', lambda tid: {'name': 'x'})
    monkeypatch.setattr(titledb.store, 'list_overrides', lambda source: {})
    monkeypatch.setattr(titledb.store, 'set_override', lambda tid, rec, source: calls.append((tid, rec, source)) or (True, None))
    monkeypatch.setattr(tasks.media, 'store_bytes', lambda kind, data: ('abc.jpg', (256, 256)))
    monkeypatch.setattr(nup, 'read_icon', lambda path: JPEG)
    tasks._store_file_icon('game.nup', 'nup', ['0100ABCD12340000'])
    assert calls == [('0100ABCD12340000', {'iconUrl': '/api/media/0100ABCD12340000/icon/0/client/abc.jpg'}, 'extract')]

    # titledb has a cover: the file is not even read.
    calls.clear()
    monkeypatch.setattr(tasks.titles_lib, 'get_title_record', lambda tid: {'iconUrl': 'https://x/i.jpg'})
    monkeypatch.setattr(nup, 'read_icon', lambda path: pytest.fail('read for nothing'))
    tasks._store_file_icon('game.nup', 'nup', ['0100ABCD12340000'])
    assert calls == []

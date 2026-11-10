"""NUP reading as Switch Library Manager Web 2.0.x reads it (containers/nup.py,
library.py): the second rule for metadata types counted from 0, the metadata no hash
covers checked, hostile tables of contents refused, a game rebuilt with its update in it
up to date, and a NUP never making a separate update file obsolete."""
import struct
import types

import pytest

from containers import nup
from test_nup import DLC, GAME, _tlv, build_nup

BUILD_ID = b'\x11' * 32
NPDM = b'META' + b'\0' * 28


# --- metadata types counted from 0 ----------------------------------------------------------

def test_a_dlc_block_counted_from_zero_is_read_one_up(tmp_path):
    """A block without an NPDM (a DLC's) has no type 0 to tell it: a record 0x0007 that is
    not the 32 bytes of a build ID does - the name of its source dump, one below its place.
    Read as it was, the name came from the publisher's record."""
    metas = [_tlv(0x0005, b'Game') + _tlv(0x0004, b'1.0.0'), _tlv(0x0005, b'Game'),
             _tlv(0x0004, b'Expansion Pass') + _tlv(0x0005, b'Nintendo') + _tlv(0x0007, b'dump.xci')]
    container = nup.read(build_nup(str(tmp_path / 'z.nup'), metas=metas))
    dlc = container['packages'][2]
    assert dlc['zero_based'] is True
    assert dlc['meta'][0x0005] == b'Expansion Pass' and dlc['meta'][0x0006] == b'Nintendo'
    assert dlc['meta'][0x0008] == b'dump.xci'
    assert container['packages'][0]['zero_based'] is False


def test_a_real_build_id_keeps_the_types_as_they_are(tmp_path):
    metas = [_tlv(0x0001, NPDM) + _tlv(0x0005, b'Game') + _tlv(0x0007, BUILD_ID), b'', b'']
    pkg = nup.read(build_nup(str(tmp_path / 'b.nup'), metas=metas))['packages'][0]
    assert pkg['zero_based'] is False and pkg['meta'][0x0005] == b'Game'


# --- the metadata no hash covers -------------------------------------------------------------

@pytest.mark.parametrize("block,expected", [
    # Counted from 0 (the NPDM at 0): the build ID is the record 6, read one up.
    (_tlv(0x0000, NPDM) + _tlv(0x0006, b'\x22' * 16), 'build ID'),
    (_tlv(0x0001, NPDM) + _tlv(0x0005, b'\xff\xfe broken'), 'UTF-8'),
    (_tlv(0x0009, b'\x05en-us' + struct.pack('<I', 999) + b'short'), 'languages'),
])
def test_check_the_files_tells_damaged_metadata(tmp_path, block, expected):
    """No hash covers the metadata: a build ID that is not 32 bytes, text that is not
    UTF-8 or names by language that run past their record are told as damage."""
    metas = [block, _tlv(0x0005, b'Game'), b'']
    ok, error = nup.verify(build_nup(str(tmp_path / 'm.nup'), metas=metas))
    assert not ok and expected in error and 'metadata' in error


def test_sound_metadata_passes(tmp_path):
    names = b'\x05en-us' + struct.pack('<I', 4) + b'Game' + b'\x02ja' + struct.pack('<I', 6) + 'ゲー'.encode()
    metas = [_tlv(0x0001, NPDM) + _tlv(0x0005, b'Game') + _tlv(0x0007, BUILD_ID) + _tlv(0x0009, names),
             _tlv(0x0005, b'Game'), b'']
    assert nup.verify(build_nup(str(tmp_path / 's.nup'), metas=metas)) == (True, None)


# --- hostile tables of contents --------------------------------------------------------------

def test_a_name_longer_than_the_consoles_is_refused(tmp_path):
    path = build_nup(str(tmp_path / 'n.nup'), file_names=[b'x' * 0x301, b'data.bin', b'dlc.bin'])
    with pytest.raises(nup.NupError, match='name'):
        nup.read(path)


def test_folders_sharing_their_children_are_refused(tmp_path):
    """Folders whose ranges of children overlap make every walk go through the same
    children again and again: a crafted NUP kept a reader at it for hours."""
    path = build_nup(str(tmp_path / 'o.nup'), dir_children=[(0, 3), (0, 1), (1, 1)])
    with pytest.raises(nup.NupError, match='share'):
        nup.read(path)


# --- the library -------------------------------------------------------------------------------

@pytest.fixture
def library(tmp_path, monkeypatch):
    import db as db_mod
    import titledb
    from app import create_app
    from db import Libraries, db, init_db
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    init_db(app)
    titledb.store.create_titledb(str(config / "titles.db"))
    ctx = app.app_context()
    ctx.push()
    lib = Libraries(path=str(tmp_path / "games"))
    db.session.add(lib)
    db.session.commit()
    yield types.SimpleNamespace(app=app, lib=lib, db=db, tmp=tmp_path)
    ctx.pop()


def _game(env, apps):
    """A title with its apps: (app_id, version, type, owned, file extension or None)."""
    from db import Apps, Files, Titles
    title = Titles(title_id=f'{GAME:016X}', have_base=True)
    env.db.session.add(title)
    env.db.session.flush()
    for n, (app_id, version, kind, owned, ext) in enumerate(apps):
        app = Apps(title_id=title.id, app_id=app_id, app_version=str(version), app_type=kind, owned=owned)
        env.db.session.add(app)
        if ext:
            f = Files(library_id=env.lib.id, filepath=str(env.tmp / f'f{n}.{ext}'), filename=f'f{n}.{ext}',
                      extension=ext, size=10, identified=True, multicontent=False)
            env.db.session.add(f)
            env.db.session.flush()
            app.files.append(f)
    env.db.session.commit()
    return title


def test_a_game_rebuilt_with_its_update_in_it_is_up_to_date(library):
    """hacBrewPackLZ packs a game with its update in it: the game's own version is the
    update's. It showed an update available."""
    from db import Titles
    from library import update_titles
    base, upd = f'{GAME:016X}', f'{GAME | 0x800:016X}'
    _game(library, [(base, 131072, 'BASE', True, 'nsp'),
                    (upd, 65536, 'UPDATE', False, None), (upd, 131072, 'UPDATE', False, None)])
    update_titles()
    assert Titles.query.filter_by(title_id=base).one().up_to_date is True


def test_an_update_in_a_nup_never_makes_an_nsp_update_obsolete(library):
    """The NUP is for emulators, the NSP to install: an older update NSP beside a newer
    update in a NUP is not listed - nor deleted - as an old update."""
    from library import outdated_update_groups
    base, upd = f'{GAME:016X}', f'{GAME | 0x800:016X}'
    _game(library, [(base, 0, 'BASE', True, 'nsp'),
                    (upd, 65536, 'UPDATE', True, 'nsp'), (upd, 131072, 'UPDATE', True, 'nup')])
    assert outdated_update_groups() == []


def test_two_install_files_still_compare_as_before(library):
    from library import outdated_update_groups
    base, upd = f'{GAME:016X}', f'{GAME | 0x800:016X}'
    _game(library, [(base, 0, 'BASE', True, 'nsp'),
                    (upd, 65536, 'UPDATE', True, 'nsp'), (upd, 131072, 'UPDATE', True, 'nsz')])
    groups = outdated_update_groups()
    assert len(groups) == 1 and [f.extension for _, f in groups[0][2]] == ['nsp']


def test_the_deleter_never_takes_a_nup(library, monkeypatch):
    import library as library_mod
    removed = []
    monkeypatch.setattr(library_mod, "remove_file_from_apps", lambda fid: removed.append(fid))
    base, upd = f'{GAME:016X}', f'{GAME | 0x800:016X}'
    _game(library, [(base, 0, 'BASE', True, 'nsp'),
                    (upd, 65536, 'UPDATE', True, 'nup'), (upd, 131072, 'UPDATE', True, 'nsp')])
    for path in ('f1.nup', 'f2.nsp'):
        (library.tmp / path).write_bytes(b'x')
    library_mod.remove_outdated_update_files()
    assert (library.tmp / 'f1.nup').exists() and removed == []

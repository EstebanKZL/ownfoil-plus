"""Organize on a disk that doesn't tell upper and lower case apart (Windows, macOS, a NAS
share): a file or folder whose name only changes its case is renamed in place, not
given a "(2)" copy of itself, and the change doesn't come back on the next run."""
import os

import pytest

from library import move_companion_files, rename_case_only, same_entry, set_folder_case


def _case_insensitive(path):
    probe = os.path.join(path, 'CaseProbe')
    os.makedirs(probe, exist_ok=True)
    try:
        return os.path.exists(os.path.join(path, 'caseprobe'))
    finally:
        os.rmdir(probe)


@pytest.fixture
def ci_dir(tmp_path):
    if not _case_insensitive(str(tmp_path)):
        pytest.skip('this disk tells upper and lower case apart')
    return tmp_path


def test_same_entry_tells_one_file_from_another(tmp_path):
    a, b = tmp_path / 'a.nsp', tmp_path / 'b.nsp'
    a.write_text('a')
    b.write_text('b')
    assert same_entry(str(a), str(a))
    assert not same_entry(str(a), str(b))
    assert not same_entry(str(a), str(tmp_path / 'missing.nsp'))


def test_a_file_whose_name_only_changes_case_is_renamed(ci_dir):
    old = ci_dir / 'zelda.nsp'
    old.write_text('game')
    rename_case_only(str(old), str(ci_dir / 'Zelda.nsp'))
    assert os.listdir(ci_dir) == ['Zelda.nsp']
    assert (ci_dir / 'Zelda.nsp').read_text() == 'game'


def test_a_folder_whose_name_only_changes_case_is_renamed(ci_dir):
    (ci_dir / 'the legend of zelda' / 'dlc').mkdir(parents=True)
    (ci_dir / 'the legend of zelda' / 'game.nsp').write_text('game')
    set_folder_case(str(ci_dir), str(ci_dir / 'The Legend of Zelda' / 'DLC'))
    assert os.listdir(ci_dir) == ['The Legend of Zelda']
    assert sorted(os.listdir(ci_dir / 'The Legend of Zelda')) == ['DLC', 'game.nsp']


def test_folders_above_the_library_are_never_touched(ci_dir):
    lib = ci_dir / 'lib'
    lib.mkdir()
    set_folder_case(str(ci_dir / 'LIB'), str(ci_dir / 'LIB' / 'Game'))
    assert os.listdir(ci_dir) == ['lib']


def test_a_missing_folder_is_left_for_makedirs(tmp_path):
    # Nothing to rename: the folder will be created as the template says.
    set_folder_case(str(tmp_path), str(tmp_path / 'New' / 'Folder'))
    assert os.listdir(tmp_path) == []


def test_par2_recovery_data_travels_with_the_game(tmp_path):
    lib = tmp_path / 'lib'
    (lib / 'in').mkdir(parents=True)
    (lib / 'in' / 'game.par2').write_text('recovery')
    (lib / 'in' / 'other.nsp').write_text('x')
    (lib / 'out').mkdir()
    move_companion_files(str(lib / 'in' / 'game.nsp'), str(lib / 'out' / 'Game.nsp'), str(lib))
    assert (lib / 'out' / 'Game.par2').read_text() == 'recovery'

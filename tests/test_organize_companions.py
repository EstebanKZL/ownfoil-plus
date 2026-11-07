"""Organize takes a game's NFO, SFV and proof files along (library.move_companion_files)."""
import os

from library import move_companion_files


def _touch(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def test_a_file_named_as_the_game_takes_its_new_name(tmp_path):
    lib = tmp_path / "lib"
    old = lib / "Downloads" / "game.nsp"
    new = lib / "Zelda" / "Zelda [0100][v0].nsp"
    _touch(str(lib / "Downloads" / "game.nfo"))
    _touch(str(lib / "Downloads" / "other.nsp"))           # keeps the folder from being a release
    _touch(str(lib / "Downloads" / "readme.txt"))
    os.makedirs(new.parent)
    moved, skipped = move_companion_files(str(old), str(new), str(lib))
    assert (lib / "Zelda" / "Zelda [0100][v0].nfo").exists()
    assert not (lib / "Downloads" / "game.nfo").exists()
    # Not named as the game, and the folder still holds another game: it stays.
    assert (lib / "Downloads" / "readme.txt").exists()
    assert skipped == []


def test_a_release_folder_hands_over_everything_else(tmp_path):
    lib = tmp_path / "lib"
    rel = lib / "Zelda.Release-GRP"
    old, new = rel / "zelda.nsp", lib / "Zelda" / "Zelda.nsp"
    _touch(str(rel / "zelda.sfv"))
    _touch(str(rel / "grp.nfo"))
    _touch(str(rel / "Proof" / "front.jpg"))
    os.makedirs(new.parent)
    move_companion_files(str(old), str(new), str(lib))
    assert (lib / "Zelda" / "Zelda.sfv").exists()
    assert (lib / "Zelda" / "grp.nfo").exists()
    assert (lib / "Zelda" / "Proof" / "front.jpg").exists()
    assert os.listdir(rel) == []


def test_a_taken_name_stays_where_it_is(tmp_path):
    lib = tmp_path / "lib"
    old, new = lib / "in" / "game.nsp", lib / "out" / "Game.nsp"
    _touch(str(lib / "in" / "game.nfo"), "mine")
    _touch(str(lib / "out" / "Game.nfo"), "already there")
    moved, skipped = move_companion_files(str(old), str(new), str(lib))
    assert skipped and (lib / "in" / "game.nfo").exists()
    assert (lib / "out" / "Game.nfo").read_text(encoding="utf-8") == "already there"


def test_the_library_root_is_never_emptied(tmp_path):
    lib = tmp_path / "lib"
    _touch(str(lib / "notes.txt"))
    os.makedirs(lib / "Game")
    move_companion_files(str(lib / "game.nsp"), str(lib / "Game" / "game.nsp"), str(lib))
    assert (lib / "notes.txt").exists()


def test_it_is_on_by_default_and_can_be_turned_off():
    from constants import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["library"]["management"]["organizer"]["move_companions"] is True
    import inspect
    import library
    assert "organizer_settings.get('move_companions', True)" in inspect.getsource(library.organize_file)
    root = os.path.join(os.path.dirname(__file__), "..", "app")
    assert 'id="moveCompanionsCheck"' in open(os.path.join(root, "templates", "settings.html"), encoding="utf-8").read()
    assert "move_companions: getCheckboxStatus" in open(os.path.join(root, "static", "js", "settings.js"), encoding="utf-8").read()

"""Security fixes: a library file
linking into the config folder is never served, an upload belongs to whoever started it,
and a saved ntfy token is not handed to a new server."""
import os

import pytest

import uploads
from utils import servable_library_file


def test_a_file_resolving_into_the_config_folder_is_not_servable(tmp_path, monkeypatch):
    import constants
    config = tmp_path / "config"
    config.mkdir()
    (config / "keys.txt").write_text("secret")
    monkeypatch.setattr(constants, "CONFIG_DIR", str(config))
    lib = tmp_path / "games"
    lib.mkdir()
    game = lib / "game.nsp"
    game.write_text("x")
    assert servable_library_file(str(game))
    assert not servable_library_file(str(config / "keys.txt"))
    link = lib / "keys.nsp"
    try:
        os.symlink(config / "keys.txt", link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need extra rights on this system")
    assert not servable_library_file(str(link))


def test_every_download_route_checks_it():
    root = os.path.join(os.path.dirname(__file__), "..", "app")
    app_src = open(os.path.join(root, "app.py"), encoding="utf-8").read()
    assert app_src.count("servable_library_file(") >= 2
    sphaira = open(os.path.join(root, "clients", "sphaira.py"), encoding="utf-8").read()
    assert "servable_library_file(file.filepath)" in sphaira


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads, "SESSION_DIR", str(tmp_path / "sessions"))
    lib = tmp_path / "lib"
    lib.mkdir()
    return str(lib)


def test_an_upload_belongs_to_whoever_started_it(library):
    state = uploads.start(library, "game.nsp", 10, [library], user="alice")
    with pytest.raises(uploads.UploadError) as e:
        uploads.start(library, "game.nsp", 10, [library], user="bob")
    assert e.value.code == "exists"
    for call in (lambda: uploads.status(state["id"], "bob"),
                 lambda: uploads.cancel(state["id"], "bob"),
                 lambda: uploads.append(state["id"], 0, None, 1, user="bob")):
        with pytest.raises(uploads.UploadError) as e:
            call()
        assert e.value.code == "not_found"
    assert uploads.list_sessions("bob") == []
    assert [s["id"] for s in uploads.list_sessions("alice")] == [state["id"]]
    # Alice resumes it.
    assert uploads.start(library, "game.nsp", 10, [library], user="alice")["id"] == state["id"]
    uploads.cancel(state["id"], "alice")


def test_a_saved_ntfy_token_is_not_sent_to_a_new_server(shop_app):
    from settings import get_settings, set_notification_settings
    with shop_app.app.app_context():
        set_notification_settings({"ntfy": {"server": "https://ntfy.example", "token": "tk"}})
        assert get_settings()["notifications"]["ntfy"]["token"] == "tk"
        # Same token sent back with another address: dropped.
        set_notification_settings({"ntfy": {"server": "https://evil.example", "token": "tk"}})
        assert get_settings()["notifications"]["ntfy"]["token"] == ""
        # Written again on purpose for the new server: kept.
        set_notification_settings({"ntfy": {"server": "https://evil.example", "token": "new"}})
        assert get_settings()["notifications"]["ntfy"]["token"] == "new"

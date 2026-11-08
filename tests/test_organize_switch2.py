"""Nintendo Switch 2 games (title ids 04...) are organized and renamed like the others,
NUP files included: same templates, same folders."""
import json
import types

import pytest

import db as db_mod
import titledb
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC, APP_TYPE_UPD
from db import Apps, Files, Libraries, Titles, db, init_db
from library import organize_file

S2_ID = "04005A0021B8C000"
S2_UPD = "04005A0021B8C800"

SETTINGS = {
    "templates": {
        "base": "{titleName}/{titleName} [{appId}][v{appVersion}]",
        "update": "{titleName}/{titleName} [{appId}][v{appVersion}]",
        "dlc": "{titleName}/{appName} [{appId}][v{appVersion}]",
        "multi": "{titleName}/{titleName} [{titleId}]",
    },
    "windows_compatible": False, "clean_names": False, "name_region": "", "name_language": "",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    lib_dir = tmp_path / "games"
    lib_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    ctx = app.app_context()
    ctx.push()
    init_db(app)
    region_file = titledb_dir / "titles.US.en.json"
    region_file.write_text(json.dumps({S2_ID: {"id": S2_ID, "name": "Nintendo Switch 2 Welcome Tour"}}))
    (titledb_dir / "cnmts.json").write_text("{}")
    (titledb_dir / "versions.json").write_text("{}")
    titledb.store.import_from_json(str(region_file), "US.en")
    library = Libraries(path=str(lib_dir))
    db.session.add(library)
    db.session.flush()
    title = Titles(title_id=S2_ID, have_base=True)
    db.session.add(title)
    db.session.flush()

    def seed(filename, contents):
        path = lib_dir / filename
        path.write_bytes(b"RAWDATA")
        ext = filename.rsplit('.', 1)[1]
        f = Files(library_id=library.id, filepath=str(path), folder=str(lib_dir), filename=filename,
                  extension=ext, size=7, identified=True, multicontent=len(contents) > 1,
                  nb_content=len(contents))
        db.session.add(f)
        db.session.flush()
        for app_id, version, app_type in contents:
            a = Apps(title_id=title.id, app_id=app_id, app_version=version, app_type=app_type, owned=True)
            db.session.add(a)
            db.session.flush()
            a.files.append(f)
        db.session.commit()
        return f

    yield types.SimpleNamespace(lib_dir=lib_dir, seed=seed)
    ctx.pop()


def test_a_switch2_nsp_is_organized(env):
    f = env.seed("whatever.nsp", [(S2_ID, "0", APP_TYPE_BASE)])
    assert organize_file(f, str(env.lib_dir), SETTINGS)
    assert f.filepath.endswith(
        "Nintendo Switch 2 Welcome Tour/Nintendo Switch 2 Welcome Tour [04005A0021B8C000][v0].nsp".replace("/", __import__("os").sep))


def test_a_switch2_nup_with_base_and_update_is_organized(env):
    f = env.seed("Nintendo Switch 2 Welcome Tour.nup",
                 [(S2_ID, "0", APP_TYPE_BASE), (S2_UPD, "65536", APP_TYPE_UPD)])
    assert organize_file(f, str(env.lib_dir), SETTINGS)
    assert f.filepath.endswith("Nintendo Switch 2 Welcome Tour [04005A0021B8C000].nup")


@pytest.mark.parametrize("template", ["{titleName}/{titleName} [{titleId}][v{appVersion}]",
                                      "{titleName}/{appName} [{appId}][v{appVersion}]"])
def test_a_bundle_takes_any_template_field(env, template):
    """A file holding the base, the update and DLC together: the "multi" template may
    use every field the single-content ones do, not only titleName and titleId."""
    f = env.seed("Nintendo Switch 2 Welcome Tour.nup",
                 [(S2_UPD, "65536", APP_TYPE_UPD), (S2_ID, "0", APP_TYPE_BASE)])
    settings = {**SETTINGS, "templates": {**SETTINGS["templates"], "multi": template}}
    assert organize_file(f, str(env.lib_dir), settings)
    assert f.filepath.endswith("[04005A0021B8C000][v65536].nup")


def test_package_contents_and_size_in_the_name(env):
    """Asked for (as Switch Library Manager Web names them):
    "Nintendo Switch 2 Welcome Tour [Base + Update] [3.23 GB].nup"."""
    from db import db
    f = env.seed("tour.nup", [(S2_ID, "0", APP_TYPE_BASE), (S2_UPD, "65536", APP_TYPE_UPD)])
    f.size = int(3.23 * 1024 ** 3)
    db.session.commit()
    settings = {**SETTINGS, "templates": {**SETTINGS["templates"],
                                          "multi": "{titleName}/{titleName} [{packageNames}] [{sizeGb} GB]"}}
    assert organize_file(f, str(env.lib_dir), settings)
    assert f.filepath.endswith("Nintendo Switch 2 Welcome Tour [Base + Update] [3.23 GB].nup")


def test_package_contents_is_counted(env):
    """{packageContents} reads "1G+1U+5D", as file names have always said it."""
    f = env.seed("tour.nup", [(S2_ID, "0", APP_TYPE_BASE), (S2_UPD, "65536", APP_TYPE_UPD)])
    settings = {**SETTINGS, "templates": {**SETTINGS["templates"],
                                          "multi": "{titleName}/{titleName} - [{appId}][{packageContents}]"}}
    assert organize_file(f, str(env.lib_dir), settings)
    assert f.filepath.endswith("Nintendo Switch 2 Welcome Tour - [04005A0021B8C000][1G+1U].nup")


def test_package_contents_reads_like_its_parts():
    from library import package_contents
    assert package_contents([APP_TYPE_DLC, APP_TYPE_BASE, APP_TYPE_UPD, APP_TYPE_DLC]) == "Base + Update + DLC"
    assert package_contents([APP_TYPE_BASE]) == "Base"
    assert package_contents([APP_TYPE_UPD]) == "Update"


def test_package_counts_read_like_switch_library_names():
    from library import package_counts
    assert package_counts([APP_TYPE_BASE, APP_TYPE_UPD] + [APP_TYPE_DLC] * 5) == "1G+1U+5D"
    assert package_counts([APP_TYPE_UPD, APP_TYPE_BASE]) == "1G+1U"
    assert package_counts([APP_TYPE_UPD, APP_TYPE_DLC]) == "1U+1D"



def test_a_template_with_an_unknown_field_is_named_on_save():
    """Seen: {packageNames} saved on a version that didn't know it - every bundle stayed
    unorganized and nothing said why. Settings refuses it now, naming the field."""
    from library import template_errors
    assert template_errors({'base': '{titleName} [{appId}]', 'multi': '{titleName} [{packageNames}]'}) == []
    assert template_errors({'multi': '{titleName} [{packageNamez}]'}) == [('multi', '{packageNamez}')]
    assert template_errors({'dlc': '{titleName'})[0][0] == 'dlc'

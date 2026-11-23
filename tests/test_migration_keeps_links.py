"""A migration that touches `files` must never lose what points at it.

6.2.5.62's first `files.keep` migration added the column through Alembic's batch mode:
on SQLite that rebuilds the table (copy, drop, rename), and with the foreign keys on, the
drop cascaded into `app_files` - every file stayed "identified" but lost its link to its
game, so games, covers and counts vanished until each file was identified again. These
tests run the real upgrade on a library with links and check they all survive, and that
a library already hit is put right (its orphaned files are identified again).
"""
import sqlite3

import pytest

import db as db_mod
import titledb
from app import create_app
from constants import APP_TYPE_BASE
from db import Apps, Files, Libraries, Titles, db, init_db


def _library(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    # A start runs the migrations (init_db skips them under a "db" command line), and
    # keeps its pre-migration backup in this test's own folder.
    monkeypatch.setattr("sys.argv", ["ownfoil"])
    monkeypatch.setattr(db_mod, "CONFIG_DIR", str(config))
    # The "is a migration needed" check reads this URL, not DB_FILE.
    monkeypatch.setattr(db_mod, "OWNFOIL_DB", f"sqlite:///{config / 'ownfoil.db'}")
    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    init_db(app)
    with app.app_context():
        lib = Libraries(path=str(tmp_path / "games"))
        title = Titles(title_id="0100000000010000", have_base=True)
        db.session.add_all([lib, title])
        db.session.flush()
        for i in range(3):
            app_row = Apps(title_id=title.id, app_id=f"010000000001000{i}", app_version="0",
                           app_type=APP_TYPE_BASE, owned=True)
            f = Files(library_id=lib.id, filepath=str(tmp_path / f"g{i}.nsp"), folder=str(tmp_path),
                      filename=f"g{i}.nsp", extension="nsp", size=1, identified=True)
            db.session.add_all([app_row, f])
            db.session.flush()
            app_row.files.append(f)
        db.session.commit()
    return app, str(config / "ownfoil.db")


def _rewind_to(db_path, revision, drop_keep):
    """Put the database back as the revision before: the column it adds gone."""
    con = sqlite3.connect(db_path)
    if drop_keep:
        con.execute("ALTER TABLE files DROP COLUMN keep")
    con.execute("UPDATE alembic_version SET version_num = ?", (revision,))
    con.commit()
    con.close()


def _counts(db_path):
    con = sqlite3.connect(db_path)
    try:
        links = con.execute("SELECT COUNT(*) FROM app_files").fetchone()[0]
        orphans = con.execute(
            "SELECT COUNT(*) FROM files WHERE identified = 1 "
            "AND id NOT IN (SELECT file_id FROM app_files)").fetchone()[0]
        return links, orphans
    finally:
        con.close()


def test_upgrading_from_6_2_5_61_keeps_every_link(tmp_path, monkeypatch):
    app, path = _library(tmp_path, monkeypatch)
    assert _counts(path) == (3, 0)
    _rewind_to(path, "b8c9d0e1f2a5", drop_keep=True)
    init_db(app)                      # runs the upgrade, as a start does
    assert _counts(path) == (3, 0)
    con = sqlite3.connect(path)
    assert "keep" in [r[1] for r in con.execute("PRAGMA table_info(files)")]
    con.close()


def test_a_library_already_hit_gets_its_files_identified_again(tmp_path, monkeypatch):
    """Links lost by the bad migration: the files are marked unidentified, so the next
    scan identifies them again and they get their games back."""
    app, path = _library(tmp_path, monkeypatch)
    con = sqlite3.connect(path)
    con.execute("DELETE FROM app_files")          # what the bad migration left
    con.commit()
    con.close()
    assert _counts(path) == (0, 3)
    _rewind_to(path, "c9d0e1f2a3b6", drop_keep=False)
    init_db(app)
    con = sqlite3.connect(path)
    unidentified = con.execute("SELECT COUNT(*) FROM files WHERE identified = 0 "
                               "AND identification_attempts = 0 AND identification_type = 'relink'").fetchone()[0]
    con.close()
    assert unidentified == 3 and _counts(path) == (0, 0)


def test_a_file_linked_again_is_not_announced_as_new():
    import os
    tasks_js = open(os.path.join(os.path.dirname(__file__), "..", "app", "tasks.py"), encoding="utf-8").read()
    assert "was_identified = bool(file.identified) or file.identification_type == 'relink'" in tasks_js

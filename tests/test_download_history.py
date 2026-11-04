"""Download history (Stats > Downloads): what gets recorded on each counted download,
and the stats endpoint built on it."""
import base64
import datetime
import os

import fixture
import pytest

from db import DownloadEvent, Files, db

GAME_ID = "0100000000010000"


def _basic(user):
    token = base64.b64encode(f"{user}:{fixture.PASSWORDS[user]}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _base_file():
    return Files.query.filter(Files.filename.like(f"%[{GAME_ID}][v0].nsp")).one()


def _events():
    return DownloadEvent.query.order_by(DownloadEvent.id).all()


@pytest.fixture
def admin_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code == 302
    return shop_app.client


# --- recording ---------------------------------------------------------------------

def test_a_console_download_records_user_client_and_title(shop_app):
    with shop_app.app.app_context():
        file_id = _base_file().id
    resp = shop_app.client.get(f"/api/get_game/{file_id}",
                               headers={**_basic("shopper"), "User-Agent": "Sphaira/1.0.6",
                                        "X-Forwarded-For": "192.168.1.50"})
    assert resp.status_code == 200
    resp.close()

    with shop_app.app.app_context():
        [event] = _events()
        assert (event.user, event.client, event.address) == ("shopper", "sphaira", "192.168.1.50")
        assert (event.title_id, event.app_type, event.app_version) == (GAME_ID, "BASE", "0")
        assert event.file_id == file_id and event.filename.endswith("[v0].nsp")
        assert event.size == _base_file().size


def test_an_unidentified_client_is_recorded_as_other(shop_app):
    with shop_app.app.app_context():
        file_id = _base_file().id
    shop_app.client.get(f"/api/get_game/{file_id}", headers=_basic("shopper")).close()
    with shop_app.app.app_context():
        assert [(e.user, e.client) for e in _events()] == [("shopper", "other")]


def test_a_web_download_is_recorded_as_web(admin_client):
    from settings import set_library_management_settings
    with admin_client.application.app_context():
        set_library_management_settings({"web_downloads": {"enabled": True}})
        file_id = _base_file().id
    admin_client.get(f"/api/library/download/{file_id}").close()
    with admin_client.application.app_context():
        assert [(e.user, e.client) for e in _events()] == [("admin", "web")]


def test_a_repeat_within_the_throttle_window_is_recorded_once(shop_app):
    with shop_app.app.app_context():
        file_id = _base_file().id
    for _ in range(3):
        shop_app.client.get(f"/api/get_game/{file_id}", headers=_basic("shopper")).close()
    with shop_app.app.app_context():
        assert len(_events()) == 1


def test_history_outlives_the_file(shop_app):
    with shop_app.app.app_context():
        file_id = _base_file().id
    shop_app.client.get(f"/api/get_game/{file_id}", headers=_basic("shopper")).close()
    with shop_app.app.app_context():
        db.session.delete(db.session.get(Files, file_id))
        db.session.commit()
        db.session.expire_all()
        [event] = _events()
        assert event.file_id is None
        assert event.title_id == GAME_ID and event.filename.endswith("[v0].nsp")


def test_old_entries_are_pruned_on_the_next_download(shop_app):
    with shop_app.app.app_context():
        db.session.add(DownloadEvent(filename="old.nsp", client="web",
                                     downloaded_at=datetime.datetime.utcnow() - datetime.timedelta(days=400)))
        db.session.commit()
        file_id = _base_file().id
    shop_app.client.get(f"/api/get_game/{file_id}", headers=_basic("shopper")).close()
    with shop_app.app.app_context():
        assert [e.filename for e in _events() if e.filename == "old.nsp"] == []
        assert len(_events()) == 1


def test_a_recording_failure_does_not_break_the_download(shop_app, monkeypatch):
    import db as db_mod
    monkeypatch.setattr(db_mod, "DownloadEvent", lambda **kw: (_ for _ in ()).throw(RuntimeError("db locked")))
    with shop_app.app.app_context():
        file_id = _base_file().id
    resp = shop_app.client.get(f"/api/get_game/{file_id}", headers=_basic("shopper"))
    assert resp.status_code == 200
    resp.close()


# --- stats endpoint ------------------------------------------------------------------

def _add(when_utc, title_id=GAME_ID, user="shopper", client="tinfoil", size=100, filename="g.nsp"):
    db.session.add(DownloadEvent(filename=filename, title_id=title_id, user=user, client=client,
                                 size=size, address="10.0.0.2", downloaded_at=when_utc))


def test_stats_aggregate_the_period(admin_client):
    now = datetime.datetime.utcnow()
    with admin_client.application.app_context():
        _add(now - datetime.timedelta(hours=1))
        _add(now - datetime.timedelta(hours=2), user=None, client="sphaira")
        _add(now - datetime.timedelta(days=3), title_id="0100000000020000", user="admin", client="web")
        _add(now - datetime.timedelta(days=60))  # outside the 30-day window
        db.session.commit()

    d = admin_client.get("/api/stats/downloads?days=30").get_json()
    assert d["days"] == 30 and len(d["by_day"]) == 30
    assert d["total"] == 3 and d["all_time"] == 4 and d["total_bytes"] == 300
    assert sum(b["count"] for b in d["by_day"]) == 3
    assert d["top_titles"][0]["title_id"] == GAME_ID and d["top_titles"][0]["count"] == 2
    assert {u["user"]: u["count"] for u in d["by_user"]} == {"shopper": 1, None: 1, "admin": 1}
    assert {c["client"]: c["count"] for c in d["by_client"]} == {"tinfoil": 1, "sphaira": 1, "web": 1}
    # Newest first.
    assert [r["client"] for r in d["recent"]] == ["tinfoil", "sphaira", "web"]


@pytest.mark.parametrize("days, expected", [("0", 1), ("9999", 365), ("abc", 30)])
def test_stats_period_is_clamped(admin_client, days, expected):
    assert admin_client.get(f"/api/stats/downloads?days={days}").get_json()["days"] == expected


def test_clear_history(admin_client):
    with admin_client.application.app_context():
        _add(datetime.datetime.utcnow())
        db.session.commit()
    assert admin_client.delete("/api/stats/downloads").get_json() == {"success": True, "deleted": 1}
    assert admin_client.get("/api/stats/downloads").get_json()["all_time"] == 0


def test_stats_are_admin_only(shop_app):
    shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    assert shop_app.client.get("/api/stats/downloads").status_code == 403
    assert shop_app.client.delete("/api/stats/downloads").status_code == 403


def test_stats_page_has_the_downloads_section(admin_client):
    html = admin_client.get("/admin/stats").get_data(as_text=True)
    assert 'id="downloadsSection"' in html and 'id="downloadChart"' in html


# --- migration -----------------------------------------------------------------------

def test_migration_chain_ends_at_download_events():
    from alembic.script import ScriptDirectory
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "app", "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["a1b2c3d4e5f7"]

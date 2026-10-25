"""download_title_media_task / download_media_task (Settings > Local artworks): fetch
and store a local copy of a title's icon/banner/screenshots, so Title.iconUrl etc (see
gql/resolvers.py's _local_media_urls) can serve /api/media/... instead of hotlinking
Nintendo's CDN - this is now the only artwork pipeline (see tasks.py's comment where
the old, separate titledb/images.py resilience cache used to be)."""
import json
import types
from unittest.mock import patch

import pytest

import db as db_mod
import media
import tasks
import titledb
from app import create_app
from constants import APP_TYPE_BASE, APP_TYPE_DLC
from db import Apps, Libraries, Media, Titles, db, get_title_media, init_db, upsert_media


class FakeResponse:
    def __init__(self, body=b"BYTES", status=200):
        self._body = body
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))

    @property
    def content(self):
        return self._body


def _jpeg_bytes(size=(300, 300)):
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', size, color=(1, 2, 3)).save(buffer, format='JPEG')
    return buffer.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    titledb_dir = tmp_path / "titledb"
    titledb_dir.mkdir()
    monkeypatch.setattr(db_mod, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(db_mod, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "TITLES_DB_FILE", str(config / "titles.db"))
    monkeypatch.setattr(titledb.store, "DB_FILE", str(config / "ownfoil.db"))
    monkeypatch.setattr(media, "MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setattr(tasks, "local_media_enabled", lambda: True)

    app = create_app(f"sqlite:///{config / 'ownfoil.db'}")
    init_db(app)

    title_id = "0100000000010000"
    region_file = titledb_dir / "titles.US.en.json"
    region_file.write_text(json.dumps({
        title_id: {
            "id": title_id, "name": "Game",
            "bannerUrl": "https://example.com/banner.jpg",
            "iconUrl": "https://example.com/icon.jpg",
            "screenshots": ["https://example.com/s0.jpg", "https://example.com/s1.jpg"],
        },
    }))
    (titledb_dir / "cnmts.json").write_text("{}")
    (titledb_dir / "versions.json").write_text("{}")
    with app.app_context():
        titledb.store.import_from_json(str(region_file), "US.en")
        lib_row = Libraries(path=str(tmp_path / "games"))
        db.session.add(lib_row)
        db.session.flush()
        title_row = Titles(title_id=title_id, have_base=True)
        db.session.add(title_row)
        db.session.flush()
        app_row = Apps(title_id=title_row.id, app_id=title_id, app_version="0",
                       app_type=APP_TYPE_BASE, owned=True)
        db.session.add(app_row)
        db.session.commit()

    yield types.SimpleNamespace(app=app, title_id=title_id)


def test_downloads_icon_banner_and_every_screenshot(env, monkeypatch):
    monkeypatch.setattr(media, "fetch", lambda url: _jpeg_bytes())
    with env.app.app_context():
        tasks.download_title_media_task(title_id=env.title_id)

        rows = get_title_media([env.title_id])
        assert set(rows) == {
            (env.title_id, media.ICON, 0),
            (env.title_id, media.BANNER, 0),
            (env.title_id, media.SCREENSHOT, 0),
            (env.title_id, media.SCREENSHOT, 1),
        }
        for row in rows.values():
            assert media.have(row.kind, row.filename)


def test_does_nothing_when_local_media_is_disabled(env, monkeypatch):
    monkeypatch.setattr(tasks, "local_media_enabled", lambda: False)
    monkeypatch.setattr(media, "fetch", lambda url: _jpeg_bytes())
    with env.app.app_context():
        tasks.download_title_media_task(title_id=env.title_id)
        assert get_title_media([env.title_id]) == {}


def test_a_dead_url_is_skipped_without_failing_the_other_slots(env, monkeypatch):
    import requests

    def flaky_fetch(url):
        if "banner" in url:
            raise requests.ConnectionError("offline")
        return _jpeg_bytes()

    monkeypatch.setattr(media, "fetch", flaky_fetch)
    monkeypatch.setattr(tasks, "enqueue_task", lambda *a, **k: None)  # no retry scheduling needed here
    with env.app.app_context():
        tasks.download_title_media_task(title_id=env.title_id)  # must not raise

        rows = get_title_media([env.title_id])
        assert (env.title_id, media.BANNER, 0) not in rows
        assert (env.title_id, media.ICON, 0) in rows


def test_a_failed_slot_schedules_a_retry_up_to_the_limit(env, monkeypatch):
    import requests
    monkeypatch.setattr(media, "fetch", lambda url: (_ for _ in ()).throw(requests.ConnectionError("offline")))
    scheduled = []
    monkeypatch.setattr(tasks, "enqueue_task", lambda name, data, **kw: scheduled.append((name, data)))

    with env.app.app_context():
        tasks.download_title_media_task(title_id=env.title_id, attempt=0)
        assert scheduled == [("download_title_media", {"title_id": env.title_id, "attempt": 1})]

        scheduled.clear()
        tasks.download_title_media_task(title_id=env.title_id, attempt=tasks.MEDIA_RETRY_LIMIT)
        assert scheduled == []  # retry budget exhausted - leave it hotlinked until the next titledb refresh


def test_a_second_run_does_not_redownload_an_unchanged_slot(env, monkeypatch):
    calls = []

    def counting_fetch(url):
        calls.append(url)
        return _jpeg_bytes()

    monkeypatch.setattr(media, "fetch", counting_fetch)
    with env.app.app_context():
        tasks.download_title_media_task(title_id=env.title_id)
        assert len(calls) == 4  # icon + banner + 2 screenshots
        tasks.download_title_media_task(title_id=env.title_id)
        assert len(calls) == 4  # nothing new to fetch


def test_a_slot_already_pointing_locally_is_left_alone(env, monkeypatch):
    """_build_title's own substitution never writes titledb hotlinks back into the
    dump, but this guards the task against ever being handed one of its own
    /api/media/... URLs as the "source" to fetch - it must recognize and skip it."""
    with env.app.app_context():
        upsert_media(env.title_id, media.ICON, 0, source="local", source_url=None,
                     filename="already-local.jpg", size=(10, 10))
        monkeypatch.setattr(tasks.titles_lib, "get_title_record", lambda tid: {
            "iconUrl": media.url_for(tid, media.ICON, 0, media.CLIENT, "already-local.jpg"),
            "bannerUrl": None, "screenshots": [], "source": "titledb",
        })
        monkeypatch.setattr(media, "fetch", lambda url: pytest.fail("should never fetch a local URL"))
        tasks.download_title_media_task(title_id=env.title_id)

        rows = get_title_media([env.title_id])
        assert rows[(env.title_id, media.ICON, 0)].filename == "already-local.jpg"


def test_removes_a_slot_no_longer_present_eg_a_shortened_screenshot_list(env, monkeypatch):
    monkeypatch.setattr(media, "fetch", lambda url: _jpeg_bytes())
    with env.app.app_context():
        tasks.download_title_media_task(title_id=env.title_id)
        assert (env.title_id, media.SCREENSHOT, 1) in get_title_media([env.title_id])

        monkeypatch.setattr(tasks.titles_lib, "get_title_record", lambda tid: {
            "iconUrl": "https://example.com/icon.jpg", "bannerUrl": "https://example.com/banner.jpg",
            "screenshots": ["https://example.com/s0.jpg"], "source": "titledb",
        })
        tasks.download_title_media_task(title_id=env.title_id)
        rows = get_title_media([env.title_id])
        assert (env.title_id, media.SCREENSHOT, 1) not in rows
        assert (env.title_id, media.SCREENSHOT, 0) in rows


def test_an_unknown_title_record_is_left_untouched_rather_than_wiped(env, monkeypatch):
    """A None record means titles.db can't currently say, not that the title has no
    artwork - a rebuild-in-progress window must not read as licence to delete rows."""
    with env.app.app_context():
        upsert_media(env.title_id, media.ICON, 0, source="titledb", source_url="https://x/icon.jpg",
                     filename="kept.jpg", size=(10, 10))
        monkeypatch.setattr(tasks.titles_lib, "get_title_record", lambda tid: None)
        tasks.download_title_media_task(title_id=env.title_id)

        rows = get_title_media([env.title_id])
        assert (env.title_id, media.ICON, 0) in rows


def test_download_media_task_enqueues_a_child_per_title_and_its_dlc(env, monkeypatch):
    enqueued = []
    monkeypatch.setattr(tasks, "enqueue_or_child", lambda name, data: enqueued.append((name, data)) or 1)
    monkeypatch.setattr(tasks, "set_waiting_for_children", lambda: None)
    monkeypatch.setattr(tasks.titles_lib, "get_all_existing_dlc", lambda tid: ["0100000000010800"])

    with env.app.app_context():
        tasks.download_media_task()

    assert enqueued == [
        ("download_title_media", {"title_id": env.title_id}),
        ("download_title_media", {"title_id": "0100000000010800"}),
    ]


def test_download_media_task_does_nothing_when_local_media_is_disabled(env, monkeypatch):
    monkeypatch.setattr(tasks, "local_media_enabled", lambda: False)
    enqueued = []
    monkeypatch.setattr(tasks, "enqueue_or_child", lambda name, data: enqueued.append((name, data)) or 1)

    with env.app.app_context():
        tasks.download_media_task()

    assert enqueued == []


# --- Scanning a title also checks its artwork, not just on the titledb schedule ---
#
# add_missing_apps_for_title_task is the only chain a newly identified title goes
# down (see its own docstring), so that's where a freshly-scanned game's artwork
# download has to be enqueued from - waiting for the next titledb refresh would leave
# a brand new title's card blank (or hotlinked) until then.

def test_scanning_a_title_also_enqueues_its_artwork_download(env, monkeypatch):
    monkeypatch.setattr(tasks, "add_missing_apps_for_title", lambda tid: None)
    enqueued = []
    monkeypatch.setattr(tasks, "enqueue_or_child", lambda name, data: enqueued.append((name, data)) or 1)
    monkeypatch.setattr(tasks, "set_waiting_for_children", lambda: None)
    monkeypatch.setattr(tasks.titles_lib, "get_all_existing_dlc", lambda tid: [])

    with env.app.app_context():
        tasks.add_missing_apps_for_title_task(title_id=env.title_id)

    assert ("download_title_media", {"title_id": env.title_id}) in enqueued
    assert ("update_titles_for_title", {"title_id": env.title_id}) in enqueued


def test_scanning_a_title_skips_the_artwork_download_when_local_media_is_disabled(env, monkeypatch):
    monkeypatch.setattr(tasks, "local_media_enabled", lambda: False)
    monkeypatch.setattr(tasks, "add_missing_apps_for_title", lambda tid: None)
    enqueued = []
    monkeypatch.setattr(tasks, "enqueue_or_child", lambda name, data: enqueued.append((name, data)) or 1)
    monkeypatch.setattr(tasks, "set_waiting_for_children", lambda: None)

    with env.app.app_context():
        tasks.add_missing_apps_for_title_task(title_id=env.title_id)

    assert all(name != "download_title_media" for name, _data in enqueued)
    assert ("update_titles_for_title", {"title_id": env.title_id}) in enqueued

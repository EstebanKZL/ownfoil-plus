"""Etapa 3: the admin dashboard (/admin) and the installable app (manifest, service
worker, offline page)."""
import datetime
import json
import os

import fixture
import pytest

from db import DownloadEvent, Files, Task, db


@pytest.fixture
def admin_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code == 302
    return shop_app.client


# --- PWA -----------------------------------------------------------------------------

def test_manifest_is_installable_and_uses_the_shop_name(shop_app):
    from settings import set_shop_settings
    set_shop_settings({"name": "Casa de Esteban"})
    resp = shop_app.client.get("/manifest.webmanifest")
    assert resp.status_code == 200 and resp.mimetype == "application/manifest+json"
    manifest = json.loads(resp.get_data(as_text=True))
    assert manifest["name"] == "Casa de Esteban"
    assert len(manifest["short_name"]) <= 12
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/"
    sizes = {i["sizes"] for i in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert {"any", "maskable"} <= {i["purpose"] for i in manifest["icons"]}


def test_manifest_icons_actually_exist(shop_app):
    manifest = json.loads(shop_app.client.get("/manifest.webmanifest").get_data(as_text=True))
    for icon in manifest["icons"]:
        resp = shop_app.client.get(icon["src"])
        assert resp.status_code == 200, icon["src"]
        resp.close()


def test_service_worker_is_served_from_the_root(shop_app):
    resp = shop_app.client.get("/sw.js")
    assert resp.status_code == 200
    assert resp.mimetype == "application/javascript"
    assert resp.headers["Service-Worker-Allowed"] == "/"
    assert "no-cache" in resp.headers["Cache-Control"]
    js = resp.get_data(as_text=True)
    assert "const CACHE = 'ownfoil-plus-" in js
    precache = json.loads(js.split("const PRECACHE = ", 1)[1].split(";\n", 1)[0])
    assert "/offline" in precache
    for url in precache:
        r = shop_app.client.get(url)
        assert r.status_code == 200, url
        r.close()


def test_service_worker_never_touches_the_api_or_downloads(shop_app):
    js = shop_app.client.get("/sw.js").get_data(as_text=True)
    # Only static assets and page navigations are handled; everything else falls through.
    assert "request.method !== 'GET'" in js and "has('range')" in js
    assert "url.pathname.startsWith('/static/')" in js and "request.mode === 'navigate'" in js


def test_static_assets_come_from_the_network_first(shop_app):
    js = shop_app.client.get("/sw.js").get_data(as_text=True)
    # Fresh pages must never wear an older version's CSS or JS: the network answers
    # and the cache only when the server can't be reached (mixed versions used to
    # half-break the layout "for a while" after every update).
    static_block = js.split("url.pathname.startsWith('/static/')", 1)[1].split("return;", 1)[0]
    assert static_block.index("fetch(request)") < static_block.index("cache.match(request)")


def test_pwa_files_need_no_login_on_a_private_shop(shop_app):
    for url in ("/manifest.webmanifest", "/sw.js", "/offline"):
        resp = shop_app.client.get(url)
        assert resp.status_code == 200, url
        resp.close()


def test_pages_link_the_manifest_and_register_the_worker(admin_client):
    html = admin_client.get("/admin").get_data(as_text=True)
    assert '<link rel="manifest" href="/manifest.webmanifest"' in html
    assert '/static/js/pwa.js' in html
    assert 'name="theme-color"' in html
    js = admin_client.get('/static/js/pwa.js').get_data(as_text=True)
    assert "navigator.serviceWorker.register('/sw.js')" in js and 'window.isSecureContext' in js


def test_old_broken_manifest_is_gone():
    root = os.path.join(os.path.dirname(__file__), "..", "app", "static", "favicon")
    assert not os.path.exists(os.path.join(root, "site.webmanifest"))


# --- dashboard -----------------------------------------------------------------------

def test_admin_lands_on_the_dashboard(admin_client):
    resp = admin_client.get("/admin")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="dashAlerts"' in html and 'id="dashTiles"' in html
    assert 'href="/admin"' in html  # sidebar entry


def test_dashboard_reports_library_health(admin_client):
    with admin_client.application.app_context():
        first = Files.query.filter_by(extension="nsp").first()
        first.signature_valid, first.hash_valid, first.hash_modified = True, False, False
        db.session.add(Task(task_name="scan_libraries", status="failed", input_json="{}", input_hash="x"))
        db.session.add(DownloadEvent(filename="g.nsp", client="web", user="admin",
                                     downloaded_at=datetime.datetime.utcnow()))
        db.session.commit()
        files_count = Files.query.count()

    d = admin_client.get("/api/dashboard").get_json()
    lib = d["library"]
    assert lib["files"] == files_count
    assert lib["unidentified"] == 1          # the fixture's Mystery File
    assert lib["corrupt"] == 1
    assert lib["owned_titles"] == 1
    assert d["tasks"]["failed"] == 1
    assert d["downloads_week"] == 1
    assert d["recent_downloads"][0]["user"] == "admin"
    assert d["keys_valid"] is False
    assert len(d["recent_files"]) <= 30 and all(f["filename"] for f in d["recent_files"])


def test_dashboard_storage_marks_an_unreachable_library(admin_client, tmp_path):
    from settings import settings_transaction
    with settings_transaction() as settings:
        settings["library"]["paths"] = [str(tmp_path), str(tmp_path / "missing")]
    storage = admin_client.get("/api/dashboard").get_json()["storage"]
    assert storage[0]["online"] and storage[0]["free"] > 0
    assert storage[1] == {"path": str(tmp_path / "missing"), "online": False}


def test_dashboard_counts_duplicates(admin_client):
    from db import Apps, Libraries
    with admin_client.application.app_context():
        app_row = Apps.query.filter_by(app_type="BASE").first()
        library = Libraries.query.first()
        dup = Files(library_id=library.id, filepath=os.path.join(library.path, "copy.nsp"),
                    folder=library.path, filename="copy.nsp", extension="nsp", size=1, identified=True)
        db.session.add(dup)
        app_row.files.append(dup)
        db.session.commit()
    assert admin_client.get("/api/dashboard").get_json()["library"]["duplicates"] == 1


def test_dashboard_is_admin_only(shop_app):
    shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    assert shop_app.client.get("/api/dashboard").status_code == 403
    assert shop_app.client.get("/admin").status_code == 403

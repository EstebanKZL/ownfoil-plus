"""Stage 1 design system: the flat top bar (admin pages one click away, with counters)
and the phone bottom bar."""
import os
import re

import fixture
import pytest

from db import Files, Libraries, db

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _login(client, user):
    resp = client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    assert resp.status_code == 302


@pytest.fixture
def admin_client(shop_app):
    _login(shop_app.client, "admin")
    return shop_app.client


@pytest.fixture
def shopper_client(shop_app):
    _login(shop_app.client, "shopper")
    return shop_app.client


@pytest.fixture(autouse=True)
def _fresh_counts():
    import nav_counts
    nav_counts.clear_cache()
    yield
    nav_counts.clear_cache()


# --- top bar -------------------------------------------------------------------------

def test_admin_sees_flat_items_linking_existing_routes(admin_client):
    html = admin_client.get("/admin").get_data(as_text=True)
    for href in ('href="/admin/files"', 'href="/admin/tasks"', 'href="/admin/stats"',
                 'href="/admin/settings"', 'href="/admin/services"', 'href="/setup"'):
        assert href in html, href
    assert "settings-sidebar" not in html


def test_shopper_sees_no_admin_items_or_counts(shopper_client):
    html = shopper_client.get("/").get_data(as_text=True)
    assert 'href="/admin/files"' not in html and "navCountTasks" not in html
    assert 'href="/setup"' in html


def test_counts_match_the_library_and_hide_at_zero(shop_app, admin_client):
    import nav_counts
    with shop_app.app.app_context():
        unidentified = Files.query.filter(Files.identified.is_(False)).count()
        assert nav_counts.get_nav_counts() == {"unidentified": unidentified, "running_tasks": 0}
    html = admin_client.get("/admin").get_data(as_text=True)
    assert re.search(r'id="navCountTasks"[^>]*\bhidden\b', html)


def test_unidentified_file_shows_in_the_files_badge(shop_app, admin_client):
    import nav_counts
    with shop_app.app.app_context():
        before = nav_counts.get_nav_counts()["unidentified"]
        db.session.add(Files(library_id=Libraries.query.first().id,
                             filepath=os.path.join(str(shop_app.library_root), "mystery.nsp"),
                             filename="mystery.nsp", folder=str(shop_app.library_root),
                             identified=False, size=1))
        db.session.commit()
        nav_counts.clear_cache()
        assert nav_counts.get_nav_counts()["unidentified"] == before + 1
    html = admin_client.get("/admin").get_data(as_text=True)
    badge = re.search(r'id="navCountFiles"[^>]*>(\d+)<', html)
    assert badge and int(badge.group(1)) == before + 1


def test_first_run_nav_renders(shop_app, monkeypatch):
    # No admin account yet: the nav treats the visitor as admin and must not crash.
    import app as app_mod
    import auth
    monkeypatch.setattr(app_mod, "admin_account_created", lambda: 0)
    monkeypatch.setattr(auth, "admin_account_created", lambda: 0)
    resp = shop_app.app.test_client().get("/")
    assert resp.status_code == 200
    assert 'href="/admin/tasks"' in resp.get_data(as_text=True)


def test_active_item_is_marked(admin_client):
    html = admin_client.get("/admin/tasks").get_data(as_text=True)
    assert re.search(r'data-nav="tasks"[^>]*aria-current="page"', html)


def test_tasks_page_keeps_the_nav_count_live():
    html = open(os.path.join(ROOT, "app", "templates", "tasks.html"), encoding="utf-8").read()
    assert "navCountTasks" in html

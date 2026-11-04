"""Phase 4, part C: a profile picture in My account - one of the gallery's avatars or an
uploaded image (cropped square and shrunk on the server) - shown in the top bar and in
the users table (app/avatars.py)."""
import io
import os
import re

import fixture
import pytest
from PIL import Image

import avatars
from db import User

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GALLERY = os.path.join(ROOT, "app", "static", "img", "avatars")


def _login(shop_app, user="shopper"):
    resp = shop_app.client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    assert resp.status_code == 302
    return shop_app.client


@pytest.fixture
def avatar_dir(tmp_path, monkeypatch):
    folder = tmp_path / "avatars"
    monkeypatch.setattr(avatars, "AVATARS_DIR", str(folder))
    return folder


def _png(width=600, height=300, color=(200, 40, 40)):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


def _upload(client, data, name="me.png"):
    return client.post("/api/account/avatar", data={"file": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


def _stored(shop_app, user="shopper"):
    with shop_app.app.app_context():
        return User.query.filter_by(user=user).one().avatar


# --- the gallery --------------------------------------------------------------------------

def test_the_gallery_has_a_dozen_local_avatars():
    files = sorted(f for f in os.listdir(GALLERY) if f.endswith(".svg"))
    assert len(files) >= 12 and files == [f"{n:02d}.svg" for n in range(1, len(files) + 1)]
    assert avatars.GALLERY == tuple(f[:-4] for f in files)
    for name in files:
        svg = open(os.path.join(GALLERY, name), encoding="utf-8").read()
        assert svg.startswith("<svg") and 'viewBox="0 0 96 96"' in svg
        # Drawn here, nothing fetched: the UI works offline.
        assert "http://" not in svg.replace("http://www.w3.org/2000/svg", "") and "https://" not in svg
        assert "<script" not in svg


def test_choosing_a_gallery_avatar(shop_app, avatar_dir):
    client = _login(shop_app)
    resp = client.post("/api/account/avatar", json={"gallery": "05"})
    assert resp.status_code == 200 and resp.get_json()["url"] == "/static/img/avatars/05.svg"
    assert _stored(shop_app) == "g:05"
    assert client.post("/api/account/avatar", json={"gallery": "../x"}).status_code == 400
    assert client.post("/api/account/avatar", json={"gallery": "99"}).status_code == 400


# --- uploading one's own --------------------------------------------------------------------

def test_an_upload_is_cropped_square_and_shrunk(shop_app, avatar_dir):
    client = _login(shop_app)
    resp = _upload(client, _png(1200, 600))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    url = resp.get_json()["url"]
    stored = _stored(shop_app)
    assert stored.startswith("u:") and url == "/api/avatars/" + stored[2:]
    served = client.get(url)
    assert served.status_code == 200 and served.mimetype == "image/jpeg"
    with Image.open(io.BytesIO(served.data)) as image:
        assert image.size == (avatars.SIZE, avatars.SIZE)


def test_a_new_picture_replaces_the_old_file(shop_app, avatar_dir):
    client = _login(shop_app)
    first = _upload(client, _png()).get_json()["url"].rsplit("/", 1)[1]
    _upload(client, _png(color=(0, 0, 200)))
    assert not (avatar_dir / first).exists() and len(list(avatar_dir.iterdir())) == 1
    client.post("/api/account/avatar", json={"gallery": None})
    assert _stored(shop_app) is None and not list(avatar_dir.iterdir())


@pytest.mark.parametrize("data,status", [(b"not an image at all", 400), (b"<svg onload=x></svg>", 400)])
def test_only_real_images_are_taken(shop_app, avatar_dir, data, status):
    client = _login(shop_app)
    assert _upload(client, data, "x.png").status_code == status
    assert _stored(shop_app) is None


def test_too_large_an_upload_is_refused(shop_app, avatar_dir, monkeypatch):
    monkeypatch.setattr(avatars, "MAX_UPLOAD", 1000)
    client = _login(shop_app)
    assert _upload(client, _png(800, 800)).status_code == 413


def test_huge_dimensions_are_refused(shop_app, avatar_dir, monkeypatch):
    monkeypatch.setattr(avatars, "MAX_PIXELS", 100 * 100)
    client = _login(shop_app)
    assert _upload(client, _png(400, 400)).status_code == 400


def test_uploaded_pictures_are_served_by_their_safe_name_only(shop_app, avatar_dir):
    client = _login(shop_app)
    # A name with slashes never reaches the route (the app's catch-all sends it home).
    climb = client.get("/api/avatars/..%2F..%2Fsettings.yaml")
    assert climb.status_code in (302, 404) and b"shop" not in climb.data
    assert client.get("/api/avatars/nothing.jpg").status_code == 404
    client.get("/logout")
    url = _upload(_login(shop_app), _png()).get_json()["url"]
    shop_app.client.get("/logout")
    assert shop_app.client.get(url).status_code in (302, 401)      # signed-in users only


# --- where it shows ---------------------------------------------------------------------------

def test_the_top_bar_shows_the_picture(shop_app, avatar_dir):
    client = _login(shop_app)
    html = client.get("/account").get_data(as_text=True)
    assert 'class="nav-avatar' not in html
    client.post("/api/account/avatar", json={"gallery": "03"})
    html = client.get("/account").get_data(as_text=True)
    assert re.search(r'<img class="nav-avatar[^"]*" src="/static/img/avatars/03.svg"', html)


def test_the_users_table_gets_each_picture(shop_app, avatar_dir):
    client = _login(shop_app)
    client.post("/api/account/avatar", json={"gallery": "07"})
    client.get("/logout")
    users = _login(shop_app, "admin").get("/api/users").get_json()
    shopper = next(u for u in users if u["user"] == "shopper")
    assert shopper["avatar_url"] == "/static/img/avatars/07.svg"
    assert next(u for u in users if u["user"] == "admin")["avatar_url"] is None
    js = open(os.path.join(ROOT, "app", "static", "js", "settings.js"), encoding="utf-8").read()
    assert "user['avatar_url']" in js


def test_my_account_has_the_picture_picker(shop_app, avatar_dir):
    html = _login(shop_app).get("/account").get_data(as_text=True)
    assert 'id="accountAvatar"' in html and 'id="avatarFile"' in html and 'id="avatarRemove"' in html
    assert len(re.findall(r'class="avatar-choice', html)) == len(avatars.GALLERY)
    assert len(re.findall(r"<script>(.*?)</script>", html, re.S)) == 1
    for name in ("avatarSaved:", "avatarFailed:", "avatarTooLarge:"):
        assert name in html, name

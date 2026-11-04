"""The save vault: JKSV uploads save backups over WebDAV to /dav/, with its own user and
password, off until an admin turns it on (app/vault.py)."""
import base64
import io
import os
import re
import struct
import time
import zipfile

import fixture
import pytest

import vault

GAME = "01007EF00011E000"
PASSWORD = "jksv-secret-1"


def _meta_zip(title_id=GAME, stamp=1782864000, extra_entries=0):
    """A backup as JKSV makes it: the save files plus .nx_save_meta.bin."""
    meta = struct.pack("<IB", 0x56534B4A, 1) + struct.pack("<Q", int(title_id, 16))
    meta += b"\0" * 16 + b"\0" * 8 + b"\0\0" + b"\0\0" + b"\0" * 8 + struct.pack("<Q", stamp)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(".nx_save_meta.bin", meta)
        zf.writestr("save/progress.sav", b"data")
        for n in range(extra_entries):
            zf.writestr(f"x/{n}", b"")
    return buf.getvalue()


def _auth(user="jksv", password=PASSWORD):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _login(shop_app, user):
    resp = shop_app.client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    assert resp.status_code == 302
    return shop_app.client


@pytest.fixture
def saves_dir(tmp_path, monkeypatch):
    root = tmp_path / "saves"
    monkeypatch.setattr(vault, "SAVES_DIR", str(root))
    monkeypatch.setattr(vault, "_free_bytes", lambda path: 100 << 30)
    vault.clear_auth_cache()
    return root


@pytest.fixture
def on(shop_app, saves_dir):
    """The vault turned on from Settings by the admin."""
    admin = _login(shop_app, "admin")
    resp = admin.post("/api/settings/vault", json={"enabled": True, "username": "jksv",
                                                   "password": PASSWORD, "keep": 0})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    admin.get("/logout")
    return shop_app.client


def _dav(client, method, path, data=None, headers=None):
    return client.open(path, method=method, data=data, headers={**_auth(), **(headers or {})})


# --- off, and who gets in ------------------------------------------------------------------

def test_the_vault_is_off_by_default(shop_app, saves_dir):
    assert shop_app.client.open("/dav/", method="PROPFIND", headers=_auth()).status_code == 404


def test_it_asks_for_its_own_user_and_password(on):
    resp = on.open("/dav/", method="PROPFIND")
    assert resp.status_code == 401 and "Basic" in resp.headers["WWW-Authenticate"]
    assert on.open("/dav/", method="PROPFIND", headers=_auth(password="wrong-password")).status_code == 401
    # The web interface's accounts don't open it.
    assert on.open("/dav/", method="PROPFIND", headers=_auth("admin", fixture.PASSWORDS["admin"])).status_code == 401


def test_repeated_wrong_passwords_are_locked_out(on):
    for _ in range(5):
        on.open("/dav/", method="PROPFIND", headers=_auth(password="nope-nope-nope"))
    assert on.open("/dav/", method="PROPFIND", headers=_auth()).status_code == 429


# --- what JKSV does --------------------------------------------------------------------------

def test_jksv_lists_creates_a_folder_uploads_and_reads_back(on, saves_dir):
    assert _dav(on, "OPTIONS", "/dav/").headers.get("DAV")
    listing = _dav(on, "PROPFIND", "/dav/", headers={"Depth": "1"})
    assert listing.status_code == 207 and "/dav/JKSV/" in listing.get_data(as_text=True)
    assert _dav(on, "MKCOL", "/dav/JKSV/Zelda%20BOTW").status_code == 201
    body = _meta_zip()
    assert _dav(on, "PUT", "/dav/JKSV/Zelda%20BOTW/2026-01-01.zip", data=body).status_code == 201
    assert (saves_dir / "JKSV" / "Zelda BOTW" / "2026-01-01.zip").read_bytes() == body
    folder = _dav(on, "PROPFIND", "/dav/JKSV/Zelda%20BOTW/", headers={"Depth": "1"}).get_data(as_text=True)
    assert "2026-01-01.zip" in folder and f"<D:getcontentlength>{len(body)}</D:getcontentlength>" in folder
    assert _dav(on, "GET", "/dav/JKSV/Zelda%20BOTW/2026-01-01.zip").data == body
    moved = _dav(on, "MOVE", "/dav/JKSV/Zelda%20BOTW/2026-01-01.zip",
                 headers={"Destination": "http://localhost/dav/JKSV/Zelda%20BOTW/renamed.zip"})
    assert moved.status_code in (201, 204) and (saves_dir / "JKSV" / "Zelda BOTW" / "renamed.zip").exists()
    assert _dav(on, "DELETE", "/dav/JKSV/Zelda%20BOTW/renamed.zip").status_code == 204


# --- even with the right password ----------------------------------------------------------

@pytest.mark.parametrize("method,path,headers,data", [
    ("PUT", "/dav/JKSV/game/notes.txt", {}, b"x"),                      # only ZIP backups
    ("PUT", "/dav/elsewhere.zip", {}, b"x"),                           # outside the JKSV folder
    ("PUT", "/dav/JKSV/../../escape.zip", {}, b"x"),                   # no climbing out
    ("PUT", "/dav/JKSV/game/a:stream.zip", {}, b"x"),                  # no Windows streams
    ("MKCOL", "/dav/other", {}, None),
    ("DELETE", "/dav/JKSV/game", {}, None),                            # never a whole folder
    ("PROPFIND", "/dav/", {"Depth": "infinity"}, None),               # no listing of everything
    ("MOVE", "/dav/JKSV/game/a.zip", {"Destination": "http://localhost/dav/out.zip"}, None),
    ("PATCH", "/dav/JKSV/game/a.zip", {}, b"x"),                       # methods JKSV doesn't use
])
def test_the_vault_refuses_anything_but_backups_in_the_jksv_folder(on, saves_dir, method, path, headers, data):
    (saves_dir / "JKSV" / "game").mkdir(parents=True)
    (saves_dir / "JKSV" / "game" / "a.zip").write_bytes(_meta_zip())
    assert _dav(on, method, path, data=data, headers=headers).status_code in (400, 403, 405)
    assert not (saves_dir.parent / "escape.zip").exists()


def test_an_upload_needs_room_left_on_the_disk(on, saves_dir, monkeypatch):
    _dav(on, "MKCOL", "/dav/JKSV/game")
    monkeypatch.setattr(vault, "_free_bytes", lambda path: 100 << 20)     # 100 MB free
    assert _dav(on, "PUT", "/dav/JKSV/game/b.zip", data=_meta_zip()).status_code == 507
    assert not (saves_dir / "JKSV" / "game" / "b.zip").exists()


def test_a_zip_with_absurdly_many_entries_is_refused(on, saves_dir, monkeypatch):
    monkeypatch.setattr(vault, "MAX_ZIP_ENTRIES", 10)
    _dav(on, "MKCOL", "/dav/JKSV/game")
    assert _dav(on, "PUT", "/dav/JKSV/game/bomb.zip", data=_meta_zip(extra_entries=20)).status_code == 422
    assert not (saves_dir / "JKSV" / "game" / "bomb.zip").exists()


def test_old_backups_beyond_the_kept_number_are_removed(shop_app, saves_dir):
    admin = _login(shop_app, "admin")
    admin.post("/api/settings/vault", json={"enabled": True, "username": "jksv", "password": PASSWORD, "keep": 5})
    admin.get("/logout")
    client = shop_app.client
    _dav(client, "MKCOL", "/dav/JKSV/game")
    past = time.time() - 1000
    for n in range(7):
        _dav(client, "PUT", f"/dav/JKSV/game/{n}.zip", data=_meta_zip())
        # Older uploads, older files: the newest is always the one just uploaded.
        os.utime(saves_dir / "JKSV" / "game" / f"{n}.zip", (past + n, past + n))
    left = sorted(p.name for p in (saves_dir / "JKSV" / "game").iterdir())
    assert left == ["2.zip", "3.zip", "4.zip", "5.zip", "6.zip"]


def test_a_new_backup_is_notified(on, monkeypatch):
    sent = []
    import notifications
    monkeypatch.setattr(notifications, "notify", lambda event, item: sent.append((event, item)))
    _dav(on, "MKCOL", "/dav/JKSV/Zelda")
    _dav(on, "PUT", "/dav/JKSV/Zelda/b.zip", data=_meta_zip())
    assert sent and sent[0][0] == "save_backup" and "Zelda" in sent[0][1]
    assert "save_backup" in notifications.EVENTS


# --- reading JKSV's backups ------------------------------------------------------------------

def test_a_backup_tells_its_game_and_time(tmp_path):
    path = tmp_path / "b.zip"
    path.write_bytes(_meta_zip(GAME, stamp=1782864000))   # 1 July 2026
    title_id, when = vault.read_meta(str(path))
    assert title_id == GAME and when.year == 2026


def test_a_file_that_is_not_a_jksv_backup_tells_nothing(tmp_path):
    path = tmp_path / "b.zip"
    path.write_bytes(b"not a zip")
    assert vault.read_meta(str(path)) == (None, None)


# --- settings ----------------------------------------------------------------------------------

def test_vault_settings_need_a_long_password_to_turn_on(shop_app, saves_dir):
    admin = _login(shop_app, "admin")
    assert admin.post("/api/settings/vault", json={"enabled": True, "username": "jksv",
                                                   "password": "short", "keep": 0}).status_code == 400
    assert admin.post("/api/settings/vault", json={"enabled": True, "username": "jksv",
                                                   "password": "", "keep": 0}).status_code == 400
    assert admin.post("/api/settings/vault", json={"enabled": False, "username": "jk sv",
                                                   "password": "", "keep": 0}).status_code == 400
    assert admin.post("/api/settings/vault", json={"enabled": False, "username": "jksv",
                                                   "password": "", "keep": 3}).status_code == 400


def test_the_password_is_kept_hashed_and_never_sent_back(shop_app, saves_dir):
    admin = _login(shop_app, "admin")
    admin.post("/api/settings/vault", json={"enabled": True, "username": "jksv", "password": PASSWORD, "keep": 10})
    from settings import get_settings
    stored = get_settings()["vault"]
    assert stored["password_hash"] and PASSWORD not in stored["password_hash"]
    sent = admin.get("/api/settings").get_json()["vault"]
    assert "password_hash" not in sent and sent["password_set"] is True and sent["keep"] == 10
    # Saving again without a password keeps the one there was.
    admin.post("/api/settings/vault", json={"enabled": True, "username": "jksv", "password": "", "keep": 5})
    assert get_settings()["vault"]["password_hash"] == stored["password_hash"]


def test_only_admins_change_the_vault(shop_app, saves_dir):
    client = _login(shop_app, "shopper")
    assert client.post("/api/settings/vault", json={"enabled": True}).status_code in (302, 401, 403)


# --- the Saves page ----------------------------------------------------------------------------

def _backup_user(shop_app):
    from auth import create_or_update_user
    with shop_app.app.app_context():
        create_or_update_user("keeper", "keeperpass1", shop_access=True, backup_access=True)
    resp = shop_app.client.post("/login", data={"user": "keeper", "password": "keeperpass1"})
    assert resp.status_code == 302
    return shop_app.client


def test_the_saves_page_and_api_list_backups_by_game(shop_app, on, saves_dir):
    _dav(on, "MKCOL", "/dav/JKSV/Zelda")
    _dav(on, "PUT", "/dav/JKSV/Zelda/b.zip", data=_meta_zip())
    client = _backup_user(shop_app)
    html = client.get("/saves").get_data(as_text=True)
    assert len(re.findall(r"<script>(.*?)</script>", html, re.S)) == 1 and "/static/js/saves.js" in html
    data = client.get("/api/saves").get_json()
    game = data["games"][0]
    assert data["enabled"] is True and game["title_id"] == GAME and game["folder"] == "Zelda"
    assert game["backups"][0]["path"] == "Zelda/b.zip" and game["backups"][0]["size"] > 0
    assert client.get("/api/saves/download", query_string={"path": "Zelda/b.zip"}).status_code == 200
    assert client.get("/api/saves/download", query_string={"path": "../../etc/passwd"}).status_code == 404
    assert client.get(f"/api/saves/of/{GAME}").get_json()["count"] == 1
    assert client.delete("/api/saves", query_string={"path": "Zelda/b.zip"}).status_code == 200
    assert not (saves_dir / "JKSV" / "Zelda" / "b.zip").exists()


def test_users_without_backup_access_dont_see_saves(shop_app, on):
    client = _login(shop_app, "shopper")
    assert client.get("/saves").status_code == 403
    assert client.get("/api/saves").status_code == 403


def test_settings_has_a_vault_section_with_the_webdav_json_button(shop_app, saves_dir):
    html = _login(shop_app, "admin").get("/admin/settings").get_data(as_text=True)
    assert 'id="Vault"' in html and 'id="vaultDownloadWebdav"' in html and 'id="vaultOrigin"' in html
    js = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "js", "settings.js"), encoding="utf-8").read()
    assert "basepath: 'JKSV'" in js and "'/dav'" in js


def test_one_backup_reads_in_the_singular():
    """Seen in the browser: "1 backups" / "1 copias"."""
    import i18n
    assert i18n.TRANSLATIONS["saves.backups_one"]["es"].startswith("1 copia ·")
    assert i18n.TRANSLATIONS["game.saves_value_one"]["es"].startswith("1 copia,")
    root = os.path.join(os.path.dirname(__file__), "..", "app", "static", "js")
    assert "I18N.backupsOne" in open(os.path.join(root, "saves.js"), encoding="utf-8").read()
    assert "I18N.savesValueOne" in open(os.path.join(root, "game.js"), encoding="utf-8").read()


# --- final review fixes -----------------------------------------------------------------------

def _lying_zip(real_entries=30, declared=1):
    """A ZIP whose end record understates its entries: zipfile reads the real ones."""
    data = bytearray(_meta_zip(extra_entries=real_entries))
    at = bytes(data).rfind(b"PK\x05\x06")
    data[at + 8:at + 10] = struct.pack("<H", declared)
    data[at + 10:at + 12] = struct.pack("<H", declared)
    return bytes(data)


def test_the_entry_cap_counts_the_real_entries_not_the_declared_ones(on, saves_dir, monkeypatch, tmp_path):
    monkeypatch.setattr(vault, "MAX_ZIP_ENTRIES", 10)
    path = tmp_path / "liar.zip"
    path.write_bytes(_lying_zip())
    assert vault.read_meta(str(path)) == (None, None)
    _dav(on, "MKCOL", "/dav/JKSV/game")
    assert _dav(on, "PUT", "/dav/JKSV/game/liar.zip", data=_lying_zip()).status_code == 422


def test_a_cut_off_upload_never_replaces_a_backup_or_leaves_a_temp_file(on, saves_dir):
    _dav(on, "MKCOL", "/dav/JKSV/game")
    good = _meta_zip()
    _dav(on, "PUT", "/dav/JKSV/game/b.zip", data=good)
    environ = {"CONTENT_LENGTH": str(len(good) + 5000)}
    resp = on.open("/dav/JKSV/game/b.zip", method="PUT", data=good[:100], headers=_auth(),
                   environ_overrides=environ)
    assert resp.status_code == 400
    assert (saves_dir / "JKSV" / "game" / "b.zip").read_bytes() == good
    assert not [p for p in (saves_dir / "JKSV" / "game").iterdir() if p.name.startswith(".upload-")]


def test_the_shareable_export_leaves_out_the_vault_password(shop_app, saves_dir):
    admin = _login(shop_app, "admin")
    admin.post("/api/settings/vault", json={"enabled": True, "username": "jksv", "password": PASSWORD, "keep": 0})
    shared = admin.get("/api/settings/export?include_secrets=0").get_data(as_text=True)
    assert "password_hash" not in shared


def test_a_known_good_login_keeps_working_while_someone_else_guesses(on):
    assert _dav(on, "PROPFIND", "/dav/", headers={"Depth": "0"}).status_code == 207
    for _ in range(6):
        on.open("/dav/", method="PROPFIND", headers=_auth(password="guess-guess-guess"))
    assert _dav(on, "PROPFIND", "/dav/", headers={"Depth": "0"}).status_code == 207


def test_a_wrong_username_costs_the_same_hash_check(on, monkeypatch):
    calls = []
    real = vault.check_password_hash
    monkeypatch.setattr(vault, "check_password_hash", lambda h, p: calls.append(1) or real(h, p))
    on.open("/dav/", method="PROPFIND", headers=_auth(user="someone", password="whatever-pass"))
    assert calls, "a wrong username must not answer faster"


def test_names_with_percent_signs_are_reachable_and_control_characters_refused(on, saves_dir):
    _dav(on, "MKCOL", "/dav/JKSV/game")
    assert _dav(on, "PUT", "/dav/JKSV/game/100%25.zip", data=_meta_zip()).status_code == 201
    assert (saves_dir / "JKSV" / "game" / "100%.zip").exists()
    listing = _dav(on, "PROPFIND", "/dav/JKSV/game/", headers={"Depth": "1"}).get_data(as_text=True)
    assert "/dav/JKSV/game/100%25.zip" in listing
    assert _dav(on, "GET", "/dav/JKSV/game/100%25.zip").status_code == 200
    # Refused before (Flask's router) or by the vault itself; never stored.
    assert _dav(on, "PUT", "/dav/JKSV/game/a%0Ab.zip", data=_meta_zip()).status_code in (400, 404)
    assert not [p for p in (saves_dir / "JKSV" / "game").iterdir() if "\n" in p.name]


def test_a_folder_named_like_a_backup_is_refused(on):
    _dav(on, "MKCOL", "/dav/JKSV/game")
    assert _dav(on, "MKCOL", "/dav/JKSV/game/x.zip").status_code == 403


def test_small_disks_can_still_take_backups():
    assert vault.MIN_FREE <= 512 << 20


def test_backup_only_users_dont_see_the_library_list(shop_app, on, saves_dir):
    _dav(on, "MKCOL", "/dav/JKSV/Zelda")
    _dav(on, "PUT", "/dav/JKSV/Zelda/b.zip", data=_meta_zip())
    from auth import create_or_update_user
    with shop_app.app.app_context():
        create_or_update_user("vaultonly", "vaultonlypass1", shop_access=False, backup_access=True)
    shop_app.client.post("/login", data={"user": "vaultonly", "password": "vaultonlypass1"})
    assert shop_app.client.get("/api/saves").get_json()["missing"] == []
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "app.py"), encoding="utf-8").read()
    body = src[src.index("def saves_api"):src.index("def saves_download_api")]
    assert "current_user.has_access('shop')" in body


def test_discord_never_pings_from_names_in_messages():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "notifications.py"), encoding="utf-8").read()
    body = src[src.index("def _send_discord"):src.index("def _send_telegram")]
    assert "'allowed_mentions': {'parse': []}" in body


def test_the_meta_cache_forgets_deleted_backups(on, saves_dir):
    _dav(on, "MKCOL", "/dav/JKSV/game")
    _dav(on, "PUT", "/dav/JKSV/game/b.zip", data=_meta_zip())
    vault.backups()
    _dav(on, "DELETE", "/dav/JKSV/game/b.zip")
    vault.backups()
    assert not any("b.zip" in key[0] for key in vault._meta_cache)

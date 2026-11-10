"""The save vault: JKSV uploads save backups over WebDAV to /dav/, each user into their
own space with their own vault password (My account), only while an admin has the vault
turned on (Services) (app/vault.py)."""
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


def _auth(user="keeper", password=PASSWORD):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _login(shop_app, user, password=None):
    resp = shop_app.client.post("/login", data={"user": user, "password": password or fixture.PASSWORDS[user]})
    assert resp.status_code == 302
    return shop_app.client


def _user(shop_app, name, password, **access):
    from auth import create_or_update_user
    from db import User
    with shop_app.app.app_context():
        create_or_update_user(name, password, **access)
        return User.query.filter_by(user=name).one().id


def _vault_password(shop_app, name, web_password, vault_password=PASSWORD):
    client = _login(shop_app, name, web_password)
    resp = client.post("/api/account/vault", json={"password": vault_password})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    client.get("/logout")


@pytest.fixture
def saves_dir(tmp_path, monkeypatch):
    root = tmp_path / "saves"
    monkeypatch.setattr(vault, "SAVES_DIR", str(root))
    monkeypatch.setattr(vault, "_free_bytes", lambda path: 100 << 30)
    vault.clear_auth_cache()
    vault._meta_cache.clear()     # each test starts with none from another's folders
    return root


def _turn_on(shop_app, keep=0):
    admin = _login(shop_app, "admin")
    resp = admin.post("/api/settings/vault", json={"enabled": True, "keep": keep})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    admin.get("/logout")


@pytest.fixture
def keeper(shop_app, saves_dir):
    """A user with the Backup permission (and the shop), with a vault password set."""
    user_id = _user(shop_app, "keeper", "keeperpass1", shop_access=True, backup_access=True)
    _vault_password(shop_app, "keeper", "keeperpass1")
    return user_id


@pytest.fixture
def on(shop_app, keeper):
    _turn_on(shop_app)
    return shop_app.client


@pytest.fixture
def space(saves_dir, keeper):
    """The keeper's own space in the vault."""
    return saves_dir / "users" / str(keeper)


def _dav(client, method, path, data=None, headers=None, user="keeper"):
    return client.open(path, method=method, data=data, headers={**_auth(user), **(headers or {})})


# --- off, and who gets in ------------------------------------------------------------------

def test_the_vault_is_off_by_default(shop_app, keeper):
    assert shop_app.client.open("/dav/", method="PROPFIND", headers=_auth()).status_code == 404


def test_it_asks_for_the_users_own_vault_password(on):
    resp = on.open("/dav/", method="PROPFIND")
    assert resp.status_code == 401 and "Basic" in resp.headers["WWW-Authenticate"]
    assert on.open("/dav/", method="PROPFIND", headers=_auth(password="wrong-password")).status_code == 401
    # The web password doesn't open it: only the vault password from My account.
    assert on.open("/dav/", method="PROPFIND", headers=_auth(password="keeperpass1")).status_code == 401
    assert on.open("/dav/", method="PROPFIND", headers=_auth()).status_code == 207


def test_only_users_with_the_backup_permission_get_in(shop_app, on):
    _user(shop_app, "nobackup", "nobackuppass1", shop_access=True, backup_access=False)
    client = _login(shop_app, "nobackup", "nobackuppass1")
    assert client.post("/api/account/vault", json={"password": PASSWORD}).status_code == 403
    client.get("/logout")
    assert on.open("/dav/", method="PROPFIND", headers=_auth("nobackup")).status_code == 401


def test_losing_the_permission_closes_the_vault(shop_app, on, keeper):
    from db import User, db
    assert _dav(on, "PROPFIND", "/dav/", headers={"Depth": "0"}).status_code == 207
    with shop_app.app.app_context():
        db.session.get(User, keeper).backup_access = False
        db.session.commit()
    vault.clear_auth_cache()
    assert _dav(on, "PROPFIND", "/dav/", headers={"Depth": "0"}).status_code == 401


def test_repeated_wrong_passwords_are_locked_out(on):
    for _ in range(5):
        on.open("/dav/", method="PROPFIND", headers=_auth(password="nope-nope-nope"))
    assert on.open("/dav/", method="PROPFIND", headers=_auth()).status_code == 429


# --- what JKSV does --------------------------------------------------------------------------

def test_jksv_lists_creates_a_folder_uploads_and_reads_back(on, space):
    assert _dav(on, "OPTIONS", "/dav/").headers.get("DAV")
    listing = _dav(on, "PROPFIND", "/dav/", headers={"Depth": "1"})
    assert listing.status_code == 207 and "/dav/JKSV/" in listing.get_data(as_text=True)
    assert _dav(on, "MKCOL", "/dav/JKSV/Zelda%20BOTW").status_code == 201
    body = _meta_zip()
    assert _dav(on, "PUT", "/dav/JKSV/Zelda%20BOTW/2026-01-01.zip", data=body).status_code == 201
    assert (space / "JKSV" / "Zelda BOTW" / "2026-01-01.zip").read_bytes() == body
    folder = _dav(on, "PROPFIND", "/dav/JKSV/Zelda%20BOTW/", headers={"Depth": "1"}).get_data(as_text=True)
    assert "2026-01-01.zip" in folder and f"<D:getcontentlength>{len(body)}</D:getcontentlength>" in folder
    assert _dav(on, "GET", "/dav/JKSV/Zelda%20BOTW/2026-01-01.zip").data == body
    moved = _dav(on, "MOVE", "/dav/JKSV/Zelda%20BOTW/2026-01-01.zip",
                 headers={"Destination": "http://localhost/dav/JKSV/Zelda%20BOTW/renamed.zip"})
    assert moved.status_code in (201, 204) and (space / "JKSV" / "Zelda BOTW" / "renamed.zip").exists()
    assert _dav(on, "DELETE", "/dav/JKSV/Zelda%20BOTW/renamed.zip").status_code == 204


# --- each user's own space -----------------------------------------------------------------

@pytest.fixture
def other(shop_app, on):
    """A second user with the Backup permission and a backup of their own."""
    user_id = _user(shop_app, "other", "otherpass12", shop_access=True, backup_access=True)
    _vault_password(shop_app, "other", "otherpass12", "other-secret-2")
    headers = _auth("other", "other-secret-2")
    on.open("/dav/JKSV/Mario", method="MKCOL", headers=headers)
    assert on.open("/dav/JKSV/Mario/m.zip", method="PUT", data=_meta_zip(), headers=headers).status_code == 201
    return user_id


def test_each_user_sees_only_their_own_backups(shop_app, on, other, space):
    _dav(on, "MKCOL", "/dav/JKSV/Zelda")
    _dav(on, "PUT", "/dav/JKSV/Zelda/b.zip", data=_meta_zip())
    listing = _dav(on, "PROPFIND", "/dav/JKSV/", headers={"Depth": "1"}).get_data(as_text=True)
    assert "Zelda" in listing and "Mario" not in listing
    assert _dav(on, "GET", "/dav/JKSV/Mario/m.zip").status_code == 404
    client = _login(shop_app, "keeper", "keeperpass1")
    games = client.get("/api/saves").get_json()["games"]
    assert [g["folder"] for g in games] == ["Zelda"]
    # Another user's backup can't be named from here: paths are inside one's own space.
    assert client.get("/api/saves/download", query_string={"path": "Mario/m.zip"}).status_code == 404
    assert client.get("/api/saves/download", query_string={"path": "Mario/m.zip", "user": other}).status_code == 404
    assert client.delete("/api/saves", query_string={"path": "Mario/m.zip", "user": other}).status_code == 404


def test_the_saves_page_is_ones_own_even_for_an_admin(shop_app, on, other, keeper):
    """Nobody sees anyone else's saves on the Saves page; an admin (or a collaborator)
    downloads every upload from the Dashboard's "Uploaded saves" instead."""
    _dav(on, "MKCOL", "/dav/JKSV/Zelda")
    _dav(on, "PUT", "/dav/JKSV/Zelda/b.zip", data=_meta_zip())
    admin = _login(shop_app, "admin")
    assert admin.get("/api/saves").get_json()["games"] == []
    assert admin.get("/api/saves/download", query_string={"path": "Mario/m.zip", "user": other}).status_code == 404
    assert admin.delete("/api/saves", query_string={"path": "Mario/m.zip", "user": other}).status_code == 404
    resp = admin.get("/api/admin/saves/download", query_string={"path": "Mario/m.zip", "user": other})
    assert resp.status_code == 200
    resp.close()      # Windows won't delete a file a response still holds open


def test_backups_from_before_go_to_the_first_admin(shop_app, saves_dir, keeper):
    """The vault had one shared space: its backups move to the first admin's space."""
    old = saves_dir / "JKSV" / "Zelda"
    old.mkdir(parents=True)
    (old / "old.zip").write_bytes(_meta_zip())
    _turn_on(shop_app)
    admin = _login(shop_app, "admin")
    from db import User
    with shop_app.app.app_context():
        admin_id = User.query.filter_by(user="admin").one().id
    games = admin.get("/api/saves").get_json()["games"]
    assert games and games[0]["user_id"] == admin_id and games[0]["folder"] == "Zelda"
    assert (saves_dir / "users" / str(admin_id) / "JKSV" / "Zelda" / "old.zip").exists()
    assert not (saves_dir / "JKSV").exists()


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
def test_the_vault_refuses_anything_but_backups_in_the_jksv_folder(on, space, saves_dir, method, path, headers, data):
    (space / "JKSV" / "game").mkdir(parents=True)
    (space / "JKSV" / "game" / "a.zip").write_bytes(_meta_zip())
    assert _dav(on, method, path, data=data, headers=headers).status_code in (400, 403, 405)
    assert not (saves_dir.parent / "escape.zip").exists() and not (space.parent / "escape.zip").exists()


def test_an_upload_needs_room_left_on_the_disk(on, space, monkeypatch):
    _dav(on, "MKCOL", "/dav/JKSV/game")
    monkeypatch.setattr(vault, "_free_bytes", lambda path: 100 << 20)     # 100 MB free
    assert _dav(on, "PUT", "/dav/JKSV/game/b.zip", data=_meta_zip()).status_code == 507
    assert not (space / "JKSV" / "game" / "b.zip").exists()


def test_a_zip_with_absurdly_many_entries_is_refused(on, space, monkeypatch):
    monkeypatch.setattr(vault, "MAX_ZIP_ENTRIES", 10)
    _dav(on, "MKCOL", "/dav/JKSV/game")
    assert _dav(on, "PUT", "/dav/JKSV/game/bomb.zip", data=_meta_zip(extra_entries=20)).status_code == 422
    assert not (space / "JKSV" / "game" / "bomb.zip").exists()


def test_old_backups_beyond_the_kept_number_are_removed(shop_app, keeper, space):
    _turn_on(shop_app, keep=5)
    client = shop_app.client
    _dav(client, "MKCOL", "/dav/JKSV/game")
    past = time.time() - 1000
    for n in range(7):
        _dav(client, "PUT", f"/dav/JKSV/game/{n}.zip", data=_meta_zip())
        # Older uploads, older files: the newest is always the one just uploaded.
        os.utime(space / "JKSV" / "game" / f"{n}.zip", (past + n, past + n))
    left = sorted(p.name for p in (space / "JKSV" / "game").iterdir())
    assert left == ["2.zip", "3.zip", "4.zip", "5.zip", "6.zip"]


def test_a_new_backup_is_notified_with_its_user(on, monkeypatch):
    sent = []
    import notifications
    monkeypatch.setattr(notifications, "notify", lambda event, item, title_id=None, user=None: sent.append((event, item)))
    _dav(on, "MKCOL", "/dav/JKSV/Zelda")
    _dav(on, "PUT", "/dav/JKSV/Zelda/b.zip", data=_meta_zip())
    assert sent and sent[0][0] == "save_backup" and "Zelda" in sent[0][1] and "keeper" in sent[0][1]
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


# --- settings and My account -----------------------------------------------------------------

def test_the_admin_sets_on_off_how_many_are_kept_and_who_may_use_it(shop_app, saves_dir):
    admin = _login(shop_app, "admin")
    assert admin.post("/api/settings/vault", json={"enabled": True, "keep": 0}).status_code == 200
    assert admin.post("/api/settings/vault", json={"enabled": False, "keep": 3}).status_code == 400
    from settings import get_settings
    stored = get_settings()["vault"]
    assert set(stored) == {"enabled", "keep", "max_games", "admins", "users"}


def test_the_vault_password_is_kept_hashed_on_the_user(shop_app, keeper):
    from db import User, db
    with shop_app.app.app_context():
        stored = db.session.get(User, keeper).vault_password
    assert stored and PASSWORD not in stored
    client = _login(shop_app, "keeper", "keeperpass1")
    sent = client.get("/api/account/vault").get_json()
    assert sent == {"enabled": False, "password_set": True, "username": "keeper"}
    assert client.post("/api/account/vault", json={"password": "short"}).status_code == 400


def test_only_admins_change_the_vault(shop_app, saves_dir):
    client = _login(shop_app, "shopper")
    assert client.post("/api/settings/vault", json={"enabled": True}).status_code in (302, 401, 403)


def test_my_account_has_the_vault_section_for_backup_users(shop_app, keeper):
    client = _login(shop_app, "keeper", "keeperpass1")
    html = client.get("/account").get_data(as_text=True)
    for needle in ('id="accountVault"', 'id="vaultPassword"', 'id="vaultOrigin"', 'id="vaultDownloadWebdav"'):
        assert needle in html, needle
    client.get("/logout")
    shopper = _login(shop_app, "shopper")
    assert 'id="accountVault"' not in shopper.get("/account").get_data(as_text=True)
    js = open(os.path.join(os.path.dirname(__file__), "..", "app", "static", "js", "account.js"), encoding="utf-8").read()
    assert "basepath: 'JKSV'" in js and "'/dav'" in js and "username: VAULT_USER" in js


def test_settings_keeps_only_the_vault_options_for_everyone(shop_app, saves_dir):
    html = _login(shop_app, "admin").get("/admin/settings").get_data(as_text=True)
    section = html[html.index('id="Vault"'):html.index('id="Notifications"')]
    assert 'id="vaultKeep"' in section
    assert 'id="vaultPassword"' not in section and 'id="vaultDownloadWebdav"' not in section


# --- the Saves page ----------------------------------------------------------------------------

def test_the_saves_page_and_api_list_backups_by_game(shop_app, on, space):
    _dav(on, "MKCOL", "/dav/JKSV/Zelda")
    _dav(on, "PUT", "/dav/JKSV/Zelda/b.zip", data=_meta_zip())
    client = _login(shop_app, "keeper", "keeperpass1")
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
    assert not (space / "JKSV" / "Zelda" / "b.zip").exists()


def test_users_without_backup_access_dont_see_saves(shop_app, on):
    client = _login(shop_app, "shopper")
    assert client.get("/saves").status_code == 403
    assert client.get("/api/saves").status_code == 403


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


def test_the_entry_cap_counts_the_real_entries_not_the_declared_ones(on, monkeypatch, tmp_path):
    monkeypatch.setattr(vault, "MAX_ZIP_ENTRIES", 10)
    path = tmp_path / "liar.zip"
    path.write_bytes(_lying_zip())
    assert vault.read_meta(str(path)) == (None, None)
    _dav(on, "MKCOL", "/dav/JKSV/game")
    assert _dav(on, "PUT", "/dav/JKSV/game/liar.zip", data=_lying_zip()).status_code == 422


def test_a_cut_off_upload_never_replaces_a_backup_or_leaves_a_temp_file(on, space):
    _dav(on, "MKCOL", "/dav/JKSV/game")
    good = _meta_zip()
    _dav(on, "PUT", "/dav/JKSV/game/b.zip", data=good)
    environ = {"CONTENT_LENGTH": str(len(good) + 5000)}
    resp = on.open("/dav/JKSV/game/b.zip", method="PUT", data=good[:100], headers=_auth(),
                   environ_overrides=environ)
    assert resp.status_code == 400
    assert (space / "JKSV" / "game" / "b.zip").read_bytes() == good
    assert not [p for p in (space / "JKSV" / "game").iterdir() if p.name.startswith(".upload-")]


def test_the_export_never_carries_vault_passwords(shop_app, keeper):
    admin = _login(shop_app, "admin")
    shared = admin.get("/api/settings/export?include_secrets=0").get_data(as_text=True)
    assert "password_hash" not in shared and "vault_password" not in shared


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


def test_names_with_percent_signs_are_reachable_and_control_characters_refused(on, space):
    _dav(on, "MKCOL", "/dav/JKSV/game")
    assert _dav(on, "PUT", "/dav/JKSV/game/100%25.zip", data=_meta_zip()).status_code == 201
    assert (space / "JKSV" / "game" / "100%.zip").exists()
    listing = _dav(on, "PROPFIND", "/dav/JKSV/game/", headers={"Depth": "1"}).get_data(as_text=True)
    assert "/dav/JKSV/game/100%25.zip" in listing
    assert _dav(on, "GET", "/dav/JKSV/game/100%25.zip").status_code == 200
    # Refused before (Flask's router) or by the vault itself; never stored.
    assert _dav(on, "PUT", "/dav/JKSV/game/a%0Ab.zip", data=_meta_zip()).status_code in (400, 404)
    assert not [p for p in (space / "JKSV" / "game").iterdir() if "\n" in p.name]


def test_a_folder_named_like_a_backup_is_refused(on):
    _dav(on, "MKCOL", "/dav/JKSV/game")
    assert _dav(on, "MKCOL", "/dav/JKSV/game/x.zip").status_code == 403


def test_small_disks_can_still_take_backups():
    assert vault.MIN_FREE <= 512 << 20


def test_saves_page_lists_only_games_with_backups(shop_app, on, saves_dir):
    # Phase 8: the "library games without a backup" list is gone, for every user.
    _user(shop_app, "vaultonly", "vaultonlypass1", shop_access=False, backup_access=True)
    _vault_password(shop_app, "vaultonly", "vaultonlypass1")
    headers = _auth("vaultonly")
    shop_app.client.open("/dav/JKSV/Zelda", method="MKCOL", headers=headers)
    shop_app.client.open("/dav/JKSV/Zelda/b.zip", method="PUT", data=_meta_zip(), headers=headers)
    _login(shop_app, "vaultonly", "vaultonlypass1")
    body = shop_app.client.get("/api/saves").get_json()
    assert "missing" not in body
    assert [g["folder"] for g in body["games"]] == ["Zelda"]
    html = shop_app.client.get("/saves").get_data(as_text=True)
    assert "savesMissing" not in html


def test_discord_never_pings_from_names_in_messages():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "notifications.py"), encoding="utf-8").read()
    body = src[src.index("def _send_discord"):src.index("def _send_telegram")]
    assert "'allowed_mentions': {'parse': []}" in body


def test_the_meta_cache_forgets_deleted_backups(on, keeper):
    _dav(on, "MKCOL", "/dav/JKSV/game")
    _dav(on, "PUT", "/dav/JKSV/game/b.zip", data=_meta_zip())
    vault.backups([keeper])
    _dav(on, "DELETE", "/dav/JKSV/game/b.zip")
    vault.backups([keeper])
    assert not any("b.zip" in key[0] for key in vault._meta_cache)


def test_a_migration_adds_the_vault_password_and_avatar_and_is_the_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from db import User
    assert "vault_password" in User.__table__.columns and "avatar" in User.__table__.columns
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "app", "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["a7b8c9d0e1f3"]
    assert script.get_revision("b2c3d4e5f6a8").down_revision == "a1b2c3d4e5f7"


# --- how many different games each user keeps --------------------------------------------

def _limit_games(shop_app, n, keep=0):
    admin = _login(shop_app, "admin")
    resp = admin.post("/api/settings/vault", json={"enabled": True, "keep": keep, "max_games": n})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    admin.get("/logout")


def test_two_backups_per_game_can_be_kept(shop_app, saves_dir):
    _limit_games(shop_app, 0, keep=2)
    from settings import get_settings
    assert get_settings()["vault"]["keep"] == 2 and 2 in vault.KEEP_CHOICES


def test_the_game_limit_counts_games_not_copies_and_never_deletes(shop_app, keeper, space):
    _limit_games(shop_app, 10)
    from settings import set_vault_settings
    set_vault_settings({"max_games": 2})        # 2 to keep the test short (the UI offers 10-50)
    client = shop_app.client
    for game in ("A", "B", "C"):
        assert _dav(client, "MKCOL", f"/dav/JKSV/{game}").status_code == 201
    assert _dav(client, "PUT", "/dav/JKSV/A/1.zip", data=_meta_zip()).status_code == 201
    assert _dav(client, "PUT", "/dav/JKSV/B/1.zip", data=_meta_zip()).status_code == 201
    # More copies of a game already kept: always.
    assert _dav(client, "PUT", "/dav/JKSV/A/2.zip", data=_meta_zip()).status_code == 201
    # A third game: refused, and nothing older goes to make room.
    assert _dav(client, "PUT", "/dav/JKSV/C/1.zip", data=_meta_zip()).status_code == 507
    assert sorted(p.name for p in (space / "JKSV" / "A").iterdir()) == ["1.zip", "2.zip"]
    assert not (space / "JKSV" / "C" / "1.zip").exists()
    # A move into the new game is refused the same way.
    moved = _dav(client, "MOVE", "/dav/JKSV/A/2.zip", headers={"Destination": "http://localhost/dav/JKSV/C/2.zip"})
    assert moved.status_code == 507
    # Deleting every save of a game frees its place.
    assert vault.delete_backup(keeper, "B/1.zip")
    assert not (space / "JKSV" / "B").exists()      # the emptied game goes from the list too
    assert _dav(client, "PUT", "/dav/JKSV/C/1.zip", data=_meta_zip()).status_code == 201


def test_the_settings_offer_the_limit_and_refuse_other_values(shop_app, saves_dir):
    admin = _login(shop_app, "admin")
    assert admin.post("/api/settings/vault", json={"enabled": True, "keep": 0, "max_games": 30}).status_code == 200
    assert admin.post("/api/settings/vault", json={"enabled": True, "keep": 0, "max_games": 7}).status_code == 400
    html = admin.get("/admin/settings").get_data(as_text=True)
    assert 'id="vaultMaxGames"' in html
    assert vault.GAME_CHOICES == (0, 10, 20, 30, 40, 50)

"""Public registration with email verification, password reset and Google sign-in
(app/accounts.py and its routes). Email and Google are simulated: nothing goes online."""
import os
import re

import fixture
import pytest

import accounts
import accounts_views
from db import User, db

ROOT = os.path.join(os.path.dirname(__file__), "..")
SMTP_ENV = {"SMTP_HOST": "smtp.example.test", "SMTP_PORT": "587", "SMTP_SECURITY": "TLS",
            "SMTP_USER": "mailer", "SMTP_PASSWORD": "smtp-secret", "SMTP_FROM": "shop@example.test"}
GOOGLE_ENV = {"GOOGLE_CLIENT_ID": "cid.apps.googleusercontent.com", "GOOGLE_CLIENT_SECRET": "gsecret",
              "GOOGLE_REDIRECT_URI": "http://localhost/login/google/callback"}


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """The tries per address are kept in the process: each test starts with none."""
    import auth
    auth._login_failures.clear()
    yield
    auth._login_failures.clear()


@pytest.fixture
def outbox(monkeypatch):
    """Every email the app sends, instead of sending it."""
    sent = []
    monkeypatch.setattr(accounts, "_deliver", lambda msg, cfg: sent.append(msg))
    monkeypatch.setattr(accounts, "SEND_IN_BACKGROUND", False)
    for k, v in SMTP_ENV.items():
        monkeypatch.setenv(k, v)
    return sent


def _admin(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code == 302
    return shop_app.client


def _open(shop_app, public_url="http://shop.example.test"):
    admin = _admin(shop_app)
    resp = admin.post("/api/settings/registration", json={"enabled": True, "public_url": public_url})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    admin.get("/logout")
    return shop_app.client


def _link(message, path):
    match = re.search(rf"(https?://[^\s]+{path}/[^\s]+)", message.get_content())
    assert match, message.get_content()
    return match.group(1).split("://", 1)[1].split("/", 1)[1]   # the path, for the test client


def _signup(client, user="newbie", email="newbie@example.test", password="newbiepass1"):
    return client.post("/signup", data={"user": user, "email": email, "password": password,
                                        "confirm": password})


# --- the user row ------------------------------------------------------------------------

def test_users_gain_email_verification_and_google_columns():
    cols = User.__table__.columns
    for name in ("email", "email_verified", "pending_email", "google_id", "pending"):
        assert name in cols, name
    assert cols["email"].unique and cols["google_id"].unique


def test_a_migration_adds_them_and_is_the_new_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(ROOT, "app", "migrations"))
    script = ScriptDirectory.from_config(cfg)
    assert "a1b2c3d4e5f7" in {r.revision for r in script.walk_revisions()}
    assert script.get_revision("a1b2c3d4e5f7").down_revision == "f9a0b1c2d3e4"


def test_secret_key_is_read_from_SECRET_KEY_too(monkeypatch):
    import app as app_mod
    monkeypatch.delenv("OWNFOIL_SECRET_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY", "from-secret-key-var")
    assert app_mod.load_or_create_secret_key() == "from-secret-key-var"
    monkeypatch.setenv("OWNFOIL_SECRET_KEY", "ownfoil-wins")
    assert app_mod.load_or_create_secret_key() == "ownfoil-wins"


# --- email --------------------------------------------------------------------------------

def test_email_settings_come_from_the_environment(monkeypatch):
    for k in SMTP_ENV:
        monkeypatch.delenv(k, raising=False)
    assert accounts.smtp_config() is None
    for k, v in SMTP_ENV.items():
        monkeypatch.setenv(k, v)
    cfg = accounts.smtp_config()
    assert cfg["host"] == "smtp.example.test" and cfg["port"] == 587 and cfg["security"] == "tls"


@pytest.mark.parametrize("security,cls,starttls", [("SSL", "SMTP_SSL", False), ("TLS", "SMTP", True),
                                                   ("NONE", "SMTP", False)])
def test_email_is_sent_with_the_chosen_security(monkeypatch, security, cls, starttls):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, **kw):
            calls.append(("open", type(self).__name__, host, port))
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def starttls(self, **kw):
            calls.append(("starttls",))
        def login(self, user, password):
            calls.append(("login", user))
        def send_message(self, msg):
            calls.append(("send", msg["To"]))

    class SMTP(FakeSMTP):
        pass

    class SMTP_SSL(FakeSMTP):
        pass

    monkeypatch.setattr(accounts.smtplib, "SMTP", SMTP)
    monkeypatch.setattr(accounts.smtplib, "SMTP_SSL", SMTP_SSL)
    for k, v in dict(SMTP_ENV, SMTP_SECURITY=security).items():
        monkeypatch.setenv(k, v)
    accounts.send_mail("someone@example.test", "Hi", "Body")
    assert calls[0][1] == cls
    assert (("starttls",) in calls) is starttls
    assert ("login", "mailer") in calls and ("send", "someone@example.test") in calls


def test_admin_can_send_a_test_email(shop_app, outbox):
    admin = _admin(shop_app)
    resp = admin.post("/api/settings/registration/test-email", json={"to": "me@example.test"})
    assert resp.status_code == 200 and outbox and outbox[0]["To"] == "me@example.test"


# --- registration ----------------------------------------------------------------------------

def test_registration_is_closed_by_default(shop_app, outbox):
    assert shop_app.client.get("/signup").status_code == 404
    assert _signup(shop_app.client).status_code == 404
    assert "/signup" not in shop_app.client.get("/login").get_data(as_text=True)


def test_registration_needs_email_to_verify_the_account(shop_app, monkeypatch):
    client = _open(shop_app)
    for k in SMTP_ENV:
        monkeypatch.delenv(k, raising=False)
    assert _signup(client).status_code == 400
    with shop_app.app.app_context():
        assert User.query.filter_by(user="newbie").first() is None


def test_a_new_account_waits_for_its_email_and_gets_shop_access_only(shop_app, outbox):
    client = _open(shop_app)
    assert _signup(client).status_code == 200
    with shop_app.app.app_context():
        u = User.query.filter_by(user="newbie").one()
        # Unverified, the address is only a claim: `email` holds verified ones alone.
        assert u.pending and not u.email_verified and u.email is None
        assert u.pending_email == "newbie@example.test"
        # Shop and backups by default, never the administration.
        assert u.shop_access and u.backup_access and not u.admin_access
    assert len(outbox) == 1 and outbox[0]["To"] == "newbie@example.test"
    # Not before verifying - neither the web nor the shop clients' Basic Auth.
    login = client.post("/login", data={"user": "newbie", "password": "newbiepass1"})
    assert login.status_code == 403 and "/verify/resend" in login.get_data(as_text=True)
    path = _link(outbox[0], "/verify")
    assert client.get("/" + path).status_code in (200, 302)
    with shop_app.app.app_context():
        u = User.query.filter_by(user="newbie").one()
        assert not u.pending and u.email_verified and u.email == "newbie@example.test" and u.pending_email is None
    assert client.post("/login", data={"user": "newbie", "password": "newbiepass1"}).status_code == 302


def test_the_email_link_uses_the_public_address(shop_app, outbox):
    client = _open(shop_app, public_url="https://shop.example.test/")
    _signup(client)
    assert "https://shop.example.test/verify/" in outbox[0].get_content()


@pytest.mark.parametrize("fields,reason", [
    ({"user": "admin"}, "taken user"),
    ({"email": "not-an-email"}, "bad email"),
    ({"password": "short"}, "short password"),
    ({"password": "has@sign1"}, "Tinfoil forbids @"),
    ({"user": "bad name!"}, "bad user name"),
])
def test_signup_refuses_bad_or_taken_details(shop_app, outbox, fields, reason):
    client = _open(shop_app)
    data = {"user": "newbie", "email": "newbie@example.test", "password": "newbiepass1"}
    data.update(fields)
    resp = client.post("/signup", data=dict(data, confirm=data["password"]))
    assert resp.status_code == 400, reason


def test_signup_with_a_verified_email_tells_nothing_and_warns_its_owner(shop_app, outbox):
    client = _open(shop_app)
    _verified_user(shop_app, client, outbox)
    resp = _signup(client, user="other")
    assert resp.status_code == 200
    with shop_app.app.app_context():
        assert User.query.filter_by(user="other").first() is None
    assert len(outbox) == 1 and outbox[0]["To"] == "newbie@example.test"
    assert "/verify/" not in outbox[0].get_content()


def test_an_unverified_claim_never_blocks_the_real_owner(shop_app, outbox):
    """Someone signs up with your address and never verifies: you still can."""
    client = _open(shop_app)
    _signup(client, user="squatter", email="victim@example.test")
    outbox.clear()
    assert _signup(client, user="victim", email="victim@example.test").status_code == 200
    client.get("/" + _link(outbox[0], "/verify"))
    with shop_app.app.app_context():
        assert User.query.filter_by(user="victim").one().email == "victim@example.test"


def test_resend_never_says_whether_an_account_exists(shop_app, outbox):
    client = _open(shop_app)
    _signup(client)
    outbox.clear()
    a = client.post("/verify/resend", data={"email": "newbie@example.test"})
    b = client.post("/verify/resend", data={"email": "nobody@example.test"})
    assert a.status_code == b.status_code == 200
    assert a.get_data(as_text=True) == b.get_data(as_text=True)
    assert len(outbox) == 1


def test_signup_attempts_are_rate_limited(shop_app, outbox):
    client = _open(shop_app)
    tries = accounts_views.TRIES_PER_ADDRESS[0] + 1
    codes = [_signup(client, user=f"u{n}", email=f"u{n}@example.test").status_code for n in range(tries)]
    assert codes[-1] == 429


# --- password reset -----------------------------------------------------------------------------

def _verified_user(shop_app, client, outbox):
    _signup(client)
    client.get("/" + _link(outbox[0], "/verify"))
    client.get("/logout")
    outbox.clear()


def test_links_never_come_from_the_request_host(shop_app, outbox):
    """Without the public address set, account emails aren't sent at all: a link built
    from a forged Host header would hand a reset or verify token to whoever forged it."""
    client = _open(shop_app, public_url="")
    assert _signup(client).status_code == 400
    assert client.post("/forgot", data={"email": "x@example.test"}, headers={"Host": "evil.test"}).status_code == 200
    assert outbox == []
    assert 'href="/forgot"' not in client.get("/login").get_data(as_text=True)


def test_a_verify_link_works_once_and_never_signs_in(shop_app, outbox):
    client = _open(shop_app)
    _signup(client)
    path = "/" + _link(outbox[0], "/verify")
    client.get(path)
    assert client.get("/account").status_code in (302, 401)      # not signed in by the link
    assert client.get(path).status_code == 400                     # spent


def test_a_reset_link_dies_when_the_email_changes(shop_app, outbox):
    client = _open(shop_app)
    _verified_user(shop_app, client, outbox)
    client.post("/forgot", data={"email": "newbie@example.test"})
    path = "/" + _link(outbox[0], "/reset")
    with shop_app.app.app_context():
        u = User.query.filter_by(user="newbie").one()
        u.email = "moved@example.test"
        db.session.commit()
    assert client.get(path).status_code == 400


@pytest.mark.parametrize("bad", ["a,b@example.test", "x<y@example.test", '"q"@example.test'])
def test_an_email_is_one_plain_address(bad):
    assert not accounts.valid_email(bad)
    assert accounts.valid_email("plain.name+tag@example.test")


def test_forgot_is_also_limited_per_address(shop_app, outbox):
    client = _open(shop_app)
    _verified_user(shop_app, client, outbox)
    for n in range(6):
        client.post("/forgot", data={"email": "newbie@example.test"}, environ_overrides={"REMOTE_ADDR": f"10.0.0.{n}"})
    assert len(outbox) <= 3


def test_wrong_current_passwords_lock_the_password_form(shop_app):
    client = shop_app.client
    client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    for _ in range(5):
        client.post("/api/account/password", json={"current": "wrong", "new": "newshoppass1"})
    assert client.post("/api/account/password", json={"current": fixture.PASSWORDS["shopper"],
                                                      "new": "newshoppass1"}).status_code == 429


def test_emails_go_out_in_the_background():
    src = open(os.path.join(ROOT, "app", "accounts.py"), encoding="utf-8").read()
    assert "threading.Thread(" in src and "SEND_IN_BACKGROUND = True" in src


def test_google_never_replaces_a_different_linked_account(shop_app, google):
    with shop_app.app.app_context():
        u = User.query.filter_by(user="shopper").one()
        u.email, u.email_verified, u.google_id = "gamer@gmail.test", True, "another-sub"
        db.session.commit()
    assert _google_login(shop_app.client).status_code == 403
    with shop_app.app.app_context():
        assert User.query.filter_by(user="shopper").one().google_id == "another-sub"


def test_the_migration_adds_columns_without_rebuilding_the_user_table():
    """A batch rebuild drops `user`, and with foreign keys on that cascades into the
    wishlist."""
    src = open(os.path.join(ROOT, "app", "migrations", "versions", "a1b2c3d4e5f7_add_account_emails.py"),
               encoding="utf-8").read()
    assert "batch_alter_table" not in src and "create_index" in src


def test_forgot_password_sends_a_single_use_link(shop_app, outbox):
    client = _open(shop_app)
    _verified_user(shop_app, client, outbox)
    a = client.post("/forgot", data={"email": "newbie@example.test"})
    b = client.post("/forgot", data={"email": "nobody@example.test"})
    assert a.get_data(as_text=True) == b.get_data(as_text=True) and len(outbox) == 1
    path = "/" + _link(outbox[0], "/reset")
    assert client.get(path).status_code == 200
    assert client.post(path, data={"password": "brandnewpass1", "confirm": "brandnewpass1"}).status_code in (200, 302)
    assert client.post("/login", data={"user": "newbie", "password": "brandnewpass1"}).status_code == 302
    client.get("/logout")
    # The same link again: spent, the password already changed.
    assert client.post(path, data={"password": "another-pass1", "confirm": "another-pass1"}).status_code == 400


def test_an_expired_reset_link_is_refused(shop_app, outbox, monkeypatch):
    client = _open(shop_app)
    _verified_user(shop_app, client, outbox)
    client.post("/forgot", data={"email": "newbie@example.test"})
    monkeypatch.setattr(accounts, "RESET_MAX_AGE", -1)
    path = "/" + _link(outbox[0], "/reset")
    assert client.post(path, data={"password": "brandnewpass1", "confirm": "brandnewpass1"}).status_code == 400


# --- Google ---------------------------------------------------------------------------------------

@pytest.fixture
def google(monkeypatch):
    for k, v in GOOGLE_ENV.items():
        monkeypatch.setenv(k, v)
    profile = {"sub": "g-123", "email": "gamer@gmail.test", "email_verified": True}
    monkeypatch.setattr(accounts, "google_profile", lambda code: dict(profile) if code == "good-code" else None)
    return profile


def _google_login(client, code="good-code"):
    start = client.get("/login/google")
    assert start.status_code == 302 and "accounts.google.com" in start.headers["Location"]
    state = re.search(r"state=([^&]+)", start.headers["Location"]).group(1)
    return client.get("/login/google/callback", query_string={"state": state, "code": code})


def test_google_needs_its_settings(shop_app):
    assert shop_app.client.get("/login/google").status_code == 404


def test_the_google_callback_checks_its_state(shop_app, google):
    _open(shop_app)
    shop_app.client.get("/login/google")
    assert shop_app.client.get("/login/google/callback",
                               query_string={"state": "forged", "code": "good-code"}).status_code == 400


def test_google_creates_a_shop_account_when_registration_is_open(shop_app, google, outbox):
    client = _open(shop_app)
    assert _google_login(client).status_code == 302
    with shop_app.app.app_context():
        u = User.query.filter_by(google_id="g-123").one()
        assert u.user == "gamer" and u.email == "gamer@gmail.test" and u.email_verified and not u.pending
        assert u.shop_access and u.backup_access and not u.admin_access and u.password is None


def test_google_never_creates_accounts_while_registration_is_closed(shop_app, google):
    resp = _google_login(shop_app.client)
    assert resp.status_code == 403
    with shop_app.app.app_context():
        assert User.query.filter_by(google_id="g-123").first() is None


def test_google_signs_into_an_account_with_the_same_verified_email(shop_app, google):
    with shop_app.app.app_context():
        u = User.query.filter_by(user="shopper").one()
        u.email, u.email_verified = "gamer@gmail.test", True
        db.session.commit()
    assert _google_login(shop_app.client).status_code == 302
    with shop_app.app.app_context():
        assert User.query.filter_by(user="shopper").one().google_id == "g-123"


def test_google_never_takes_over_an_unverified_email(shop_app, google):
    with shop_app.app.app_context():
        u = User.query.filter_by(user="shopper").one()
        u.pending_email = "gamer@gmail.test"
        db.session.commit()
    assert _google_login(shop_app.client).status_code == 403
    with shop_app.app.app_context():
        assert User.query.filter_by(user="shopper").one().google_id is None


def test_an_account_without_a_password_cannot_sign_in_with_one(shop_app, google):
    client = _open(shop_app)
    _google_login(client)
    client.get("/logout")
    assert client.post("/login", data={"user": "gamer", "password": ""}).status_code == 401


# --- the login page and My account -------------------------------------------------------------------

def test_the_login_page_offers_what_is_on(shop_app, outbox, google):
    _open(shop_app)
    html = shop_app.client.get("/login").get_data(as_text=True)
    assert 'href="/signup"' in html and 'href="/forgot"' in html and 'href="/login/google"' in html


def test_my_account_sets_an_email_to_verify(shop_app, outbox):
    client = _open(shop_app)
    client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    resp = client.post("/api/account/email", json={"email": "shop@example.test"})
    assert resp.status_code == 200 and len(outbox) == 1
    with shop_app.app.app_context():
        u = User.query.filter_by(user="shopper").one()
        assert u.pending_email == "shop@example.test" and u.email is None and not u.pending
    client.get("/" + _link(outbox[0], "/verify"))
    with shop_app.app.app_context():
        u = User.query.filter_by(user="shopper").one()
        assert u.email_verified and u.email == "shop@example.test"


def test_my_account_changes_the_password_with_the_current_one(shop_app):
    client = shop_app.client
    client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    assert client.post("/api/account/password", json={"current": "wrong", "new": "newshoppass1"}).status_code == 400
    assert client.post("/api/account/password", json={"current": fixture.PASSWORDS["shopper"],
                                                      "new": "newshoppass1"}).status_code == 200


def test_settings_has_a_registration_section(shop_app):
    html = _admin(shop_app).get("/admin/settings").get_data(as_text=True)
    assert 'id="Registration"' in html and 'id="registrationEnabled"' in html and 'id="registrationTestEmail"' in html


def test_the_user_list_shows_emails(shop_app):
    users = _admin(shop_app).get("/api/users").get_json()
    assert all("email" in u and "email_verified" in u for u in users)

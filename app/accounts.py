"""Accounts people make themselves: public registration with email verification,
password reset, and Google sign-in.

Email goes out over SMTP and Google over OAuth 2.0, both set with environment variables
(see Install.md) - never in settings.yaml, so their secrets stay out of backups and
exports. No new dependency: smtplib from the standard library, itsdangerous (Flask's
own) for the signed links, requests for Google.

Links in emails are signed with the app's secret key and point only at the public
address set in Settings - never at the Host the request came in with, which anyone can
forge to get a link to their own server. Without that address, no account email goes out.
- verifying an email: valid a day, and only once - for the address still waiting for it;
- resetting a password: valid an hour, and only once - it carries a fingerprint of the
  password it replaces (and the account's email), so it stops working as soon as either
  changes.
"""
import hashlib
import logging
import os
import re
import secrets
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import urlencode

import requests
from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from settings import get_settings

logger = logging.getLogger('main')

VERIFY_SALT = 'ownfoil-verify-email'
RESET_SALT = 'ownfoil-reset-password'
VERIFY_MAX_AGE = 24 * 3600
RESET_MAX_AGE = 3600
SMTP_TIMEOUT = 10
# Account emails go out in a thread (send_mail_later). Tests turn it off to read them.
SEND_IN_BACKGROUND = True

GOOGLE_AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
GOOGLE_TIMEOUT = 15

EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$')
USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{3,32}$')


# --- settings -------------------------------------------------------------------------

def registration():
    return get_settings().get('registration') or {}


def registration_open():
    return bool(registration().get('enabled'))


def public_url():
    """The address links in emails point at, as set in Settings, or None."""
    return (registration().get('public_url') or '').strip().rstrip('/') or None


def valid_email(email):
    """One plain address: no display name, quotes, commas or angle brackets."""
    return len(email) <= 254 and bool(EMAIL_RE.match(email)) and parseaddr(email)[1] == email


def smtp_config():
    """SMTP from the environment, or None when it isn't set up (host and sender needed)."""
    host = (os.environ.get('SMTP_HOST') or '').strip()
    sender = (os.environ.get('SMTP_FROM') or '').strip()
    if not host or not sender:
        return None
    security = (os.environ.get('SMTP_SECURITY') or 'tls').strip().lower()
    if security not in ('tls', 'ssl', 'none'):
        security = 'tls'
    try:
        port = int(os.environ.get('SMTP_PORT') or (465 if security == 'ssl' else 587))
    except ValueError:
        port = 465 if security == 'ssl' else 587
    return {'host': host, 'port': port, 'security': security, 'from': sender,
            'user': os.environ.get('SMTP_USER') or '', 'password': os.environ.get('SMTP_PASSWORD') or ''}


def email_ready():
    """Account emails can go out: SMTP set up, and the public address their links use."""
    return smtp_config() is not None and public_url() is not None


def google_config():
    """Google OAuth from the environment, or None when any of its three values is missing."""
    cfg = {k: (os.environ.get(f'GOOGLE_{k.upper()}') or '').strip()
           for k in ('client_id', 'client_secret', 'redirect_uri')}
    return cfg if all(cfg.values()) else None


# --- email ----------------------------------------------------------------------------

def _deliver(message, cfg):
    context = ssl.create_default_context()
    if cfg['security'] == 'ssl':
        server = smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=SMTP_TIMEOUT, context=context)
    else:
        server = smtplib.SMTP(cfg['host'], cfg['port'], timeout=SMTP_TIMEOUT)
    with server:
        if cfg['security'] == 'tls':
            server.starttls(context=context)
        if cfg['user']:
            server.login(cfg['user'], cfg['password'])
        server.send_message(message)


def send_mail(to, subject, body, html=None):
    """Sends an email: the plain text, and an HTML version beside it when given. Raises
    RuntimeError when SMTP isn't set up, and the SMTP error when sending fails."""
    cfg = smtp_config()
    if cfg is None:
        raise RuntimeError('SMTP is not configured')
    message = EmailMessage()
    message['From'] = cfg['from']
    message['To'] = to
    message['Subject'] = subject
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype='html')
    _deliver(message, cfg)


def _send_logged(to, subject, body, html=None):
    try:
        send_mail(to, subject, body, html=html)
    except Exception as e:
        logger.warning(f'Could not send the email "{subject}": {e}')


def send_mail_later(to, subject, body, html=None):
    """Sends without waiting: a slow mail server doesn't hold the page up, and how long
    the page takes doesn't tell whether an address has an account. Failures are logged."""
    if not SEND_IN_BACKGROUND:
        _send_logged(to, subject, body, html)
        return
    threading.Thread(target=_send_logged, args=(to, subject, body, html), daemon=True).start()


def account_mail(subject, body, link=None, button=None):
    """An account email's HTML, built from its plain text: the shop's name in the header,
    the subject as heading, and the link as a button."""
    import mail_html
    from i18n import t
    from settings import get_settings
    shop = get_settings()['shop'].get('name') or 'Ownfoil-Plus'
    return mail_html.from_text(shop, subject, body, link, button or t('mail.button_open'),
                               t('mail.fallback'), t('mail.footer', shop=shop))


# --- signed links ---------------------------------------------------------------------

def _serializer(salt):
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=salt)


def _password_fingerprint(user):
    return hashlib.sha256((user.password or '').encode()).hexdigest()[:16]


def verify_token(user):
    return _serializer(VERIFY_SALT).dumps({'u': user.id, 'e': user.pending_email})


def reset_token(user):
    return _serializer(RESET_SALT).dumps({'u': user.id, 'p': _password_fingerprint(user), 'e': user.email})


def _load(token, salt, max_age):
    try:
        return _serializer(salt).loads(token, max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None


def user_from_verify_token(token):
    from db import User, db
    data = _load(token, VERIFY_SALT, VERIFY_MAX_AGE)
    if not isinstance(data, dict):
        return None
    user = db.session.get(User, data.get('u'))
    # Only for the address still waiting for it: once verified (or replaced by another)
    # the link is spent.
    return user if user and user.pending_email and user.pending_email == data.get('e') else None


def user_from_reset_token(token):
    from db import User, db
    data = _load(token, RESET_SALT, RESET_MAX_AGE)
    if not isinstance(data, dict):
        return None
    user = db.session.get(User, data.get('u'))
    if user is None or not user.email or user.email != data.get('e'):
        return None
    return user if _password_fingerprint(user) == data.get('p') else None


# --- Google ---------------------------------------------------------------------------

def google_auth_url(state):
    cfg = google_config()
    return GOOGLE_AUTH_URL + '?' + urlencode({
        'client_id': cfg['client_id'], 'redirect_uri': cfg['redirect_uri'], 'response_type': 'code',
        'scope': 'openid email profile', 'state': state, 'prompt': 'select_account'})


def google_profile(code):
    """Trades the code Google sent back for the user's profile ({sub, email,
    email_verified}), or None. The code goes to Google with the client secret over HTTPS,
    and the profile comes from Google's own userinfo endpoint."""
    cfg = google_config()
    if cfg is None or not code:
        return None
    try:
        token = requests.post(GOOGLE_TOKEN_URL, timeout=GOOGLE_TIMEOUT, data={
            'code': code, 'client_id': cfg['client_id'], 'client_secret': cfg['client_secret'],
            'redirect_uri': cfg['redirect_uri'], 'grant_type': 'authorization_code'})
        token.raise_for_status()
        payload = token.json()
        access = payload.get('access_token') if isinstance(payload, dict) else None
        if not access:
            return None
        info = requests.get(GOOGLE_USERINFO_URL, timeout=GOOGLE_TIMEOUT,
                            headers={'Authorization': f'Bearer {access}'})
        info.raise_for_status()
        profile = info.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f'Google sign-in failed: {e}')
        return None
    if not isinstance(profile, dict) or not profile.get('sub') or not profile.get('email'):
        return None
    return {'sub': str(profile['sub']), 'email': str(profile['email']).strip().lower(),
            'email_verified': profile.get('email_verified') is True}


def new_state():
    return secrets.token_urlsafe(24)


def username_from_email(email, taken):
    """A user name for a Google account, from its email: Tinfoil-safe characters, and a
    number when the name is taken ('gamer', 'gamer2', ...)."""
    base = re.sub(r'[^A-Za-z0-9_.-]', '', email.split('@', 1)[0])[:28] or 'user'
    if len(base) < 3:
        base = (base + 'user')[:28]
    name, n = base, 2
    while taken(name):
        name = f'{base}{n}'
        n += 1
    return name

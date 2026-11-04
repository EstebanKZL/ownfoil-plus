"""Routes for accounts people make themselves (accounts.py): sign up, verify an email,
resend that email, forgot/reset a password, Google sign-in, and the email and password
parts of My account.

Nothing here says whether an email has an account: signing up, resending and forgetting
answer the same either way, and their emails go out in the background so the time taken
doesn't tell either. Each network address gets a few tries per quarter of an hour, and
each email address a few emails per hour, so the forms can't be used to spam a mailbox
or guess accounts.
"""
import logging

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session
from flask_login import current_user, login_required, login_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

import accounts
import auth
from db import User, db
from i18n import t

logger = logging.getLogger('main')

accounts_blueprint = Blueprint('accounts', __name__)

MIN_PASSWORD = 8
TRIES_PER_ADDRESS = (10, 15 * 60)     # per network address and form
MAILS_PER_EMAIL = (3, 3600)           # per email address and form
ACCOUNT_EMAIL_CHANGES = (5, 3600)     # per signed-in user


def _limited(kind, email=None):
    """True when this network address, or this email, used `kind` too often; counts this try."""
    if auth.over_limit(('form', kind, request.remote_addr or ''), *TRIES_PER_ADDRESS):
        return True
    return bool(email) and auth.over_limit(('mail', kind, email), *MAILS_PER_EMAIL)


def _page(template, status=200, **context):
    return render_template(template, title='Account', **context), status


def _message(heading, text, status=200):
    return _page('auth_message.html', status, heading=heading, text=text)


def _verified_owner(email, but=None):
    """The account whose verified email this is, or None. Unverified claims
    (`pending_email`) never count: anyone can type any address."""
    q = User.query.filter(db.func.lower(User.email) == email.lower())
    if but is not None:
        q = q.filter(User.id != but.id)
    return q.first()


def _check_password(password, confirm=None):
    """An error message, or None. The web password is also the shop clients' (Tinfoil,
    Sphaira): the same rules as every account."""
    if confirm is not None and password != confirm:
        return t('signup.passwords_differ')
    if len(password or '') < MIN_PASSWORD:
        return t('signup.password_short', n=MIN_PASSWORD)
    valid, _ = auth.validate_password(password)
    return None if valid else t('signup.password_chars')


def _verification(user):
    link = f'{accounts.public_url()}/verify/{accounts.verify_token(user)}'
    return user.pending_email, t('mail.verify_subject'), t('mail.verify_body', user=user.user, link=link)


@accounts_blueprint.app_context_processor
def inject_auth_options():
    """What the login page offers: sign up (registration open, and email or Google to
    use it), forgot password (needs email), Google (needs its settings). On the
    blueprint, so every app that registers it gets it."""
    email = accounts.email_ready()
    google = accounts.google_config() is not None
    return {'auth_options': {'signup': accounts.registration_open() and (email or google),
                             'forgot': email, 'google': google, 'email': email}}


# --- sign up and verify ----------------------------------------------------------------

@accounts_blueprint.route('/signup', methods=['GET', 'POST'])
def signup():
    if not accounts.registration_open():
        abort(404)
    can_email = accounts.email_ready()
    if request.method == 'GET':
        return _page('signup.html', can_email=can_email, google=accounts.google_config() is not None)
    if not can_email:
        return _page('signup.html', 400, can_email=False, error=t('signup.no_email'))
    username = (request.form.get('user') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    password = request.form.get('password') or ''
    if _limited('signup', email if accounts.valid_email(email) else None):
        return _page('signup.html', 429, can_email=True, error=t('signup.too_many'))
    error = None
    if not accounts.USERNAME_RE.match(username):
        error = t('signup.bad_user')
    elif User.query.filter(db.func.lower(User.user) == username.lower()).first():
        error = t('signup.user_taken')
    elif not accounts.valid_email(email):
        error = t('signup.bad_email')
    else:
        error = _check_password(password, request.form.get('confirm'))
    if error:
        return _page('signup.html', 400, can_email=True, error=error, user=username, email=email)
    checked = _message(t('signup.check_mail_heading'), t('signup.check_mail', email=email))
    owner = _verified_owner(email)
    if owner is not None:
        # The same answer as a new account, and a word to whoever owns the address.
        accounts.send_mail_later(owner.email, t('mail.exists_subject'),
                                 t('mail.exists_body', user=owner.user, link=f'{accounts.public_url()}/forgot'))
        return checked
    user = User(user=username, password=generate_password_hash(password, method='scrypt'), pending_email=email,
                email_verified=False, pending=True, admin_access=False, shop_access=True, backup_access=False)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:          # the same name, a moment ago
        db.session.rollback()
        return _page('signup.html', 400, can_email=True, error=t('signup.user_taken'), user=username, email=email)
    accounts.send_mail_later(*_verification(user))
    logger.info(f'New account {username!r} registered, waiting for its email')
    return checked


@accounts_blueprint.route('/verify/<token>')
def verify(token):
    """Moves the address that waited for this link into `email`. It doesn't sign in: the
    link may have been opened by someone else (a mail scanner, a forwarded email)."""
    user = accounts.user_from_verify_token(token)
    if user is None:
        return _message(t('verify.bad_heading'), t('verify.bad'), 400)
    if _verified_owner(user.pending_email, but=user) is not None:
        user.pending_email = None
        db.session.commit()
        return _message(t('verify.bad_heading'), t('verify.taken'), 400)
    user.email, user.pending_email = user.pending_email, None
    user.email_verified = True
    user.pending = False
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _message(t('verify.bad_heading'), t('verify.taken'), 400)
    return _message(t('verify.ok_heading'), t('verify.ok'))


@accounts_blueprint.route('/verify/resend', methods=['GET', 'POST'])
def resend():
    if request.method == 'GET':
        return _page('auth_email_form.html', mode='resend')
    email = (request.form.get('email') or '').strip().lower()
    if _limited('resend', email if accounts.valid_email(email) else None):
        return _page('auth_email_form.html', 429, mode='resend', error=t('signup.too_many'))
    if email and accounts.email_ready():
        for user in User.query.filter(db.func.lower(User.pending_email) == email).all():
            accounts.send_mail_later(*_verification(user))
    return _message(t('resend.sent_heading'), t('resend.sent'))


# --- forgotten password --------------------------------------------------------------

@accounts_blueprint.route('/forgot', methods=['GET', 'POST'])
def forgot():
    if request.method == 'GET':
        return _page('auth_email_form.html', mode='forgot')
    email = (request.form.get('email') or '').strip().lower()
    if _limited('forgot', email if accounts.valid_email(email) else None):
        return _page('auth_email_form.html', 429, mode='forgot', error=t('signup.too_many'))
    user = _verified_owner(email) if email else None
    if user and user.email_verified and accounts.email_ready():
        link = f'{accounts.public_url()}/reset/{accounts.reset_token(user)}'
        accounts.send_mail_later(user.email, t('mail.reset_subject'), t('mail.reset_body', user=user.user, link=link))
    return _message(t('forgot.sent_heading'), t('forgot.sent'))


@accounts_blueprint.route('/reset/<token>', methods=['GET', 'POST'])
def reset(token):
    user = accounts.user_from_reset_token(token)
    if user is None:
        return _message(t('reset.bad_heading'), t('reset.bad'), 400)
    if request.method == 'GET':
        return _page('auth_reset.html', token=token)
    password = request.form.get('password') or ''
    error = _check_password(password, request.form.get('confirm'))
    if error:
        return _page('auth_reset.html', 400, token=token, error=error)
    user.password = generate_password_hash(password, method='scrypt')
    db.session.commit()
    auth.clear_login_failures(user.user)
    logger.info(f'Password of {user.user!r} reset from an emailed link')
    return _message(t('reset.ok_heading'), t('reset.ok'))


# --- Google -----------------------------------------------------------------------------

@accounts_blueprint.route('/login/google')
def google_start():
    if accounts.google_config() is None:
        abort(404)
    state = accounts.new_state()
    session['google_state'] = state
    session['google_next'] = auth.safe_next_url(request.args.get('next', ''))
    return redirect(accounts.google_auth_url(state))


@accounts_blueprint.route('/login/google/callback')
def google_callback():
    if accounts.google_config() is None:
        abort(404)
    expected = session.pop('google_state', None)
    if not expected or request.args.get('state') != expected:
        return _message(t('google.failed_heading'), t('google.bad_state'), 400)
    profile = accounts.google_profile(request.args.get('code'))
    if profile is None or not profile['email_verified']:
        return _message(t('google.failed_heading'), t('google.failed'), 400)
    user = User.query.filter_by(google_id=profile['sub']).first()
    if user is None:
        # An account with this same verified email is that person's: link it - unless
        # it is already linked to another Google account. An unverified claim on the
        # address (`pending_email`) is never matched: it would hand that account's
        # password-holder the Google owner's sign-in.
        same = _verified_owner(profile['email'])
        if same is not None:
            if same.google_id and same.google_id != profile['sub']:
                return _message(t('google.failed_heading'), t('google.other_linked'), 403)
            same.google_id = profile['sub']
            user = same
        elif accounts.registration_open():
            name = accounts.username_from_email(
                profile['email'], lambda n: User.query.filter(db.func.lower(User.user) == n.lower()).first() is not None)
            user = User(user=name, password=None, email=profile['email'], email_verified=True, pending=False,
                        google_id=profile['sub'], admin_access=False, shop_access=True, backup_access=False)
            db.session.add(user)
            logger.info(f'New account {name!r} registered with Google')
        else:
            return _message(t('google.failed_heading'), t('google.closed'), 403)
    try:
        db.session.commit()
    except IntegrityError:          # the same name or account, a moment ago
        db.session.rollback()
        return _message(t('google.failed_heading'), t('google.failed'), 400)
    login_user(user)
    return redirect(session.pop('google_next', None) or '/')


# --- My account: email and password -------------------------------------------------------

@accounts_blueprint.post('/api/account/email')
@login_required
def account_email():
    """Sets the address waiting for its link; the verified one stays until the link is opened."""
    email = str((request.get_json(silent=True) or {}).get('email') or '').strip().lower()
    if not accounts.valid_email(email):
        return jsonify({'success': False, 'error': 'invalid_email'}), 400
    if not accounts.email_ready():
        return jsonify({'success': False, 'error': 'no_email'}), 400
    if email == (current_user.email or ''):
        return jsonify({'success': True})
    if auth.over_limit(('account_email', current_user.id), *ACCOUNT_EMAIL_CHANGES):
        return jsonify({'success': False, 'error': 'too_many'}), 429
    if _verified_owner(email, but=current_user) is not None:
        return jsonify({'success': False, 'error': 'email_taken'}), 400
    current_user.pending_email = email
    db.session.commit()
    try:
        accounts.send_mail(*_verification(current_user))
    except Exception as e:
        logger.warning(f'Could not send the verification email: {e}')
        return jsonify({'success': False, 'error': 'send_failed'}), 502
    return jsonify({'success': True})


@accounts_blueprint.post('/api/account/password')
@login_required
def account_password():
    data = request.get_json(silent=True) or {}
    current, new = str(data.get('current') or ''), str(data.get('new') or '')
    key = f'password:{current_user.user}'
    if auth.login_locked_for(key):
        return jsonify({'success': False, 'error': 'too_many'}), 429
    # An account made with Google has no password yet: it sets its first one.
    if current_user.password and not check_password_hash(current_user.password, current):
        auth.record_login_failure(key)
        return jsonify({'success': False, 'error': 'wrong_password'}), 400
    error = _check_password(new)
    if error:
        return jsonify({'success': False, 'error': 'bad_password', 'message': error}), 400
    current_user.password = generate_password_hash(new, method='scrypt')
    db.session.commit()
    auth.clear_login_failures(key)
    return jsonify({'success': True})

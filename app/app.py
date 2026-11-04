import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, send_file, Response
from flask_login import LoginManager, login_required
from flask_sock import Sock
from functools import wraps
from file_watcher import Watcher
import threading
import logging
import sys
import copy
import flask.cli
flask.cli.show_server_banner = lambda *args: None
from constants import *
from settings import *
from db import *
from auth import *
from utils import *
from library import *
import json
import tasks as tasks_mod
import yaml
from i18n import register_i18n
import firmware
import discover
import vault
import accounts
from accounts_views import accounts_blueprint
from avatars import avatars_blueprint
import avatars as avatars_mod
import realtime
import titledb
import discovery
import backups
import titles as titles_lib
import uploads
import media
import metrics
import nav_counts
import notifications
import re
import shutil
import os
import secrets
from i18n import SUPPORTED_LANGUAGES, current_language, t
from clients import CyberFoilClient, TinfoilClient, SphairaClient

def init():
    global watcher
    global watcher_thread
    # Create the file watcher and register callbacks BEFORE starting the observer
    logger.info('Initializing File Watcher...')
    watcher = Watcher(on_library_change)
    watcher.add_file_callback(CONFIG_FILE, on_settings_change)
    watcher_thread = threading.Thread(target=watcher.run)
    watcher_thread.daemon = True
    watcher_thread.start()

    # Start UDP discovery for clients on the LAN
    discovery.reconcile()

    # init libraries
    library_paths = get_library_paths()
    init_libraries(app, watcher, library_paths)

    # Enqueue initial titledb update (re-enqueues itself on completion)
    with app.app_context():
        tasks_mod.enqueue_task('startup')

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

## Global variables
watcher = None
watcher_thread = None
pool = None  # Set by entrypoint after WorkerPool is created

# Configure logging
formatter = ColoredFormatter(LOG_FORMAT, datefmt=LOG_DATEFMT)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[handler]
)

# Create main logger
logger = logging.getLogger('main')
logger.setLevel(logging.DEBUG)

# Apply filter to hide date from http access logs
logging.getLogger('werkzeug').addFilter(FilterRemoveDateFromWerkzeugLogs())

# Suppress specific Alembic INFO logs
logging.getLogger('alembic.runtime.migration').setLevel(logging.WARNING)

@login_manager.user_loader
def load_user(user_id):
    # since the user_id is just the primary key of our user table, use it in the query for the user
    return User.query.filter_by(id=user_id).first()

def on_settings_change():
    """Settings file changed: refresh cache, scale workers, and re-apply watcher config."""
    settings = get_settings()
    if pool is not None:
        desired = max(1, settings.get('worker', {}).get('count', 1))
        if desired != pool.count:
            logger.info(f'Settings changed: scaling workers from {pool.count} to {desired}')
            pool.scale(desired)
    discovery.reconcile()
    if watcher is not None:
        # Reconcile off this thread: this callback runs inside the native observer's dispatch,
        # which holds the observer lock that schedule/unschedule also need.
        threading.Thread(target=watcher.reconcile, daemon=True).start()

def on_library_change(events):
    """Enqueue individual tasks per file event, skipping ignored events."""
    with app.app_context():
        for event in events:
            if event.type == 'deleted':
                # Ignore marks are written before our own removes, so they are checked ahead of
                # the temp mark: a converted source carries both, and a mark left unpopped leaks.
                if pop_ignored_event(src_path=event.src_path, dest_path=''):
                    continue
                # Also check if this delete is part of a move (dest_path != '')
                if pop_ignored_event(src_path=event.src_path):
                    continue
                # A path a task is writing is not a library file - unless it is a committed row,
                # in which case the file really is gone and has to leave the library.
                if is_temp_file(event.src_path) and not file_exists_in_db(event.src_path):
                    continue
                tasks_mod.enqueue_task('handle_file_deleted', {
                    'filepath': event.src_path,
                })
                continue
            if is_temp_file(event.src_path) or (
                    event.dest_path and is_temp_file(event.dest_path)):
                continue
            if event.type == 'moved':
                if pop_ignored_event(src_path=event.src_path, dest_path=event.dest_path):
                    continue
                tasks_mod.enqueue_task('handle_file_moved', {
                    'library_path': event.directory,
                    'src_path': event.src_path,
                    'dest_path': event.dest_path,
                })
            elif event.type == 'created':
                if pop_ignored_event(dest_path=event.src_path):
                    continue
                tasks_mod.enqueue_task('handle_file_added', {
                    'library_path': event.directory,
                    'filepath': event.src_path,
                })
            elif event.type == 'modified':
                tasks_mod.enqueue_task('handle_file_added', {
                    'library_path': event.directory,
                    'filepath': event.src_path,
                })
            elif event.type == 'dir_deleted':
                # A folder was moved out/removed; its files are gone, delete them by path prefix.
                tasks_mod.enqueue_task('handle_dir_deleted', {'dirpath': event.src_path})

def load_or_create_secret_key():
    """The key that signs session and remember-me cookies. It used to be a constant
    in this file - public on GitHub, so anyone could forge a session cookie for any
    user id on any install. Now: OWNFOIL_SECRET_KEY if set, else a random key
    generated once and kept in CONFIG_DIR, so sessions survive restarts."""
    # SECRET_KEY is the common name for it; OWNFOIL_SECRET_KEY wins when both are set.
    env_key = os.environ.get('OWNFOIL_SECRET_KEY') or os.environ.get('SECRET_KEY')
    if env_key:
        return env_key
    os.makedirs(CONFIG_DIR, exist_ok=True)
    try:
        with open(SECRET_KEY_FILE, 'r') as f:
            key = f.read().strip()
        if key:
            return key
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32)
    try:
        # O_EXCL: if another process won the race, use its key instead of ours.
        fd = os.open(SECRET_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(SECRET_KEY_FILE, 'r') as f:
            return f.read().strip()
    with os.fdopen(fd, 'w') as f:
        f.write(key)
    logger.info('Generated a new secret key for session cookies.')
    return key

def create_app(db_uri=None):
    app = Flask(__name__)
    app.url_map.strict_slashes = False  # Disable automatic trailing slash redirects globally, needed for Sphaira
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri or OWNFOIL_DB
    app.config['SECRET_KEY'] = load_or_create_secret_key()
    # Lax keeps the session/remember cookies off cross-site POSTs (CSRF) while still
    # sending them on normal top-level navigation. Not Secure: most installs are plain
    # HTTP on a LAN.
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    app.register_blueprint(auth_blueprint)
    app.register_blueprint(accounts_blueprint)
    app.register_blueprint(avatars_blueprint)
    register_i18n(app)

    return app

# Create app
app = create_app()

# Realtime WebSocket. ping_interval keeps idle sockets alive through proxies and lets
# the server notice a peer that went away without closing.
app.config['SOCK_SERVER_OPTIONS'] = {'ping_interval': 25}
sock = Sock(app)
realtime.init_app(app)
import task_events  # noqa: F401 — registers the tasks/workers topics


@sock.route('/api/ws')
def realtime_ws(ws):
    """Multiplexed realtime stream: /api/ws?topics=tasks,workers"""
    requested = [t for t in request.args.get('topics', '').split(',') if t]
    realtime.serve(ws, requested)

# Add proper Seek support to Range requests 
from werkzeug.wsgi import FileWrapper as WerkzeugFileWrapper

@app.before_request
def use_seekable_file_wrapper_for_range_requests():
    """
    Gunicorn's WSGI FileWrapper does not expose seekable(), seek()
    and tell(). Werkzeug therefore handles Range requests by reading
    and discarding the file from the beginning.

    Use Werkzeug's seekable wrapper for Range requests.
    """
    if request.headers.get("Range"):
        request.environ["wsgi.file_wrapper"] = WerkzeugFileWrapper


# List of supported client classes
SUPPORTED_CLIENTS = [CyberFoilClient, TinfoilClient, SphairaClient]

def get_client_for_request(request):
    """Identify and return the appropriate client for the request, or None if no client matches."""
    for client_class in SUPPORTED_CLIENTS:
        if client_class.identify_client(request):
            return client_class(get_settings())
    return None

def _console_request(request):
    """A call from a console's shop client: one it identifies itself as, or a Basic Auth
    caller of the shop's own routes (browsers sign in with a session, never Basic Auth;
    the save vault at /dav has its own switch)."""
    if get_client_for_request(request) is not None:
        return True
    path = request.path
    return request.authorization is not None and (
        path == '/' or path == '/api/graphql' or path.startswith('/api/get_game/'))

@app.before_request
def shop_closed():
    """The Store switch (Services): with the shop off, consoles get "closed"."""
    if get_settings()['shop'].get('enabled', True) or not _console_request(request):
        return None
    client = get_client_for_request(request)
    message = 'The shop is closed for now.'
    if client is not None and request.path == '/' and request.method != 'OPTIONS':
        # In the client's own format, as a disabled client is told: that's what it shows.
        return client.error_response(message)
    return jsonify({'error': message}), 503

def download_caller(request):
    """(user, client) for the download history: the Basic Auth user a console sends,
    else the signed-in browser's; the client from the same identification the shop
    routes use, else 'web' for a browser session and 'other' for anything else."""
    user = None
    if request.authorization and request.authorization.username:
        user = request.authorization.username
    elif current_user.is_authenticated:
        user = current_user.user
    for client_class in SUPPORTED_CLIENTS:
        if client_class.identify_client(request):
            return user, client_class.CLIENT_NAME.lower()
    return user, ('web' if current_user.is_authenticated else 'other')

def file_access(f):
    """Decorator for file-serving endpoints: the logged-in browser's session cookie,
    or HTTP Basic Auth for a console client (Tinfoil, Sphaira) that carries no
    session - gated the same way GraphQL is (see auth.resolve_shop_caller), and a
    public shop needs neither.

    Session auth matters here for more than consistency: the web UI's own game
    cards/banners now hit `/api/media/...` directly as plain `<img src>` requests
    (see index.html), which send cookies, never an Authorization header - Basic-Auth-
    only left every one of those 401ing on a private shop even for a signed-in admin.
    """
    @wraps(f)
    def _file_access(*args, **kwargs):
        success, error, user = resolve_shop_caller(request)
        if not success:
            response = jsonify({'error': error})
            if user is None:
                response.headers['WWW-Authenticate'] = 'Basic realm="Ownfoil-Plus"'
            return response, (403 if user else 401)
        return f(*args, **kwargs)
    return _file_access

def library_page_context():
    """What the Library and the game page tell their JS about the viewer: the same
    rules the routes they call enforce, so buttons only show where they work."""
    settings = get_settings()
    # Mirrors access_required's own rule: with no admin account created yet, auth is
    # effectively off and everyone is treated as an admin - the List view's download
    # button should behave the same way the route it calls does.
    is_admin = (not admin_account_created()) or (
        current_user.is_authenticated and current_user.has_access('admin'))
    # Same leniency during the bootstrap phase, and an admin always qualifies too
    # (an admin account always carries shop access - see signup_post) - but this is
    # also true for a plain authenticated user who only has shop access, which
    # is_admin alone would miss. The download route itself checks the exact same
    # thing server-side, so this only controls whether the button is worth showing.
    is_shop = is_admin or (
        current_user.is_authenticated and current_user.has_access('shop'))
    # A user's own choices (My account) win over the server's; a visitor of a public
    # shop gets the server's.
    show_background = settings['library']['management'].get('organizer', {})         .get('show_background_image', True)
    console_firmware = None
    if current_user.is_authenticated:
        if current_user.show_background_image is not None:
            show_background = current_user.show_background_image
        console_firmware = current_user.console_firmware
    return dict(
        admin_account_created=admin_account_created(), is_admin=is_admin, is_shop=is_shop,
        web_downloads_enabled=settings['library']['management'].get('web_downloads', {}).get('enabled', False),
        show_game_background_image=show_background, console_firmware=console_firmware,
        can_see_saves=current_user.is_authenticated and vault.may_use(current_user),
    )

def access_shop():
    return render_template('index.html', title='Library', **library_page_context())

@access_required('shop')
def access_shop_auth():
    return access_shop()

_TITLE_ID_RE = re.compile(r'[0-9A-F]{16}')

def render_game_page(title_id):
    title_id = title_id.upper()
    valid = bool(_TITLE_ID_RE.fullmatch(title_id))
    html = render_template('game.html', title='Game', game_title_id=title_id if valid else None,
                           **library_page_context())
    return html, (200 if valid else 404)

@access_required('shop')
def game_page_auth(title_id):
    return render_game_page(title_id)

@app.route('/game/<title_id>')
def game_page(title_id):
    """One game's page (templates/game.html). Same access as the Library: anyone on a
    public shop, otherwise a signed-in user with shop access. A malformed id renders
    the page's not-found state with a 404; a well-formed but unknown one is found out
    by the page's own GraphQL query."""
    if not get_settings()['shop']['public']:
        return game_page_auth(title_id)
    return render_game_page(title_id)

def shop_handshake():
    """Server identity and per-caller capabilities: the OPTIONS handshake of the
    Ownfoil API. Sphaira's native "Ownfoil" menu sends this before anything else -
    once discovery (or a manually entered address) points it at a server, it does
    an OPTIONS / here to learn the server's name, uid and protocol version and
    decide whether it can talk to it, and only then goes on to the GraphQL API.
    Flask auto-answers an unclaimed OPTIONS with an empty 200, which satisfies no
    client expecting this body - the route must claim the method itself."""
    if not get_settings()['shop']['public']:
        auth_success, auth_error, user = basic_auth(request)
        if not auth_success:
            response = jsonify({'error': auth_error})
            response.headers['WWW-Authenticate'] = 'Basic realm="Ownfoil-Plus"'
            return response, 401
        if not user.has_shop_access():
            return jsonify({'error': f'User "{user.user}" does not have access to the shop.'}), 403

    settings = get_settings()
    return jsonify({
        'uid': get_server_uid(),
        'name': settings['shop']['name'],
        'version': discovery._app_version(),
        'protocol_version': API_PROTOCOL_VERSION,
        'motd': settings['shop']['motd'],
        'public': settings['shop']['public'],
        # No local address: only discovery, on the client's own network, gives one.
        'remote': settings['shop']['host'],
        'features': {
            # Reached only past the access gate above, and downloads support Range.
            'shop': True,
            'resumable_download': True,
            'dumps_upload': False,      # needs the dumps_access permission and upload_library_id
            'save_backup': False,       # becomes user.has_backup_access() once saves are served
            'resumable_upload': False,  # becomes True with the tus upload endpoints
        },
    })

@app.route('/', defaults={'path': ''}, methods=['GET', 'OPTIONS'])
@app.route('/<path:path>')
def index(path=None):
    """Main shop endpoint routing to either client-specific shop or web browser UI."""
    # The handshake answers for itself, before any client identification happens.
    if request.method == 'OPTIONS':
        return shop_handshake()

    # Check if this is a client request
    client = get_client_for_request(request)

    if client:
        # Check if client is enabled
        client_name = client.CLIENT_NAME.lower()
        client_settings = get_settings().get('shop', {}).get('clients', {}).get(client_name, {})
        if not client_settings.get('enabled', False):
            logger.warning(f"{client.CLIENT_NAME} connection from {request.remote_addr} - Client is disabled")
            return client.error_response(f"Shop access from {client.CLIENT_NAME} is disabled.")

        # Handle client request
        logger.info(f"{client.CLIENT_NAME} connection from {request.remote_addr}")
        return client.handle_request(request)

    # Browser request - serve web UI
    elif path:
        return redirect('/')

    if not get_settings()['shop']['public']:
        return access_shop_auth()
    return access_shop()

@app.context_processor
def inject_shop_name():
    """Templates show the configured shop name, not the product name."""
    return {'shop_name': get_settings()['shop'].get('name') or 'Ownfoil-Plus'}

@app.context_processor
def inject_default_style():
    """base.html renders the admin's color style on <html>, before any JS runs;
    theme.js then applies this browser's own choice, if it made one."""
    return {'default_style': get_default_style()}

@app.context_processor
def inject_nav():
    """Who sees what in nav.html. Mirrors access_required: with no admin account
    created yet, auth is effectively off and everyone is treated as an admin. Only an
    admin's pages pay for the counters."""
    nav_admin = (not admin_account_created()) or (
        current_user.is_authenticated and bool(current_user.is_admin))
    nav_shop = nav_admin or (current_user.is_authenticated and bool(current_user.has_shop_access()))
    return {'nav_admin': nav_admin, 'nav_shop': nav_shop,
            'nav_counts': nav_counts.get_nav_counts() if nav_admin else {}}

# --- Installable app (PWA) ---
# Both live at the site root: a service worker only controls pages under its own path,
# and the manifest carries the shop's own name. No login needed - like the favicon,
# they hold nothing private, and the browser fetches them without credentials.

@app.route('/manifest.webmanifest')
def web_manifest():
    name = get_settings()['shop'].get('name') or 'Ownfoil-Plus'
    icons = []
    for size, path in ((192, 'favicon/web-app-manifest-192x192.png'),
                       (512, 'favicon/web-app-manifest-512x512.png')):
        url = url_for('static', filename=path)
        icons.append({'src': url, 'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': 'any'})
        icons.append({'src': url, 'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': 'maskable'})
    manifest = {
        'id': '/', 'name': name, 'short_name': name[:12], 'start_url': '/', 'scope': '/',
        'display': 'standalone', 'theme_color': '#212529', 'background_color': '#212529',
        'description': 'Nintendo Switch library and shop', 'icons': icons,
        'shortcuts': [
            {'name': t('nav.library'), 'url': '/'},
            {'name': t('dash.title'), 'url': '/admin'},
        ],
    }
    response = Response(json.dumps(manifest), mimetype='application/manifest+json')
    response.cache_control.no_cache = True
    return response

@app.route('/sw.js')
def service_worker():
    js = render_template('sw.js', version=discovery._app_version(),
                         precache=[url_for('static', filename=f) for f in (
                             'vendor/bootstrap/bootstrap.min.css',
                             'vendor/bootstrap/bootstrap.bundle.min.js',
                             'vendor/jquery/jquery-3.6.0.min.js',
                             'vendor/bootstrap-icons/bootstrap-icons.min.css',
                             'vendor/bootstrap-icons/fonts/bootstrap-icons.woff2',
                             'css/tokens.css', 'vendor/inter/InterVariable.woff2',
                             'style.css', 'js/pwa.js', 'logo/logo.svg', 'favicon/favicon.ico',
                         )] + ['/offline'])
    response = Response(js, mimetype='application/javascript')
    # Browsers check for a new worker on every navigation; never let a cache answer.
    response.cache_control.no_cache = True
    response.headers['Service-Worker-Allowed'] = '/'
    return response

@app.route('/offline')
def offline_page():
    return render_template('offline.html', title='Offline')

@app.route('/api/health')
def health():
    """Liveness/readiness probe for Docker's HEALTHCHECK, Kubernetes or an uptime
    monitor. Unauthenticated on purpose, so it says nothing beyond "up" and whether
    the database answers."""
    try:
        db.session.execute(db.text('SELECT 1'))
    except Exception as e:
        logger.error(f'Health check: database unreachable: {e}')
        return jsonify({'status': 'error', 'database': 'unreachable'}), 503
    return jsonify({'status': 'ok', 'database': 'ok'})

@app.route('/admin')
@access_required('admin')
def admin_page():
    return render_template('dashboard.html', title='Dashboard',
                           admin_account_created=admin_account_created())

@app.route('/admin/settings')
@access_required('admin')
def settings_page():
    with open(os.path.join(TITLEDB_DIR, 'languages.json')) as f:
        languages = json.load(f)
        languages = dict(sorted(languages.items()))
    return render_template(
        'settings.html',
        title='Settings',
        languages_from_titledb=languages,
        admin_account_created=admin_account_created())

# Services: each one's switch in settings.yaml, and the Settings section that sets it up.
SERVICES = (
    ('registration', ('registration', 'enabled'), '/admin/settings#Registration'),
    ('shop', ('shop', 'enabled'), '/admin/settings#Shop'),
    ('maintenance', ('maintenance', 'enabled'), '/admin/settings#Maintenance'),
    ('notifications', ('notifications', 'enabled'), '/admin/settings#Notifications'),
    ('vault', ('vault', 'enabled'), '/admin/settings#Vault'),
    ('discovery', ('services', 'discovery', 'enabled'), '/admin/services#servicesDiscovery'),
)

# Each service's card: icon, name and description (spelled out, so unused strings show).
SERVICE_CARDS = {
    'registration': ('bi-person-plus', 'services.name_registration', 'services.desc_registration'),
    'shop': ('bi-shop', 'services.name_shop', 'services.desc_shop'),
    'maintenance': ('bi-wrench-adjustable', 'services.name_maintenance', 'services.desc_maintenance'),
    'notifications': ('bi-bell', 'services.name_notifications', 'services.desc_notifications'),
    'vault': ('bi-safe', 'services.name_vault', 'services.desc_vault'),
    'discovery': ('bi-wifi', 'services.name_discovery', 'services.desc_discovery'),
}

def _service_state(settings, path):
    value = settings
    for key in path:
        value = (value or {}).get(key)
    return bool(value)

@app.get('/api/services')
@access_required('admin')
def services_api():
    settings = get_settings()
    return jsonify({'services': [{'id': name, 'enabled': _service_state(settings, path), 'settings': link}
                                 for name, path, link in SERVICES]})

@app.post('/api/services/<name>')
@access_required('admin')
def service_switch_api(name):
    """Turns one service on or off - the same switch its Settings section sets."""
    entry = next((s for s in SERVICES if s[0] == name), None)
    if entry is None:
        return jsonify({'success': False, 'error': 'unknown_service'}), 404
    enabled = bool((request.get_json(silent=True) or {}).get('enabled'))
    set_service_enabled(entry[1], enabled)
    if name == 'discovery':
        discovery.reconcile()
    if name == 'maintenance':
        tasks_mod.reschedule_maintenance()
    logger.info(f"Service {name} turned {'on' if enabled else 'off'} by {current_user.user}")
    return jsonify({'success': True, 'enabled': _service_state(get_settings(), entry[1])})

@app.route('/admin/services')
@access_required('admin')
def services_page():
    settings = get_settings()
    services = [{'id': name, 'enabled': _service_state(settings, path), 'settings': link,
                 'icon': SERVICE_CARDS[name][0], 'name': t(SERVICE_CARDS[name][1]),
                 'desc': t(SERVICE_CARDS[name][2])} for name, path, link in SERVICES]
    return render_template(
        'services.html',
        title='Services',
        services=services,
        discovery_port=DISCOVERY_PORT,
        admin_account_created=admin_account_created())

@app.route('/admin/files')
@access_required('admin')
def files_page():
    from constants import COMPRESS_EXT
    from containers.verification import VERIFY_EXT
    return render_template('files.html', title='Files',
                           keys_valid=bool(load_keys()[0]),
                           verify_ext=sorted(VERIFY_EXT),
                           compress_ext=sorted(COMPRESS_EXT),
                           management=get_settings()['library']['management'],
                           admin_account_created=admin_account_created())

@app.route('/admin/tasks')
@access_required('admin')
def tasks_page():
    import task_events
    return render_template('tasks.html', title='Tasks',
                           max_tasks=task_events.MAX_TASKS,
                           admin_account_created=admin_account_created())

@app.route('/admin/stats')
@access_required('admin')
def stats_page():
    return render_template('stats.html', title='Stats',
                           admin_account_created=admin_account_created())

@app.delete('/api/tasks/history')
@access_required('admin')
def clear_task_history_api():
    """Tasks page > History > trash button. Only the log of finished operations;
    queued, running and failed tasks are untouched."""
    deleted = TaskHistory.query.delete()
    db.session.commit()
    logger.info(f'Task history cleared ({deleted} entries).')
    return jsonify({'success': True, 'deleted': deleted})

# --- Prometheus metrics (see metrics.py) ---

@app.route('/metrics')
def prometheus_metrics():
    """Admin credentials (Basic Auth for a scraper, or a session), or the
    OWNFOIL_METRICS_TOKEN bearer token. Open while no admin account exists, like
    every other admin page."""
    token = os.environ.get('OWNFOIL_METRICS_TOKEN')
    authorized = not admin_account_created()
    header = request.headers.get('Authorization', '')
    if not authorized and token and header.startswith('Bearer '):
        authorized = secrets.compare_digest(header[7:].strip(), token)
    if not authorized and current_user.is_authenticated:
        authorized = current_user.has_access('admin')
    if not authorized and request.authorization:
        ok, _, user = basic_auth(request)
        authorized = ok and user.has_access('admin')
    if not authorized:
        response = Response('Unauthorized\n', 401, mimetype='text/plain')
        response.headers['WWW-Authenticate'] = 'Basic realm="Ownfoil-Plus metrics"'
        return response
    body = metrics.render_metrics(db, get_settings(), discovery._app_version(),
                                  get_library_paths(), backups.list_backups())
    return Response(body, mimetype='text/plain; version=0.0.4; charset=utf-8')

# --- Global search (Ctrl+K, see static/js/search.js) ---

@app.get('/api/search')
@access_required('shop')
def search_api():
    """Games in the library by name or title ID, and - for an admin - files by name.
    Pages and settings sections are matched in the browser (nav.html lists them)."""
    from sqlalchemy import text
    query = (request.args.get('q') or '').strip()
    if len(query) < 2:
        return jsonify({'titles': [], 'files': []})
    pattern = f'%{query}%'
    titles = [{'title_id': title_id, 'name': name or title_id}
              for title_id, name in db.session.execute(text(
                  "SELECT t.title_id, td.name FROM main.titles t "
                  "LEFT JOIN titledb.titles td ON td.id = t.title_id "
                  "WHERE t.have_base = 1 AND (td.name LIKE :p COLLATE NOCASE OR t.title_id LIKE :p COLLATE NOCASE) "
                  "ORDER BY td.name COLLATE NOCASE LIMIT 8"), {'p': pattern})]
    files = []
    is_admin = (not admin_account_created()) or current_user.has_access('admin')
    if is_admin:
        files = [{'id': f.id, 'filename': f.filename, 'size': f.size}
                 for f in Files.query.filter(Files.filename.ilike(pattern))
                 .order_by(Files.filename).limit(6)]
    return jsonify({'titles': titles, 'files': files})

# --- Dashboard (/admin) ---

@app.get('/api/dashboard')
@access_required('admin')
def dashboard_api():
    """Everything the dashboard shows, in one round trip. Plain aggregate SQL: this
    is the admin landing page, so it must stay fast on a library of thousands."""
    from sqlalchemy import text
    from containers.verification import status_of, STATUS_CORRUPT
    offset = tasks_mod.utc_offset()

    files_count, files_size, identified = db.session.execute(text(
        "SELECT COUNT(*), COALESCE(SUM(size), 0), COALESCE(SUM(identified), 0) FROM files")).first()
    owned, complete, up_to_date = db.session.execute(text(
        "SELECT COUNT(*), COALESCE(SUM(complete), 0), COALESCE(SUM(up_to_date), 0) "
        "FROM main.titles WHERE have_base = 1")).first()
    corrupt = sum(int(count) for sig, hashed, modified, count in db.session.execute(text(
        "SELECT signature_valid, hash_valid, hash_modified, COUNT(*) FROM files GROUP BY 1, 2, 3"))
        if status_of(sig, hashed, modified) == STATUS_CORRUPT)
    duplicates = db.session.execute(text(
        "SELECT COUNT(*) FROM (SELECT app_id FROM app_files GROUP BY app_id HAVING COUNT(*) > 1)")).scalar()
    tasks_by_status = dict(db.session.execute(text(
        "SELECT status, COUNT(*) FROM tasks WHERE run_after IS NULL OR status != 'pending' "
        "GROUP BY status")).all())

    storage = []
    for path in get_library_paths():
        try:
            usage = shutil.disk_usage(path)
            storage.append({'path': path, 'online': True, 'total': usage.total,
                            'used': usage.used, 'free': usage.free})
        except OSError:
            storage.append({'path': path, 'online': False})

    since = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    downloads_week = DownloadEvent.query.filter(DownloadEvent.downloaded_at >= since).count()

    def name_of(title_id):
        name = (titles_lib.get_game_info(title_id) or {}).get('name') if title_id else None
        return name if name and name != 'Unrecognized' else title_id

    recent_files = []
    # 30 each: the dashboard shows 10 and scrolls the rest.
    for f in Files.query.filter(Files.identified.is_(True)).order_by(Files.added_at.desc()).limit(30):
        app_row = f.apps[0] if f.apps else None
        title_id = app_row.title.title_id if app_row else None
        recent_files.append({
            'id': f.id, 'filename': f.filename, 'size': f.size, 'title_id': title_id,
            'name': name_of(app_row.app_id if app_row and app_row.app_type == APP_TYPE_DLC else title_id),
            'app_type': 'MULTI' if f.multicontent else (app_row.app_type if app_row else None),
            'version': app_row.app_version if app_row else None,
            'added_at': (f.added_at + offset).isoformat(timespec='minutes') if f.added_at else None,
        })

    recent_downloads = [{
        'name': name_of(e.title_id) or e.filename, 'filename': e.filename, 'user': e.user,
        'client': e.client, 'downloaded_at': (e.downloaded_at + offset).isoformat(timespec='minutes'),
        'title_id': e.title_id,   # the Dashboard links each row to its game page
    } for e in DownloadEvent.query.order_by(DownloadEvent.downloaded_at.desc()).limit(30)]

    settings = get_settings()
    backup_list = backups.list_backups()
    valid_keys = load_keys()[0]
    return jsonify({
        'library': {'files': int(files_count), 'size': int(files_size),
                    'unidentified': int(files_count) - int(identified),
                    'owned_titles': int(owned), 'complete_titles': int(complete),
                    'up_to_date_titles': int(up_to_date), 'corrupt': corrupt,
                    'duplicates': int(duplicates or 0)},
        'storage': storage,
        'tasks': {'running': int(tasks_by_status.get('running', 0)),
                  'pending': int(tasks_by_status.get('pending', 0))
                             + int(tasks_by_status.get('waiting_for_children', 0)),
                  'failed': int(tasks_by_status.get('failed', 0))},
        'downloads_week': downloads_week,
        'recent_files': recent_files,
        'recent_downloads': recent_downloads,
        'maintenance': {'enabled': settings['maintenance']['enabled'],
                        'next_run': _next_maintenance_run_local(),
                        'last_backup': backup_list[0]['created'] if backup_list else None},
        'keys_valid': bool(valid_keys),
        'notifications_enabled': bool(settings['notifications']['enabled']),
        'shop_public': bool(settings['shop']['public']),
    })

# --- Resumable uploads (Files page) ---
UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024

def _upload_error(e):
    return jsonify({'success': False, 'error': e.code, 'message': str(e), **e.extra}), e.status

@app.get('/api/uploads')
@access_required('admin')
def list_uploads_api():
    return jsonify({'uploads': uploads.list_sessions(), 'libraries': get_library_paths(),
                    'chunk_size': UPLOAD_CHUNK_SIZE})

@app.post('/api/uploads')
@access_required('admin')
def start_upload_api():
    data = request.json or {}
    try:
        state = uploads.start(data.get('library'), data.get('filename'), data.get('size'),
                              get_library_paths())
    except uploads.UploadError as e:
        return _upload_error(e)
    return jsonify({'success': True, **state})

@app.get('/api/uploads/<upload_id>')
@access_required('admin')
def upload_status_api(upload_id):
    try:
        return jsonify({'success': True, **uploads.status(upload_id)})
    except uploads.UploadError as e:
        return _upload_error(e)

@app.patch('/api/uploads/<upload_id>')
@access_required('admin')
def upload_chunk_api(upload_id):
    """One chunk: the raw body, appended at the `Upload-Offset` header's position."""
    try:
        offset = int(request.headers.get('Upload-Offset', ''))
    except ValueError:
        return jsonify({'success': False, 'error': 'bad_offset', 'message': 'Upload-Offset header required'}), 400
    try:
        state, finished = uploads.append(upload_id, offset, request.stream, request.content_length)
    except uploads.UploadError as e:
        return _upload_error(e)
    if finished:
        # The watcher sees the rename too; this covers it being off (duplicates dedup).
        tasks_mod.enqueue_task('add_file', {'library_path': state['library'], 'filepath': finished})
    return jsonify({'success': True, **state})

@app.delete('/api/uploads/<upload_id>')
@access_required('admin')
def cancel_upload_api(upload_id):
    try:
        uploads.cancel(upload_id)
    except uploads.UploadError as e:
        return _upload_error(e)
    return jsonify({'success': True})

@app.get('/api/stats/downloads')
@access_required('admin')
def download_stats_api():
    """Downloads over the last `days` (default 30, max 365): per-day counts in the
    server's local time, top titles, per-user and per-client counts, plus the most
    recent downloads and all-time totals."""
    try:
        days = min(max(int(request.args.get('days', 30)), 1), DOWNLOAD_HISTORY_DAYS)
    except ValueError:
        days = 30
    offset = tasks_mod.utc_offset()
    today = (datetime.datetime.utcnow() + offset).date()
    first_day = today - datetime.timedelta(days=days - 1)
    since_utc = datetime.datetime.combine(first_day, datetime.time()) - offset

    events = (DownloadEvent.query.filter(DownloadEvent.downloaded_at >= since_utc)
              .order_by(DownloadEvent.downloaded_at.desc()).all())
    by_day = {first_day + datetime.timedelta(days=n): 0 for n in range(days)}
    titles, users, clients = {}, {}, {}
    total_bytes = 0
    for e in events:
        by_day[(e.downloaded_at + offset).date()] = by_day.get((e.downloaded_at + offset).date(), 0) + 1
        if e.title_id:
            titles[e.title_id] = titles.get(e.title_id, 0) + 1
        users[e.user or ''] = users.get(e.user or '', 0) + 1
        clients[e.client] = clients.get(e.client, 0) + 1
        total_bytes += e.size or 0

    def title_name(title_id):
        name = (titles_lib.get_game_info(title_id) or {}).get('name')
        return name if name and name != 'Unrecognized' else title_id

    def ranked(counts, limit=None):
        items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return items[:limit] if limit else items

    recent = events[:50]
    from avatars import avatar_url
    pictures = {u.user: avatar_url(u) for u in User.query.filter(User.user.in_(list(users))).all()}
    return jsonify({
        'days': days,
        'total': len(events),
        'total_bytes': total_bytes,
        'all_time': DownloadEvent.query.count(),
        'by_day': [{'date': d.isoformat(), 'count': c} for d, c in sorted(by_day.items())],
        'top_titles': [{'title_id': t, 'name': title_name(t), 'count': c} for t, c in ranked(titles, 50)],
        'by_user': [{'user': u or None, 'count': c, 'avatar_url': pictures.get(u)} for u, c in ranked(users)],
        'by_client': [{'client': cl, 'count': c} for cl, c in ranked(clients)],
        'recent': [{
            'downloaded_at': (e.downloaded_at + offset).isoformat(timespec='seconds'),
            'filename': e.filename, 'title_id': e.title_id,
            'name': title_name(e.title_id) if e.title_id else None,
            'app_type': e.app_type, 'app_version': e.app_version, 'size': e.size,
            'user': e.user, 'user_avatar': pictures.get(e.user), 'client': e.client, 'address': e.address,
        } for e in recent],
    })

@app.delete('/api/stats/downloads')
@access_required('admin')
def clear_download_history_api():
    deleted = DownloadEvent.query.delete()
    db.session.commit()
    logger.info(f'Download history cleared ({deleted} entries).')
    return jsonify({'success': True, 'deleted': deleted})

@app.route('/account')
@login_required
def account_page():
    """My account: the signed-in user's own preferences (any user, admin or not)."""
    server_background = get_settings()['library']['management'].get('organizer', {})         .get('show_background_image', True)
    return render_template('account.html', title='Account', server_background=server_background,
                           can_use_vault=vault.may_use(current_user), vault_on=vault.enabled(),
                           avatar_gallery=avatars_mod.GALLERY)

@app.route('/api/account/vault', methods=['GET', 'POST'])
@login_required
def account_vault_api():
    """The signed-in user's own vault password for JKSV (kept hashed, never sent back) -
    for users with the Backup permission and admins. JKSV signs in with the web user name
    and this password."""
    if not vault.may_use(current_user):
        return jsonify({'success': False, 'error': 'no_access'}), 403
    if request.method == 'GET':
        return jsonify({'enabled': vault.enabled(), 'password_set': bool(current_user.vault_password),
                        'username': current_user.user})
    password = str((request.get_json(silent=True) or {}).get('password') or '')
    if len(password) < VAULT_MIN_PASSWORD:
        return jsonify({'success': False, 'error': 'password'}), 400
    current_user.vault_password = generate_password_hash(password)
    db.session.commit()
    vault.clear_auth_cache()
    return jsonify({'success': True})

_BACKGROUND_CHOICES = {'default': None, 'on': True, 'off': False}

@app.post('/api/account')
@login_required
def account_api():
    """Saves the signed-in user's console firmware (as 23.0.1, empty to clear) and
    Library background choice ("default" follows the server's setting)."""
    data = request.get_json(silent=True) or {}
    console_firmware = str(data.get('console_firmware') or '').strip()
    if console_firmware and firmware.parse_firmware(console_firmware) is None:
        return jsonify({'success': False, 'error': 'invalid_firmware'}), 400
    background = data.get('show_background_image', 'default')
    if background not in _BACKGROUND_CHOICES:
        return jsonify({'success': False, 'error': 'invalid_background'}), 400
    current_user.console_firmware = console_firmware or None
    current_user.show_background_image = _BACKGROUND_CHOICES[background]
    db.session.commit()
    return jsonify({'success': True})

# --- Upcoming releases, sagas, wishlist (discover.py, series.py) ---------------------

def library_access(view):
    """The Library's own rule: anyone on a public shop, otherwise a user with shop access."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if get_settings()['shop']['public']:
            return view(*args, **kwargs)
        return access_required('shop')(view)(*args, **kwargs)
    return wrapper

def _owned_title_ids():
    return {row.title_id.upper() for row in Titles.query.filter_by(have_base=True)
            .with_entities(Titles.title_id) if row.title_id}

def _wishlist_ids():
    if not current_user.is_authenticated:
        return set()
    return {w.title_id for w in Wishlist.query.filter_by(user_id=current_user.id)}

@app.route('/upcoming')
@library_access
def upcoming_page():
    return render_template('upcoming.html', title='Upcoming', can_wishlist=current_user.is_authenticated)

@app.route('/sagas')
@app.route('/sagas/<saga_id>')
@library_access
def sagas_page(saga_id=None):
    if saga_id is not None and not re.fullmatch(r'Q\d{1,12}', saga_id):
        saga_id = ''
    return render_template('sagas.html', title='Sagas', saga_id=saga_id)

@app.get('/api/upcoming')
@library_access
def upcoming_api():
    return jsonify(discover.upcoming(datetime.date.today(), current_language(),
                                     _owned_title_ids(), _wishlist_ids()))

@app.get('/api/sagas')
@library_access
def sagas_api():
    return jsonify({'sagas': discover.sagas(datetime.date.today(), current_language(), _owned_title_ids())})

@app.get('/api/sagas/<saga_id>')
@library_access
def saga_api(saga_id):
    saga = discover.saga(saga_id, datetime.date.today(), current_language(), _owned_title_ids())
    if saga is None:
        return jsonify({'error': 'not_found'}), 404
    return jsonify(saga)

@app.get('/api/sagas/of/<title_id>')
@library_access
def sagas_of_api(title_id):
    return jsonify({'sagas': discover.sagas_of(title_id, datetime.date.today(), current_language(),
                                                _owned_title_ids())})

_TITLE_ID_ANY_CASE = re.compile(r'[0-9A-Fa-f]{16}')

@app.get('/api/wishlist')
@login_required
def wishlist_api():
    rows = Wishlist.query.filter_by(user_id=current_user.id).order_by(Wishlist.added_at)
    return jsonify({'title_ids': [w.title_id for w in rows]})

@app.post('/api/wishlist')
@login_required
def wishlist_add_api():
    title_id = str((request.get_json(silent=True) or {}).get('title_id') or '')
    if not _TITLE_ID_ANY_CASE.fullmatch(title_id):
        return jsonify({'success': False, 'error': 'invalid_title_id'}), 400
    title_id = title_id.upper()
    if not Wishlist.query.filter_by(user_id=current_user.id, title_id=title_id).first():
        db.session.add(Wishlist(user_id=current_user.id, title_id=title_id))
        db.session.commit()
    return jsonify({'success': True})

@app.delete('/api/wishlist/<title_id>')
@login_required
def wishlist_remove_api(title_id):
    Wishlist.query.filter_by(user_id=current_user.id, title_id=title_id.upper()).delete()
    db.session.commit()
    return jsonify({'success': True})

@app.route('/setup')
def setup_page():
    """Setup page showing client information and connection instructions."""
    settings = get_settings()

    # Check if user has access (must have shop access or shop must be public)
    if not settings['shop']['public'] and admin_account_created():
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.has_shop_access():
            return 'Forbidden', 403

    local_address = None
    local_port  = None

    # Get remote host from configuration
    remote_host = settings['shop'].get('host', '')

    # Whether the "Local" tab starts active: true unless the admin is definitely viewing
    # /setup through the configured remote host already. This no longer hides the tab
    # (or Discovery, fixed earlier) - which access actually works for the Switch is a
    # property of the Switch's own network, not of which URL loaded this page.
    show_local_tab = not remote_host or remote_host != request.host
    # get_lan_ip() reads the server's own network interfaces - it has nothing to do with
    # the Host header the browser happened to send, so it's always worth computing: an
    # admin who always loads /setup through their public domain, even from the same WiFi
    # as their Switch, still needs a real local address to hand it.
    local_address = get_lan_ip() or request.host.split(':')[0]
    local_port = request.host.split(':')[1] if ':' in request.host else 80

    # Check if clients are enabled
    tinfoil_enabled = settings.get('shop', {}).get('clients', {}).get('tinfoil', {}).get('enabled', False)
    sphaira_enabled = settings.get('shop', {}).get('clients', {}).get('sphaira', {}).get('enabled', False)
    cyberfoil_enabled = settings.get('shop', {}).get('clients', {}).get('cyberfoil', {}).get('enabled', False)

    # Check if shop is public
    shop_public = settings['shop']['public']
    discovery_enabled = settings.get('services', {}).get('discovery', {}).get('enabled', False)
    is_admin = not admin_account_created() or (current_user.is_authenticated and current_user.has_admin_access())

    return render_template(
        'setup.html',
        title='Setup',
        local_address=local_address,
        local_port=local_port,
        remote_host=remote_host,
        show_local_tab=show_local_tab,
        tinfoil_enabled=tinfoil_enabled,
        sphaira_enabled=sphaira_enabled,
        cyberfoil_enabled=cyberfoil_enabled,
        shop_public=shop_public,
        discovery_enabled=discovery_enabled,
        is_admin=is_admin,
        admin_account_created=admin_account_created()
    )

@app.get('/api/settings')
@access_required('admin')
def get_settings_api():
    settings = copy.deepcopy(get_settings())
    # Inject runtime key status for the UI
    valid, missing, corrupt = load_keys()
    settings['titles']['valid_keys'] = valid
    settings['titles']['missing_keys'] = missing
    settings['titles']['corrupt_keys'] = corrupt
    # Strip hauth values for privacy (don't send to client)
    if 'clients' in settings['shop']:
        for client_name, client_settings in settings['shop']['clients'].items():
            if 'hauth' in client_settings:
                # Replace hauth dict with empty dict to keep it private
                settings['shop']['clients'][client_name]['hauth'] = {}
    return jsonify(settings)

@app.post('/api/settings/titles')
@access_required('admin')
def set_titles_settings_api():
    title_settings = request.json
    region = title_settings['region']
    language = title_settings['language']
    with open(os.path.join(TITLEDB_DIR, 'languages.json')) as f:
        languages = json.load(f)
        languages = dict(sorted(languages.items()))

    if region not in languages or language not in languages[region]:
        resp = {
            'success': False,
            'errors': [{
                    'path': 'titles',
                    'error': f"The region/language pair {region}/{language} is not available."
                }]
        }
        return jsonify(resp)

    current = get_settings()
    if region != current['titles']['region'] or language != current['titles']['language']:
        set_titles_settings(region, language)
        tasks_mod.update_scheduled_task('update_titledb', datetime.datetime.utcnow())

    resp = {
        'success': True,
        'errors': []
    }
    return jsonify(resp)

@app.get('/api/settings/local_media/usage')
@access_required('admin')
def local_media_usage_api():
    return jsonify(media.usage())

@app.post('/api/settings/local_media')
@access_required('admin')
def set_local_media_settings_api():
    was_enabled = local_media_enabled()
    set_local_media_settings(request.json)
    if local_media_enabled() and not was_enabled:
        tasks_mod.enqueue_task('download_media')
    return jsonify({'success': True, 'errors': []})

@app.post('/api/settings/shop')
@access_required('admin')
def set_shop_settings_api():
    data = request.json
    set_shop_settings(data)
    resp = {
        'success': True,
        'errors': []
    }
    return jsonify(resp)

@app.post('/api/settings/notifications')
@access_required('admin')
def set_notification_settings_api():
    data = request.json or {}
    language = data.get('language')
    if language is not None and language not in SUPPORTED_LANGUAGES:
        return jsonify({'success': False, 'errors': [
            {'path': 'notifications/language', 'error': f'Unsupported language {language}'}]})
    set_notification_settings(data)
    return jsonify({'success': True, 'errors': []})

@app.post('/api/settings/notifications/test')
@access_required('admin')
def test_notification_settings_api():
    """Send a test message with the form as currently filled in (saved or not), and
    report each enabled provider's outcome so the UI can say which one is wrong."""
    config = copy.deepcopy(get_settings()['notifications'])
    for key, value in (request.json or {}).items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    results = notifications.send_test(config)
    if not results:
        return jsonify({'success': False, 'results': {}, 'error': 'no_provider'})
    return jsonify({'success': all(err is None for err in results.values()), 'results': results})

@app.post('/api/settings/services')
@access_required('admin')
def set_services_settings_api():
    data = request.json
    set_services_settings(data)
    discovery.reconcile()
    resp = {
        'success': True,
        'errors': []
    }
    return jsonify(resp)

@app.route('/api/settings/library/paths', methods=['GET', 'POST', 'DELETE'])
@access_required('admin')
def library_paths_api():
    global watcher
    if request.method == 'POST':
        data = request.json
        success, errors = add_library_complete(app, watcher, data['path'])
        if success:
            tasks_mod.enqueue_task('scan_library', {'library_path': data['path']})
        resp = {
            'success': success,
            'errors': errors
        }
    elif request.method == 'GET':
        resp = {'success': True, 'errors': [], 'paths': get_library_paths(),
                'watcher': get_watcher_config()}
    elif request.method == 'DELETE':
        data = request.json
        success, errors = remove_library_complete(app, watcher, data['path'])
        resp = {
            'success': success,
            'errors': errors
        }
    return jsonify(resp)

@app.post('/api/settings/library/watcher')
@access_required('admin')
def set_library_watcher_settings_api():
    global watcher
    success, errors = set_watcher_settings(request.json)
    if not success:
        return jsonify({'success': success, 'errors': errors})
    # Re-apply the new config live (runs in the request thread, not the observer thread)
    watcher.reconcile()
    return jsonify({'success': True, 'errors': []})

@app.post('/api/settings/library/management')
@access_required('admin')
def set_library_management_settings_api():
    data = request.json
    set_library_management_settings(data)
    tasks_mod.enqueue_task('process_library')
    resp = {
        'success': True,
        'errors': []
    }
    return jsonify(resp)

@app.post('/api/settings/scheduler')
@access_required('admin')
def set_scheduler_settings_api():
    from utils import interval_string_to_timedelta
    data = request.json
    titledb_update_interval_str = data.get('titledb_update_interval')

    if titledb_update_interval_str is not None:
        is_valid, error_msg = validate_interval_string(titledb_update_interval_str)
        if not is_valid:
            return jsonify({
                'success': False,
                'errors': [{'path': 'scheduler/titledb_update_interval', 'error': error_msg}]
            })

    set_scheduler_settings(data)

    if titledb_update_interval_str is not None:
        delta = interval_string_to_timedelta(titledb_update_interval_str)
        run_after = datetime.datetime.utcnow() + delta if delta else None
        tasks_mod.update_scheduled_task('update_titledb', run_after)

    return jsonify({'success': True, 'errors': []})

@app.post('/api/settings/appearance')
@access_required('admin')
def set_appearance_settings_api():
    data = request.json or {}
    style = data.get('default_style')
    if style not in APPEARANCE_STYLES:
        return jsonify({'success': False, 'errors': [
            {'path': 'appearance/default_style', 'error': f'Use one of: {", ".join(APPEARANCE_STYLES)}'}]})
    set_appearance_settings({'default_style': style})
    return jsonify({'success': True, 'errors': []})

VAULT_MIN_PASSWORD = 10

@app.post('/api/settings/vault')
@access_required('admin')
def set_vault_settings_api():
    """The save vault (vault.py) for everyone: on/off and how many backups each game
    keeps. Each user sets their own vault password in My account."""
    data = request.get_json(silent=True) or {}
    try:
        keep = int(data.get('keep') or 0)
    except (TypeError, ValueError):
        keep = -1
    if keep not in vault.KEEP_CHOICES:
        return jsonify({'success': False, 'errors': ['keep']}), 400
    set_vault_settings({'enabled': bool(data.get('enabled')), 'keep': keep})
    return jsonify({'success': True})

# The vault answers JKSV before (and without) the web login: the user's own vault password.
@app.post('/api/settings/registration')
@access_required('admin')
def set_registration_settings_api():
    """Public registration on or off, and the public address for emailed links."""
    data = request.get_json(silent=True) or {}
    url = str(data.get('public_url') or '').strip().rstrip('/')
    if url and not re.fullmatch(r'https?://[^\s/]+(/[^\s]*)?', url):
        return jsonify({'success': False, 'errors': ['public_url']}), 400
    set_registration_settings({'enabled': bool(data.get('enabled')), 'public_url': url})
    return jsonify({'success': True})

@app.get('/api/settings/registration/status')
@access_required('admin')
def registration_status_api():
    """Which of email and Google are set up in the environment - never their secrets."""
    smtp = accounts.smtp_config()
    return jsonify({'email': smtp is not None, 'email_from': smtp['from'] if smtp else None,
                    'google': accounts.google_config() is not None})

@app.post('/api/settings/registration/test-email')
@access_required('admin')
def registration_test_email_api():
    to = str((request.get_json(silent=True) or {}).get('to') or '').strip()
    if not accounts.valid_email(to):
        return jsonify({'success': False, 'error': 'invalid_email'}), 400
    try:
        accounts.send_mail(to, t('mail.test_subject'), t('mail.test_body'))
    except Exception as e:
        logger.warning(f'Test email failed: {e}')
        return jsonify({'success': False, 'error': str(e)[:200]}), 502
    return jsonify({'success': True})

app.add_url_rule('/dav', 'vault_root', vault.handle, methods=vault.METHODS + ['PATCH', 'PROPPATCH', 'LOCK', 'UNLOCK', 'COPY', 'POST'],
                 strict_slashes=False)
app.add_url_rule('/dav/<path:subpath>', 'vault_path', vault.handle,
                 methods=vault.METHODS + ['PATCH', 'PROPPATCH', 'LOCK', 'UNLOCK', 'COPY', 'POST'])

def saves_access(view):
    """Admins and users with the Backup permission (vault.may_use)."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if admin_account_created() and current_user.is_authenticated and current_user.is_admin:
            return view(*args, **kwargs)
        return access_required('backup')(view)(*args, **kwargs)
    return wrapper

@app.route('/saves')
@saves_access
def saves_page():
    return render_template('saves.html', title='Saves')

def _saves_owner():
    """Whose backups a Saves request names: the signed-in user's own - or, for an admin,
    the user in ?user= (the Saves page lists everyone's for them)."""
    if current_user.is_admin and request.args.get('user', '').isdigit():
        return int(request.args['user'])
    return current_user.id

def _save_games():
    """The backups one sees grouped by user and game (newest first), with each game's name
    and icon: one's own, or everyone's for an admin."""
    names = {u.id: u.user for u in User.query.with_entities(User.id, User.user)}
    games = {}
    for b in vault.backups(None if current_user.is_admin else [current_user.id]):
        key = (b['user_id'], b['title_id'] or b['folder'])
        game = games.setdefault(key, {'title_id': b['title_id'], 'folder': b['folder'], 'backups': [],
                                      'size': 0, 'latest': b['time'], 'user_id': b['user_id'],
                                      'user': names.get(b['user_id'], f"#{b['user_id']}")})
        game['backups'].append(b)
        game['size'] += b['size']
        game['latest'] = max(game['latest'], b['time'])
    out = []
    for game in games.values():
        info = (titles_lib.get_game_info(game['title_id']) or {}) if game['title_id'] else {}
        name = info.get('name')
        game['name'] = name if name and name != 'Unrecognized' else game['folder']
        game['icon_url'] = info.get('iconUrl')
        out.append(game)
    out.sort(key=lambda g: g['latest'], reverse=True)
    return out

@app.get('/api/saves')
@saves_access
def saves_api():
    games = _save_games()
    saved = {g['title_id'] for g in games if g['title_id'] and g['user_id'] == current_user.id}
    missing = []
    # The library's games without a backup: only for those who may see the library.
    library_ids = _owned_title_ids() if current_user.has_access('shop') else set()
    for title_id in sorted(library_ids - saved):
        info = titles_lib.get_game_info(title_id) or {}
        if info.get('name') and info['name'] != 'Unrecognized':
            missing.append({'title_id': title_id, 'name': info['name'], 'icon_url': info.get('iconUrl')})
    missing.sort(key=lambda g: g['name'].lower())
    return jsonify({'enabled': vault.enabled(), 'games': games, 'missing': missing,
                    'all_users': bool(current_user.is_admin)})

@app.get('/api/saves/download')
@saves_access
def saves_download_api():
    path = vault.backup_path(_saves_owner(), request.args.get('path'))
    if path is None:
        return jsonify({'error': 'not_found'}), 404
    folder = os.path.basename(os.path.dirname(path))
    return send_file(path, mimetype='application/zip', as_attachment=True,
                     download_name=f'{folder} - {os.path.basename(path)}')

@app.delete('/api/saves')
@saves_access
def saves_delete_api():
    if not vault.delete_backup(_saves_owner(), request.args.get('path')):
        return jsonify({'success': False, 'error': 'not_found'}), 404
    logger.info(f"Save backup {request.args.get('path')} deleted by {current_user.user if current_user.is_authenticated else '-'}")
    return jsonify({'success': True})

@app.get('/api/saves/of/<title_id>')
@saves_access
def saves_of_api(title_id):
    mine = [b for b in vault.backups([current_user.id]) if (b['title_id'] or '') == title_id.upper()]
    return jsonify({'count': len(mine), 'latest': mine[0]['time'] if mine else None})

@app.post('/api/settings/maintenance')
@access_required('admin')
def set_maintenance_settings_api():
    data = request.json or {}
    clean, errors = {}, []
    for key in ('enabled', 'scan', 'remove_outdated_updates', 'backup'):
        if key in data:
            clean[key] = bool(data[key])
    if 'time' in data:
        match = re.fullmatch(r'([01]?\d|2[0-3]):([0-5]\d)', str(data['time']).strip())
        if match:
            clean['time'] = f'{int(match.group(1)):02d}:{match.group(2)}'
        else:
            errors.append({'path': 'maintenance/time', 'error': 'Use HH:MM (00:00-23:59)'})
    if 'verify_all' in data:
        if data['verify_all'] in tasks_mod.VERIFY_ALL_CHOICES:
            clean['verify_all'] = data['verify_all']
        else:
            errors.append({'path': 'maintenance/verify_all', 'error': 'Must be off, daily or weekly'})
    if 'backup_keep' in data:
        try:
            keep = int(data['backup_keep'])
            if not 1 <= keep <= 365:
                raise ValueError
            clean['backup_keep'] = keep
        except (TypeError, ValueError):
            errors.append({'path': 'maintenance/backup_keep', 'error': 'Must be a whole number from 1 to 365'})
    if errors:
        return jsonify({'success': False, 'errors': errors})
    set_maintenance_settings(clean)
    tasks_mod.reschedule_maintenance()
    return jsonify({'success': True, 'errors': [], 'next_run': _next_maintenance_run_local()})

def _next_maintenance_run_local():
    """The pending maintenance run in the server's local time, for the UI - or None."""
    run_after = db.session.query(Task.run_after).filter_by(
        task_name='scheduled_maintenance', status='pending').scalar()
    if run_after is None:
        return None
    return (run_after + tasks_mod.utc_offset()).isoformat(timespec='minutes')

@app.get('/api/backups')
@access_required('admin')
def list_backups_api():
    return jsonify({'backups': backups.list_backups(), 'next_run': _next_maintenance_run_local()})

@app.post('/api/backups')
@access_required('admin')
def create_backup_api():
    try:
        entry = backups.create_backup()
    except Exception as e:
        logger.exception('Manual backup failed')
        return jsonify({'success': False, 'error': str(e)}), 500
    backups.prune_backups(get_settings()['maintenance']['backup_keep'])
    return jsonify({'success': True, 'backup': entry, 'backups': backups.list_backups()})

@app.get('/api/backups/<name>')
@access_required('admin')
def download_backup_api(name):
    path = backups.backup_path(name)
    if path is None:
        return jsonify({'error': 'No such backup'}), 404
    return send_from_directory(backups.BACKUP_DIR, name, as_attachment=True)

@app.delete('/api/backups/<name>')
@access_required('admin')
def delete_backup_api(name):
    path = backups.backup_path(name)
    if path is None:
        return jsonify({'success': False, 'error': 'No such backup'}), 404
    os.remove(path)
    return jsonify({'success': True, 'backups': backups.list_backups()})

@app.post('/api/settings/worker')
@access_required('admin')
def set_worker_settings_api():
    data = request.json
    count = data.get('count')
    if count is not None:
        try:
            count = int(count)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'errors': [{'path': 'worker/count', 'error': 'Must be an integer'}]})
        if count < 1:
            return jsonify({'success': False, 'errors': [{'path': 'worker/count', 'error': 'Must be at least 1'}]})
        data['count'] = count
    group_limits = data.get('group_limits')
    if group_limits is not None:
        # Every concurrency group a task can be registered under (see tasks.py's
        # TASK_GROUPS) gets the same validation, not just 'io' - 'net' (artwork/media
        # downloads) is the other one in use today, and a group with no key in the
        # request is left untouched rather than reset.
        parsed = {}
        for name in DEFAULT_SETTINGS['worker']['group_limits']:
            if name not in group_limits:
                continue
            try:
                value = int(group_limits[name])
            except (TypeError, ValueError):
                return jsonify({'success': False, 'errors': [
                    {'path': f'worker/group_limits/{name}', 'error': 'Must be an integer'}]})
            if value < 1:
                return jsonify({'success': False, 'errors': [
                    {'path': f'worker/group_limits/{name}', 'error': 'Must be at least 1'}]})
            parsed[name] = value
        # Merge into current limits so any other groups are preserved.
        current = get_settings().get('worker', {}).get('group_limits', {})
        data['group_limits'] = {**current, **parsed}
    set_worker_settings(data)
    return jsonify({'success': True, 'errors': []})

@app.post('/api/upload')
@access_required('admin')
def upload_file():
    errors = []
    success = False
    valid_keys = None
    try:
        file = request.files['file']
        if file and allowed_file(file.filename):
            # filename = secure_filename(file.filename)
            file.save(KEYS_FILE)
            logger.info(f'Validating {file.filename}...')
            valid_keys, missing_keys, corrupt_keys = load_keys(KEYS_FILE)
            if valid_keys:
                tasks_mod.enqueue_task('process_library')
            else:
                logger.warning(f'Invalid keys from {file.filename}')
            success = True
            logger.info('Successfully saved keys.txt')

    except Exception as e:
        logger.error(f'Failed to upload console keys file: {e}')
        os.remove(KEYS_FILE)
        success = False
        errors.append(str(e))

    resp = {
        'success': success,
        'errors': errors,
        'data': {}
    }

    if valid_keys is not None:
        resp['data']['valid_keys'] = valid_keys
        resp['data']['missing_keys'] = missing_keys
        resp['data']['corrupt_keys'] = corrupt_keys

    return jsonify(resp)


from gql import graphql_dispatch

app.add_url_rule(
    '/api/graphql',
    view_func=graphql_dispatch,
    methods=['GET', 'POST'],
)

@app.route('/api/get_game/<int:id>')
@file_access
def serve_game(id):
    """Serve a game file to authenticated clients."""
    filepath = db.session.query(Files.filepath).filter_by(id=id).scalar()
    if not filepath:
        return jsonify({'error': f'No file with id {id}.'}), 404
    filedir, filename = os.path.split(filepath)
    # Count only once the response exists: clients probe files with a Range before taking
    # them, and a range past the end of the file raises out of here without transferring.
    response = send_from_directory(filedir, filename)
    user, client = download_caller(request)
    increment_download_count_throttled(filepath, client_address(request), user=user, client=client)
    return response

@app.route('/api/library/download/<int:file_id>')
@access_required('shop')
def download_library_file(file_id):
    """Serve a file straight from the web library UI's List view.

    Distinct from `serve_game`: that one is for shop clients (Tinfoil/etc.) and gates
    on HTTP Basic Auth against shop access, appropriate for a device that isn't running
    a browser session. This one is for a signed-in user's own browser - any user with
    shop access, admin or not (an admin account always has shop access too, so this
    doesn't take anything away from an admin-only setup) - gated on the normal
    session-based login plus an explicit opt-in setting: downloading straight off the
    server's storage through the web UI is off by default even once someone has shop
    access, until turned on in Settings.
    """
    if not get_settings()['library']['management'].get('web_downloads', {}).get('enabled', False):
        return jsonify({'error': 'Web downloads are disabled in Settings > Library.'}), 403
    file_obj = db.session.get(Files, file_id)
    if not file_obj or not os.path.isfile(file_obj.filepath):
        return jsonify({'error': f'No file with id {file_id}.'}), 404
    filedir, filename = os.path.split(file_obj.filepath)
    response = send_from_directory(filedir, filename, as_attachment=True)
    increment_download_count_throttled(file_obj.filepath, client_address(request),
                                       user=current_user.user if current_user.is_authenticated else None,
                                       client='web')
    return response

@app.route('/api/media/<title_id>/<kind>/<int:position>/<size>/<path:name>')
@file_access
def serve_media(title_id, kind, position, size, name):
    """Serve a local copy of title artwork (Settings > Local artworks). Same
    audience and auth as a library file download - this is what a console's native
    "Ownfoil" client actually requests for the icon/banner/screenshot URLs its
    GraphQL responses carry, once Local artworks has a copy.

    The title and slot are in the path to keep the URL readable; the file is found
    by kind/size/filename alone, so this stays a static send with no database read.
    Filenames are content hashes, which is what makes the year of cache safe.
    """
    try:
        directory = media.media_dir(kind, size)
    except ValueError:
        return '', 404
    # Derive the rendition from its original if it isn't already on disk.
    media.build(kind, size, name)
    response = send_from_directory(directory, name, max_age=31536000)
    if not get_settings()['shop']['public']:
        # Keep a private shop's artwork out of shared caches.
        response.cache_control.public = False
        response.cache_control.private = True
        response.headers['Vary'] = 'Authorization, Cookie'
    return response

@app.route('/api/settings/export')
@access_required('admin')
def export_settings():
    """Download the current settings as a YAML file - a backup, or something to move
    to another install. Serves the effective, already-migrated settings from
    get_settings() rather than the file as it happens to be on disk, so what comes out
    always matches what the app is actually running with.

    `?include_secrets=0` leaves out the Tinfoil key pair and the clients' saved hauth
    values - for a file meant to be shared (a bug report, a forum post). The keys are
    removed rather than blanked, so importing that file back keeps the current ones."""
    settings = copy.deepcopy(get_settings())
    include_secrets = request.args.get('include_secrets', '1') != '0'
    if not include_secrets:
        for client_settings in settings.get('shop', {}).get('clients', {}).values():
            for key in ('hauth', 'clientCertKey', 'clientCertPub'):
                client_settings.pop(key, None)
        # Webhook URLs and bot tokens are credentials: anyone holding one can post.
        for provider, key in (('discord', 'webhook_url'), ('telegram', 'bot_token'),
                              ('ntfy', 'token'), ('webhook', 'url')):
            settings.get('notifications', {}).get(provider, {}).pop(key, None)
    yaml_text = yaml.safe_dump(settings, sort_keys=False, allow_unicode=True)
    suffix = '' if include_secrets else '-shareable'
    filename = f"ownfoil-settings-{datetime.date.today().isoformat()}{suffix}.yaml"
    return Response(yaml_text, mimetype='application/x-yaml',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})

@app.route('/api/settings/import', methods=['POST'])
@access_required('admin')
def import_settings():
    """Restore settings from a previously exported (or hand-edited) YAML file. Merges
    into the current settings rather than replacing them outright - see
    settings.import_settings_yaml - so an older export missing a section a newer
    ownfoil version added doesn't blank that section out."""
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'No file uploaded.'}), 400
    try:
        raw_text = file.read().decode('utf-8')
    except UnicodeDecodeError:
        return jsonify({'error': 'File is not valid UTF-8 text.'}), 400
    try:
        import_settings_yaml(raw_text)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'success': True})



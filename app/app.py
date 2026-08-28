import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, Response
from flask_login import LoginManager
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
import titles as titles_lib
import yaml
from i18n import register_i18n
import realtime
import titledb
import os
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

def create_app(db_uri=None):
    app = Flask(__name__)
    app.url_map.strict_slashes = False  # Disable automatic trailing slash redirects globally, needed for Sphaira
    app.config["SQLALCHEMY_DATABASE_URI"] = db_uri or OWNFOIL_DB
    # TODO: generate random secret_key
    app.config['SECRET_KEY'] = '8accb915665f11dfa15c2db1a4e8026905f57716'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    app.register_blueprint(auth_blueprint)
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

def file_access(f):
    """Decorator for file serving endpoints with basic authentication (no client identification required)."""
    @wraps(f)
    def _file_access(*args, **kwargs):
        # Check if shop is private
        if not get_settings()['shop']['public']:
            # Shop is private, require authentication
            auth_success, auth_error, user = basic_auth(request)
            if not auth_success:
                return jsonify({'error': auth_error}), 401
            elif not user.has_shop_access():
                return jsonify({'error': f'User "{user.user}" does not have access to the shop.'}), 403

        return f(*args, **kwargs)
    return _file_access

def access_shop():
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
    return render_template(
        'index.html', title='Library', admin_account_created=admin_account_created(),
        is_admin=is_admin, is_shop=is_shop,
        web_downloads_enabled=settings['library']['management'].get('web_downloads', {}).get('enabled', False),
    )

@access_required('shop')
def access_shop_auth():
    return access_shop()

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def index(path=None):
    """Main shop endpoint routing to either client-specific shop or web browser UI."""
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

@app.route('/admin')
@access_required('admin')
def admin_page():
    return redirect('/admin/settings')

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
    settings = get_settings()
    return render_template('stats.html', title='Stats',
                           admin_account_created=admin_account_created(),
                           web_clean_record_enabled=settings['library']['management'].get('web_clean_record', {}).get('enabled', False))

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

    # Check if we're accessing via the configured remote host
    # If so, hide the local tab since we're already remote
    show_local_tab = not remote_host or remote_host != request.host
    if show_local_tab:
        # The Host header is the browser's view of the server (localhost, an mDNS name, a
        # container name) and is often unreachable from the Switch, so prefer our own LAN IP.
        local_address = get_lan_ip() or request.host.split(':')[0]
        local_port = request.host.split(':')[1] if ':' in request.host else 80

    # Check if clients are enabled
    tinfoil_enabled = settings.get('shop', {}).get('clients', {}).get('tinfoil', {}).get('enabled', False)
    sphaira_enabled = settings.get('shop', {}).get('clients', {}).get('sphaira', {}).get('enabled', False)
    cyberfoil_enabled = settings.get('shop', {}).get('clients', {}).get('cyberfoil', {}).get('enabled', False)

    # Check if shop is public
    shop_public = settings['shop']['public']
    
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
        try:
            io = int(group_limits['io'])
        except (TypeError, ValueError, KeyError):
            return jsonify({'success': False, 'errors': [{'path': 'worker/group_limits', 'error': 'Must be an integer'}]})
        if io < 1:
            return jsonify({'success': False, 'errors': [{'path': 'worker/group_limits', 'error': 'Must be at least 1'}]})
        # Merge into current limits so any other groups are preserved.
        current = get_settings().get('worker', {}).get('group_limits', {})
        data['group_limits'] = {**current, 'io': io}
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
    increment_download_count_throttled(filepath, client_address(request))
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
    increment_download_count_throttled(file_obj.filepath, client_address(request))
    return response

@app.route('/api/titledb-image/<title_id>/<kind>')
@access_required('shop')
def titledb_image(title_id, kind):
    """Serve a locally-cached banner/icon for a title or DLC; fall back to a live
    redirect to titledb's own URL for it when nothing is cached yet (a fresh
    library, or cache_titledb_images_task just hasn't gotten to this one). The
    frontend always points here rather than at titledb's URL directly, so caching
    (once it catches up) is transparent - see titledb/images.py for why.
    """
    if kind not in ('banner', 'icon'):
        return jsonify({'error': "kind must be 'banner' or 'icon'."}), 400
    from titledb import images as images_lib
    cached_path = images_lib.image_cache_path(title_id, kind)
    if cached_path:
        directory, filename = os.path.split(cached_path)
        return send_from_directory(directory, filename)
    info = titles_lib.get_game_info(title_id)
    url = (info or {}).get('bannerUrl' if kind == 'banner' else 'iconUrl')
    if not url or not url.startswith('http'):
        return '', 404
    return redirect(url)

@app.route('/api/settings/export')
@access_required('admin')
def export_settings():
    """Download the current settings as a YAML file - a backup, or something to move
    to another install. Serves the effective, already-migrated settings from
    get_settings() rather than the file as it happens to be on disk, so what comes out
    always matches what the app is actually running with."""
    settings = get_settings()
    yaml_text = yaml.safe_dump(settings, sort_keys=False, allow_unicode=True)
    filename = f"ownfoil-settings-{datetime.date.today().isoformat()}.yaml"
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



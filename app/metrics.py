"""Prometheus metrics (GET /metrics), in the plain-text exposition format - written by
hand, so it costs no dependency. Library-level gauges only: per-file or per-title
labels would explode Prometheus's series count on a large library.

Access (see app.py's metrics route): an admin account (Basic Auth, which a Prometheus
scrape config supports directly, or a signed-in session), or the bearer token in
OWNFOIL_METRICS_TOKEN when set.
"""
import datetime
import shutil

from sqlalchemy import text

from containers.verification import status_of


def _escape(value):
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def _number(value):
    """Exact: byte counts and Unix timestamps must not be rounded (`%g` keeps only six
    significant digits, which turns a timestamp into minutes of error)."""
    value = float(value)
    return str(int(value)) if value.is_integer() else repr(value)


class _Writer:
    def __init__(self):
        self.lines = []

    def metric(self, name, kind, help_text, samples):
        """samples: [(labels dict, value)] or a bare value for an unlabelled metric."""
        self.lines.append(f'# HELP {name} {help_text}')
        self.lines.append(f'# TYPE {name} {kind}')
        if not isinstance(samples, list):
            samples = [({}, samples)]
        for labels, value in samples:
            label_text = ','.join(f'{k}="{_escape(v)}"' for k, v in labels.items())
            self.lines.append(f'{name}{{{label_text}}} {_number(value)}' if label_text
                              else f'{name} {_number(value)}')

    def render(self):
        return '\n'.join(self.lines) + '\n'


def render_metrics(db, settings, version, library_paths, backups_list):
    w = _Writer()
    w.metric('ownfoil_info', 'gauge', 'Ownfoil-Plus version.', [({'version': version}, 1)])

    files, size, identified, downloads = db.session.execute(text(
        "SELECT COUNT(*), COALESCE(SUM(size), 0), COALESCE(SUM(identified), 0), "
        "COALESCE(SUM(download_count), 0) FROM files")).first()
    w.metric('ownfoil_library_files', 'gauge', 'Files in the library.', files)
    w.metric('ownfoil_library_size_bytes', 'gauge', 'Total size of the library files.', size)
    w.metric('ownfoil_library_unidentified_files', 'gauge', 'Files not identified as any title.',
             files - identified)
    w.metric('ownfoil_file_downloads_total', 'counter',
             'Downloads counted across all files in the library (shop clients and web).', downloads)

    owned, complete, up_to_date = db.session.execute(text(
        "SELECT COUNT(*), COALESCE(SUM(complete), 0), COALESCE(SUM(up_to_date), 0) "
        "FROM main.titles WHERE have_base = 1")).first()
    w.metric('ownfoil_titles_owned', 'gauge', 'Games whose base is in the library.', owned)
    w.metric('ownfoil_titles_complete', 'gauge', 'Owned games with all their DLC.', complete)
    w.metric('ownfoil_titles_up_to_date', 'gauge', 'Owned games with their latest update.', up_to_date)

    statuses = {}
    for sig, hashed, modified, count in db.session.execute(text(
            "SELECT signature_valid, hash_valid, hash_modified, COUNT(*) FROM files GROUP BY 1, 2, 3")):
        status = status_of(sig, hashed, modified).lower()
        statuses[status] = statuses.get(status, 0) + int(count)
    w.metric('ownfoil_files_by_verification_status', 'gauge', 'Files per verification status.',
             [({'status': s}, n) for s, n in sorted(statuses.items())])

    tasks = dict(db.session.execute(text("SELECT status, COUNT(*) FROM tasks GROUP BY status")).all())
    w.metric('ownfoil_tasks', 'gauge', 'Background tasks per status.',
             [({'status': s}, tasks.get(s, 0)) for s in
              ('pending', 'running', 'waiting_for_children', 'failed')])

    since = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    w.metric('ownfoil_downloads_last_24h', 'gauge', 'Downloads logged in the last 24 hours.',
             db.session.execute(text("SELECT COUNT(*) FROM download_events WHERE downloaded_at >= :s"),
                                {'s': since}).scalar())

    online, free, total = [], [], []
    for path in library_paths:
        try:
            usage = shutil.disk_usage(path)
            online.append(({'library': path}, 1))
            free.append(({'library': path}, usage.free))
            total.append(({'library': path}, usage.total))
        except OSError:
            online.append(({'library': path}, 0))
    w.metric('ownfoil_library_online', 'gauge', '1 when the library folder is reachable.', online)
    w.metric('ownfoil_library_disk_free_bytes', 'gauge', 'Free space on the library disk.', free)
    w.metric('ownfoil_library_disk_total_bytes', 'gauge', 'Size of the library disk.', total)

    if backups_list:
        last = datetime.datetime.fromisoformat(backups_list[0]['created'])
        w.metric('ownfoil_backup_last_timestamp_seconds', 'gauge',
                 'Unix time of the newest backup.', last.timestamp())
    w.metric('ownfoil_backups', 'gauge', 'Backups kept in config/backups.', len(backups_list))
    w.metric('ownfoil_users', 'gauge', 'User accounts.',
             db.session.execute(text("SELECT COUNT(*) FROM user")).scalar())
    w.metric('ownfoil_shop_public', 'gauge', '1 when the shop needs no login.',
             1 if settings['shop']['public'] else 0)
    return w.render()

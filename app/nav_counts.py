"""The counters on the admin's top bar and phone bottom bar: unidentified files and
running tasks. Every admin page renders them, so the two counts are cached for a few
seconds instead of costing two queries per click."""
import logging
import threading
import time

from db import Files, Task

CACHE_SECONDS = 5

logger = logging.getLogger('main')

_lock = threading.Lock()
_cached = None
_cached_at = 0.0


def get_nav_counts():
    """Never raises: the counters are a hint, and every admin page renders them - a
    failing query (a locked database mid-scan) must not turn those pages into a 500.
    The last known counts are kept (or none are shown) until a query works again.
    The cache is per process: with several gunicorn workers the counts can differ for a
    few seconds between them."""
    global _cached, _cached_at
    with _lock:
        if _cached is None or time.monotonic() - _cached_at > CACHE_SECONDS:
            try:
                _cached = {
                    'unidentified': Files.query.filter(Files.identified.is_(False)).count(),
                    'running_tasks': Task.query.filter_by(status='running').count(),
                }
            except Exception as e:
                logger.debug(f'Navigation counters unavailable: {e}')
                _cached = _cached or {'unidentified': 0, 'running_tasks': 0}
            _cached_at = time.monotonic()
        return dict(_cached)


def clear_cache():
    global _cached
    with _lock:
        _cached = None

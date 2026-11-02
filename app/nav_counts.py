"""The counters on the admin's top bar and phone bottom bar: unidentified files and
running tasks. Every admin page renders them, so the two counts are cached for a few
seconds instead of costing two queries per click."""
import threading
import time

from db import Files, Task

CACHE_SECONDS = 5

_lock = threading.Lock()
_cached = None
_cached_at = 0.0


def get_nav_counts():
    global _cached, _cached_at
    with _lock:
        if _cached is None or time.monotonic() - _cached_at > CACHE_SECONDS:
            _cached = {
                'unidentified': Files.query.filter(Files.identified.is_(False)).count(),
                'running_tasks': Task.query.filter_by(status='running').count(),
            }
            _cached_at = time.monotonic()
        return dict(_cached)


def clear_cache():
    global _cached
    with _lock:
        _cached = None

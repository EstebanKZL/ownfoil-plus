"""Local caching of the banner/icon artwork titledb points at.

titledb's own JSON entries carry bannerUrl/iconUrl pointing at a third-party image
host - ownfoil has never hosted this artwork itself. Serving it straight from that
remote host means the library page's images break whenever that host is slow,
rate-limiting, or down, even though everything else about the page (names, sizes,
verification status) comes entirely from ownfoil's own database. This module downloads
a local copy alongside the titledb JSON files (TITLEDB_DIR/images/) so the app.py
route that serves them can fall back to a live redirect only when nothing is cached
yet, rather than the browser depending on that remote host on every single page load.
"""
import logging
import os

import requests
from sqlalchemy import text

from constants import TITLEDB_DIR

logger = logging.getLogger('main')

IMAGES_DIR = os.path.join(TITLEDB_DIR, 'images')
TIMEOUT = 15
KINDS = ('banner', 'icon')
# Paused between real downloads (never after a cache hit) in the batch task - a first
# run against a large library means hundreds of requests to the same third-party host
# in quick succession, which is the kind of burst that gets an IP rate-limited.
DOWNLOAD_DELAY = 0.25

_EXT_BY_CONTENT_TYPE = {
    'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif',
}
_KNOWN_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')


def image_cache_path(title_id, kind):
    """Where a cached image for this title/kind lives, if it's already been cached -
    None otherwise. The extension is discovered rather than assumed, since titledb's
    image host serves a mix of formats."""
    if not title_id or kind not in KINDS or not os.path.isdir(IMAGES_DIR):
        return None
    prefix = f"{title_id.upper()}_{kind}."
    for name in os.listdir(IMAGES_DIR):
        if name.startswith(prefix):
            return os.path.join(IMAGES_DIR, name)
    return None


def _guess_extension(url, content_type):
    lowered = url.lower().split('?')[0]
    for ext in _KNOWN_EXTS:
        if lowered.endswith(ext):
            return '.jpg' if ext == '.jpeg' else ext
    return _EXT_BY_CONTENT_TYPE.get((content_type or '').split(';')[0].strip().lower(), '.jpg')


def cache_image(title_id, kind, url):
    """Download one banner/icon into the local cache if it isn't there already.

    Returns True if a file is cached afterward (whether it already was, or was just
    downloaded), False if there was nothing to do it with or the download failed.
    False is not an error to raise - a caller should just keep using the live redirect
    for that image and try again on the next pass."""
    if not title_id or not url or kind not in KINDS:
        return False
    if image_cache_path(title_id, kind) is not None:
        return True

    os.makedirs(IMAGES_DIR, exist_ok=True)
    dest = None
    try:
        with requests.get(url, stream=True, timeout=TIMEOUT) as r:
            r.raise_for_status()
            ext = _guess_extension(url, r.headers.get('Content-Type'))
            dest = os.path.join(IMAGES_DIR, f"{title_id.upper()}_{kind}{ext}")
            tmp = dest + '.tmp'
            with open(tmp, 'wb') as fh:
                for chunk in r.iter_content(65536):
                    fh.write(chunk)
            os.replace(tmp, dest)
        return True
    except (requests.RequestException, OSError) as e:
        logger.warning(f"Could not cache {kind} image for {title_id}: {e}")
        if dest is not None:
            try:
                if os.path.exists(dest + '.tmp'):
                    os.remove(dest + '.tmp')
            except OSError:
                pass
        return False


def titles_needing_images():
    """Every title_id whose artwork the library page can currently display: each
    title ownfoil tracks anything for, plus every DLC titledb attributes to it (owned
    or not - the List view's metadata modal shows a missing DLC's own artwork too).
    Deliberately not the whole titledb catalogue (tens of thousands of titles) - only
    what this library actually has some relationship to."""
    from db import Titles, db

    owned_ids = [t.title_id for t in Titles.query.all()]
    if not owned_ids:
        return []

    result = {tid.upper() for tid in owned_ids}
    params = {f"d_{i}": tid.lower() for i, tid in enumerate(owned_ids)}
    placeholders = ",".join(f":d_{i}" for i in range(len(owned_ids)))
    rows = db.session.execute(text(f"""
        SELECT DISTINCT UPPER(c.app_id) AS dlc_id
        FROM titledb.cnmts c
        WHERE LOWER(c.other_application_id) IN ({placeholders}) AND c.title_type = 130
    """), params).all()
    result.update(r.dlc_id for r in rows if r.dlc_id)
    return sorted(result)

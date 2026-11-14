"""A game's cover, chosen in Edit on its page: found in the European eShop by name, taken
from an image the admin picks or pastes, and cropped square in the browser.

What is saved is always the server's own re-encoding of the image it was sent (opened
with Pillow, so only a real image gets through, turned upright and stored as JPEG) in the
local artwork store, and named as the title's icon by its user-authored metadata
('custom'): it wins over titledb's cover and the one read from the file, and *Reset* in
Edit, or *Use the original*, gives them back.

The eShop's images come from Nintendo's own servers: the page reads them through
/api/covers/image, which fetches only from those hosts, so the browser can crop them
(a canvas can't export an image from another origin).
"""
import io
import logging
import re
from urllib.parse import urlparse

import requests
from flask import Blueprint, Response, jsonify, request
from PIL import Image, ImageOps, UnidentifiedImageError

import media
import titledb
from auth import access_required
from titledb.schema import SOURCE_CUSTOM

logger = logging.getLogger('main')

covers_blueprint = Blueprint('covers', __name__)

ESHOP_SEARCH = 'https://searching.nintendo-europe.com/{lang}/select'
ESHOP_LANGS = ('en', 'es', 'fr', 'de', 'it', 'nl', 'pt', 'ru')
# The platforms of the eShop's search: the Switch, and the Switch 2.
PLATFORM_SWITCH = 'HAC'
PLATFORM_SWITCH2 = 'BEE'
TIMEOUT = (5, 15)
RESULTS = 18

# Hosts the cover proxy reads from: Nintendo's sites and image servers (the eShop's
# search answers with nintendo.com images; titledb's covers are on nintendo.net).
_ALLOWED_HOSTS = re.compile(r'(^|\.)(nintendo\.com|nintendo\.net|nintendo-europe\.com|nintendo\.co\.jp)$')
MAX_IMAGE = 16 << 20
MAX_PIXELS = 40_000_000
# The cover is saved at most this many pixels a side (the eShop's are 1000 or less).
MAX_SIDE = 1024
_TITLE_ID = re.compile(r'^[0-9A-Fa-f]{16}$')


def _title_id(value):
    return value.upper() if _TITLE_ID.match(value or '') else None


@covers_blueprint.get('/api/covers/search')
@access_required('admin')
def search():
    """The eShop's games matching a name, each with its square image: Switch 2 games
    only for a Switch 2 title (`switch2=1`), Switch ones otherwise."""
    query = (request.args.get('q') or '').strip()[:120]
    if not query:
        return jsonify({'results': []})
    lang = request.args.get('lang') or 'en'
    lang = lang if lang in ESHOP_LANGS else 'en'
    platform = PLATFORM_SWITCH2 if request.args.get('switch2') == '1' else PLATFORM_SWITCH
    try:
        response = requests.get(ESHOP_SEARCH.format(lang=lang), timeout=TIMEOUT, params={
            'q': query, 'fq': ['type:GAME', f'playable_on_txt:{platform}'], 'rows': RESULTS,
            'wt': 'json', 'fl': 'title,image_url_sq_s,image_url'})
        response.raise_for_status()
        docs = response.json().get('response', {}).get('docs', [])
    except (requests.RequestException, ValueError) as e:
        logger.warning(f'eShop search failed: {e}')
        return jsonify({'results': [], 'error': 'unreachable'}), 502
    results = []
    for doc in docs:
        image = doc.get('image_url_sq_s') or doc.get('image_url')
        if image and _allowed(image):
            results.append({'title': doc.get('title') or '', 'image': image})
    return jsonify({'results': results})


def _allowed(url):
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == 'https' and bool(_ALLOWED_HOSTS.search(parsed.hostname or ''))


@covers_blueprint.get('/api/covers/image')
@access_required('admin')
def image():
    """An image from Nintendo's servers, passed through so the page can crop it."""
    url = request.args.get('url') or ''
    if not _allowed(url):
        return jsonify({'error': 'not allowed'}), 400
    try:
        response = requests.get(url, timeout=TIMEOUT, stream=True)
        response.raise_for_status()
        if not _allowed(response.url):      # a redirect off Nintendo's servers
            return jsonify({'error': 'not allowed'}), 400
        data = response.raw.read(MAX_IMAGE + 1, decode_content=True)
    except requests.RequestException as e:
        return jsonify({'error': str(e)}), 502
    if len(data) > MAX_IMAGE or not _reencode(data):
        return jsonify({'error': 'not an image'}), 400
    kind = response.headers.get('Content-Type', 'image/jpeg').split(';')[0]
    return Response(data, mimetype=kind if kind.startswith('image/') else 'image/jpeg',
                    headers={'Cache-Control': 'private, max-age=3600'})


def _reencode(data):
    """The image as JPEG bytes (upright, at most MAX_SIDE a side), or None when Pillow
    can't read it."""
    try:
        with Image.open(io.BytesIO(data)) as picture:
            if picture.width * picture.height > MAX_PIXELS:
                return None
            picture.load()
            picture = ImageOps.exif_transpose(picture)
            if picture.mode in ('RGBA', 'LA', 'P'):
                # JPEG keeps no transparency: shown on white, as the console shows icons.
                rgba = picture.convert('RGBA')
                flat = Image.new('RGB', rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.split()[-1])
                picture = flat
            picture = picture.convert('RGB')
            picture.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
    out = io.BytesIO()
    picture.save(out, 'JPEG', quality=92, optimize=True)
    return out.getvalue()


def _custom(title_id):
    return titledb.store.list_overrides(SOURCE_CUSTOM).get(title_id) or {}


def _save_custom(title_id, record):
    record = {k: v for k, v in record.items() if k != 'id' and v not in (None, '')}
    if record:
        titledb.store.set_override(title_id, record, source=SOURCE_CUSTOM)
    else:
        titledb.store.delete_override(title_id, source=SOURCE_CUSTOM)


@covers_blueprint.post('/api/titles/<title_id>/cover')
@access_required('admin')
def save(title_id):
    """The cropped image (multipart `image`) as the game's cover."""
    title_id = _title_id(title_id)
    upload = request.files.get('image')
    if not title_id or upload is None:
        return jsonify({'success': False, 'error': 'missing'}), 400
    data = upload.read(MAX_IMAGE + 1)
    jpeg = _reencode(data) if len(data) <= MAX_IMAGE else None
    if not jpeg:
        return jsonify({'success': False, 'error': 'not an image'}), 400
    filename, _size = media.store_bytes(media.ICON, jpeg)
    url = media.url_for(title_id, media.ICON, 0, media.CLIENT, filename)
    record = _custom(title_id)
    record['iconUrl'] = url
    _save_custom(title_id, record)
    return jsonify({'success': True, 'url': url})


@covers_blueprint.delete('/api/titles/<title_id>/cover')
@access_required('admin')
def remove(title_id):
    """Back to titledb's cover (or the file's): the rest of the edit stays."""
    title_id = _title_id(title_id)
    if not title_id:
        return jsonify({'success': False}), 400
    record = _custom(title_id)
    record.pop('iconUrl', None)
    _save_custom(title_id, record)
    return jsonify({'success': True})

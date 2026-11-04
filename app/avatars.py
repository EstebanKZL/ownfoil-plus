"""Profile pictures (My account): one of the gallery's avatars, or an image the user
uploads.

The user row keeps `avatar` as "g:NN" for the gallery's NN.svg (static/img/avatars, drawn
here, nothing fetched) or "u:<file>" for an upload. An upload is opened with Pillow - so
only a real image gets through - turned upright, cropped square from its middle, shrunk
to SIZE and saved again as JPEG under data/avatars/, with a random name: what is served
is always the server's own re-encoding, never the bytes that were sent. Uploads are
served to signed-in users only.
"""
import io
import logging
import os
import re
import secrets

from flask import Blueprint, abort, jsonify, request, send_from_directory
from flask_login import current_user, login_required
from PIL import Image, ImageOps, UnidentifiedImageError

from constants import DATA_DIR
from db import db

logger = logging.getLogger('main')

avatars_blueprint = Blueprint('avatars', __name__)

AVATARS_DIR = os.path.join(DATA_DIR, 'avatars')
GALLERY = tuple(f'{n:02d}' for n in range(1, 13))
SIZE = 256
MAX_UPLOAD = 5 << 20              # a phone photo fits; it's shrunk to SIZE anyway
MAX_PIXELS = 40_000_000           # Pillow's own bomb guard is a warning at 89M
_UPLOAD_NAME = re.compile(r'^[0-9]+-[0-9a-f]{16}\.jpg$')


def avatar_url(user):
    """The picture's address for <img>, or None for no picture."""
    value = getattr(user, 'avatar', None) or ''
    if value.startswith('g:') and value[2:] in GALLERY:
        return f'/static/img/avatars/{value[2:]}.svg'
    if value.startswith('u:') and _UPLOAD_NAME.match(value[2:]):
        return f'/api/avatars/{value[2:]}'
    return None


@avatars_blueprint.app_template_global('avatar_url')
def _avatar_url_global(user):
    return avatar_url(user)


def _remove_upload(user):
    value = user.avatar or ''
    if value.startswith('u:') and _UPLOAD_NAME.match(value[2:]):
        try:
            os.remove(os.path.join(AVATARS_DIR, value[2:]))
        except OSError:
            pass


def _square(data):
    """The upload as SIZE x SIZE JPEG bytes, or None when it isn't an image Pillow reads."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_PIXELS:
                return None
            image.load()
            picture = ImageOps.exif_transpose(image)
            picture = ImageOps.fit(picture.convert('RGB'), (SIZE, SIZE), Image.LANCZOS)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None
    out = io.BytesIO()
    picture.save(out, 'JPEG', quality=88, optimize=True)
    return out.getvalue()


def _set(value):
    _remove_upload(current_user)
    current_user.avatar = value
    db.session.commit()
    return jsonify({'success': True, 'url': avatar_url(current_user)})


@avatars_blueprint.post('/api/account/avatar')
@login_required
def set_avatar():
    """An uploaded file (multipart "file"), or JSON {"gallery": "NN"} - null for none."""
    upload = request.files.get('file')
    if upload is None:
        choice = (request.get_json(silent=True) or {}).get('gallery')
        if choice is None:
            return _set(None)
        if choice not in GALLERY:
            return jsonify({'success': False, 'error': 'unknown_avatar'}), 400
        return _set(f'g:{choice}')
    data = upload.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        return jsonify({'success': False, 'error': 'too_large'}), 413
    picture = _square(data)
    if picture is None:
        return jsonify({'success': False, 'error': 'not_an_image'}), 400
    os.makedirs(AVATARS_DIR, exist_ok=True)
    name = f'{current_user.id}-{secrets.token_hex(8)}.jpg'
    with open(os.path.join(AVATARS_DIR, name), 'wb') as f:
        f.write(picture)
    return _set(f'u:{name}')


@avatars_blueprint.get('/api/avatars/<name>')
@login_required
def uploaded_avatar(name):
    if not _UPLOAD_NAME.match(name) or not os.path.isfile(os.path.join(AVATARS_DIR, name)):
        abort(404)
    return send_from_directory(AVATARS_DIR, name, mimetype='image/jpeg', max_age=3600)

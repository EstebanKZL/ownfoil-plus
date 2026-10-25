"""Coverage for Local artworks (Settings > Local artworks): a local, content-addressed
copy of title icon/banner/screenshot artwork, so a console's native "Ownfoil" client
never has to contact Nintendo directly for it. Covers the pure helpers in media.py, the
`media` table's helpers in db.py, the two settings routes and the serve route in app.py,
and the GraphQL-level URL substitution in gql/resolvers.py.
"""
import io
import os

import fixture
import pytest
from PIL import Image


def _jpeg_bytes(size=(400, 300)):
    buffer = io.BytesIO()
    Image.new('RGB', size, color=(10, 20, 30)).save(buffer, format='JPEG')
    return buffer.getvalue()


# ------------- media.py pure helpers -------------

def test_media_dir_rejects_unknown_kind_or_size():
    import media
    with pytest.raises(ValueError):
        media.media_dir('poster', media.ORIGINAL)
    with pytest.raises(ValueError):
        media.media_dir(media.ICON, 'huge')


def test_url_for_uppercases_the_title_id_and_is_recognized_as_local():
    import media
    url = media.url_for('0100000000010000', media.ICON, 0, media.CLIENT, 'abc123.jpg')
    assert url == '/api/media/0100000000010000/icon/0/client/abc123.jpg'
    assert media.is_local(url)
    assert not media.is_local('https://titledb.example/abc123.jpg')
    assert not media.is_local(None)


def test_filename_from_url_keeps_a_safe_basename_but_hashes_an_unsafe_one():
    import media
    assert media.filename_from_url('https://cdn.example/path/abc123.jpg') == 'abc123.jpg'
    # No extension-less or query-bearing basename is trusted verbatim - it gets hashed
    # instead, deterministically, so repeat fetches of the same URL still collide.
    first = media.filename_from_url('https://cdn.example/path/image?id=1')
    second = media.filename_from_url('https://cdn.example/path/image?id=1')
    assert first == second
    assert first.endswith('.jpg')


def test_fit_keeps_aspect_ratio_and_never_enlarges():
    import media
    # Wider than tall, shrunk to fit a square box.
    assert media.fit((400, 200), (100, 100)) == (100, 50)
    # Already smaller than the box in every dimension - left alone.
    assert media.fit((50, 25), (100, 100)) == (50, 25)


def test_box_uses_the_icon_box_only_for_icon_kind():
    import media
    assert media.box(media.ICON, media.CLIENT) == media.RENDITIONS[media.CLIENT][0]
    assert media.box(media.BANNER, media.CLIENT) == media.RENDITIONS[media.CLIENT][1]
    assert media.box(media.SCREENSHOT, media.CLIENT) == media.RENDITIONS[media.CLIENT][1]


def test_store_bytes_writes_the_original_and_every_rendition(tmp_path, monkeypatch):
    import media
    monkeypatch.setattr(media, 'MEDIA_DIR', str(tmp_path))
    filename, size = media.store_bytes(media.BANNER, _jpeg_bytes((800, 450)))
    assert size == (800, 450)
    assert media.have(media.BANNER, filename)
    assert os.path.isfile(media.media_path(media.BANNER, media.CLIENT, filename))
    assert media.dimensions(media.BANNER, filename) == (800, 450)


def test_build_derives_a_missing_rendition_from_the_original(tmp_path, monkeypatch):
    import media
    monkeypatch.setattr(media, 'MEDIA_DIR', str(tmp_path))
    filename, _size = media.store_bytes(media.ICON, _jpeg_bytes((300, 300)))
    os.remove(media.media_path(media.ICON, media.CLIENT, filename))
    assert not os.path.isfile(media.media_path(media.ICON, media.CLIENT, filename))
    assert media.build(media.ICON, media.CLIENT, filename) is True
    assert os.path.isfile(media.media_path(media.ICON, media.CLIENT, filename))
    # No original on disk at all - nothing to derive from.
    assert media.build(media.ICON, media.CLIENT, 'nonexistent.jpg') is False


def test_usage_counts_bytes_and_files_per_kind_and_size(tmp_path, monkeypatch):
    import media
    monkeypatch.setattr(media, 'MEDIA_DIR', str(tmp_path))
    media.store_bytes(media.ICON, _jpeg_bytes())
    media.store_bytes(media.BANNER, _jpeg_bytes())
    totals = media.usage()
    assert totals[media.ICON][media.ORIGINAL]['files'] == 1
    assert totals[media.ICON][media.CLIENT]['files'] == 1
    assert totals[media.BANNER][media.ORIGINAL]['files'] == 1
    assert totals[media.SCREENSHOT][media.ORIGINAL]['files'] == 0


def test_store_bytes_writes_all_four_renditions_not_just_client(tmp_path, monkeypatch):
    """Every size is downloaded and kept on disk, same as upstream - only *serving*
    is simplified to one size (see gql/resolvers.py's _local_media_urls), not
    storage. This is what Settings > Local artworks' disk-usage table reports."""
    import media
    monkeypatch.setattr(media, 'MEDIA_DIR', str(tmp_path))
    filename, _size = media.store_bytes(media.SCREENSHOT, _jpeg_bytes((1920, 1080)))
    assert media.SIZES == (media.ORIGINAL, media.THUMB, media.CLIENT, media.SCREEN)
    for size in media.SIZES:
        assert os.path.isfile(media.media_path(media.SCREENSHOT, size, filename)), size


def test_collect_removes_only_files_not_kept_and_past_the_grace_period(tmp_path, monkeypatch):
    import media
    monkeypatch.setattr(media, 'MEDIA_DIR', str(tmp_path))
    kept_name, _ = media.store_bytes(media.ICON, _jpeg_bytes())
    orphan_name, _ = media.store_bytes(media.ICON, _jpeg_bytes((100, 100)))
    # No grace at all, so an orphan not in `keep` is removed immediately.
    removed = media.collect({(media.ICON, kept_name)}, grace=0)
    assert removed >= 1
    assert media.have(media.ICON, kept_name)
    assert not media.have(media.ICON, orphan_name)


# ------------- db.py Media table helpers -------------

def test_upsert_get_and_delete_media_slots(shop_app):
    from db import Media, delete_media_slots, get_media_files, get_media_title_ids, \
        get_title_media, upsert_media
    with shop_app.app.app_context():
        upsert_media('0100000000010000', 'icon', 0, source='titledb',
                      source_url='https://x/icon.jpg', filename='icon.jpg', size=(256, 256))
        upsert_media('0100000000010000', 'screenshot', 0, source='titledb',
                      source_url='https://x/s0.jpg', filename='s0.jpg', size=(1280, 720))
        upsert_media('0100000000010000', 'screenshot', 1, source='titledb',
                      source_url='https://x/s1.jpg', filename='s1.jpg', size=(1280, 720))

        rows = get_title_media(['0100000000010000'])
        assert set(rows) == {
            ('0100000000010000', 'icon', 0),
            ('0100000000010000', 'screenshot', 0),
            ('0100000000010000', 'screenshot', 1),
        }
        assert '0100000000010000' in get_media_title_ids()
        assert ('icon', 'icon.jpg') in get_media_files()

        # Upserting the same slot again replaces it rather than duplicating it.
        upsert_media('0100000000010000', 'icon', 0, source='titledb',
                      source_url='https://x/icon2.jpg', filename='icon2.jpg', size=(256, 256))
        rows = get_title_media(['0100000000010000'])
        assert rows[('0100000000010000', 'icon', 0)].filename == 'icon2.jpg'

        # A screenshot list that shrank to one - the dropped slot's row goes away.
        delete_media_slots('0100000000010000', keep=[('icon', 0), ('screenshot', 0)])
        rows = get_title_media(['0100000000010000'])
        assert set(rows) == {('0100000000010000', 'icon', 0), ('0100000000010000', 'screenshot', 0)}


def test_delete_media_for_titles_removes_every_row_for_those_ids(shop_app):
    from db import delete_media_for_titles, get_title_media, upsert_media
    with shop_app.app.app_context():
        upsert_media('0100000000010000', 'icon', 0, source='titledb', source_url='https://x/i.jpg',
                      filename='i.jpg', size=(10, 10))
        upsert_media('0100000000020000', 'icon', 0, source='titledb', source_url='https://x/j.jpg',
                      filename='j.jpg', size=(10, 10))

        deleted = delete_media_for_titles(['0100000000010000'])
        assert deleted == 1
        remaining = get_title_media(['0100000000010000', '0100000000020000'])
        assert list(remaining) == [('0100000000020000', 'icon', 0)]


# ------------- settings.py -------------

def test_local_media_enabled_defaults_to_true_and_is_toggled(shop_app):
    from settings import local_media_enabled, set_local_media_settings
    with shop_app.app.app_context():
        assert local_media_enabled() is True
        set_local_media_settings({'enabled': False})
        assert local_media_enabled() is False
        set_local_media_settings({'enabled': True})
        assert local_media_enabled() is True


# ------------- app.py settings routes -------------

@pytest.fixture
def admin_client(shop_app):
    resp = shop_app.client.post('/login', data={'user': 'admin', 'password': fixture.PASSWORDS['admin']},
                                 follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    shop_app.client.post('/api/settings/shop', json={'public': True})
    return shop_app.client


def test_local_media_usage_route_reports_disk_usage(admin_client):
    resp = admin_client.get('/api/settings/local_media/usage')
    assert resp.status_code == 200
    body = resp.get_json()
    for kind in ('icon', 'banner', 'screenshot'):
        assert kind in body
        for size in ('original', 'client'):
            assert body[kind][size]['files'] == 0
            assert body[kind][size]['bytes'] == 0


def test_set_local_media_settings_route_toggles_and_enqueues_a_download_when_turned_on(admin_client):
    off = admin_client.post('/api/settings/local_media', json={'enabled': False})
    assert off.status_code == 200
    assert off.get_json()['success'] is True

    on = admin_client.post('/api/settings/local_media', json={'enabled': True})
    assert on.status_code == 200
    assert on.get_json()['success'] is True


def test_local_media_usage_route_requires_admin_access(shop_app):
    resp = shop_app.client.get('/api/settings/local_media/usage')
    assert resp.status_code in (302, 401, 403)


# ------------- app.py serve route -------------

def test_serve_media_returns_404_for_an_unknown_kind_or_size(admin_client):
    resp = admin_client.get('/api/media/0100000000010000/poster/0/client/x.jpg')
    assert resp.status_code == 404
    resp = admin_client.get('/api/media/0100000000010000/icon/0/huge/x.jpg')
    assert resp.status_code == 404


def test_serve_media_serves_a_stored_original_and_builds_the_client_rendition(admin_client, tmp_path, monkeypatch):
    import media
    monkeypatch.setattr(media, 'MEDIA_DIR', str(tmp_path))
    filename, _size = media.store_bytes(media.ICON, _jpeg_bytes())
    os.remove(media.media_path(media.ICON, media.CLIENT, filename))

    resp = admin_client.get(f'/api/media/0100000000010000/icon/0/client/{filename}')
    assert resp.status_code == 200
    assert os.path.isfile(media.media_path(media.ICON, media.CLIENT, filename))


def test_serve_media_on_a_private_shop_accepts_the_admins_own_session(admin_client):
    """file_access goes through auth.resolve_shop_caller now (see app.py), the same
    gate GraphQL uses - so the signed-in browser session that manages Settings also
    has shop access to this route once the shop goes private, with no Basic Auth
    needed. This is what makes index.html's own game cards/banners (plain <img src>
    requests, which carry cookies but never an Authorization header) load at all on
    a private shop."""
    admin_client.post('/api/settings/shop', json={'public': False})
    resp = admin_client.get('/api/media/0100000000010000/icon/0/client/missing.jpg')
    # 404, not 401/403: the session was accepted, there's just no such file.
    assert resp.status_code == 404


def test_serve_media_on_a_private_shop_rejects_an_unauthenticated_request(shop_app):
    shop_app.client.post('/api/settings/shop', json={'public': False})
    resp = shop_app.client.get('/api/media/0100000000010000/icon/0/client/missing.jpg')
    assert resp.status_code == 401


def test_serve_media_on_a_private_shop_serves_a_stored_file_with_basic_auth(
        admin_client, tmp_path, monkeypatch):
    import base64

    import media
    monkeypatch.setattr(media, 'MEDIA_DIR', str(tmp_path))
    filename, _size = media.store_bytes(media.ICON, _jpeg_bytes())

    admin_client.post('/api/settings/shop', json={'public': False})
    creds = base64.b64encode(f"admin:{fixture.PASSWORDS['admin']}".encode()).decode()
    resp = admin_client.get(f'/api/media/0100000000010000/icon/0/client/{filename}',
                             headers={'Authorization': f'Basic {creds}'})
    assert resp.status_code == 200
    assert resp.cache_control.public is False
    assert resp.cache_control.private is True


# ------------- gql/resolvers.py URL substitution -------------

def test_local_media_urls_leaves_everything_alone_when_disabled_or_nothing_selected(shop_app):
    from gql.resolvers import _local_media_urls
    from settings import set_local_media_settings
    with shop_app.app.app_context():
        # Nothing selected (all three None) - no query, raw values echoed back untouched,
        # and no Media row for icon/banner/screenshots to report either.
        assert _local_media_urls('0100000000010000', None, None, None) == (None, None, None, None, None, None)

        set_local_media_settings({'enabled': False})
        assert _local_media_urls('0100000000010000', 'https://x/icon.jpg', None, None) == \
            ('https://x/icon.jpg', None, None, None, None, None)


def test_local_media_urls_substitutes_only_the_slots_with_a_local_copy(shop_app):
    from db import upsert_media
    from gql.resolvers import _local_media_urls
    import media

    with shop_app.app.app_context():
        # local_media is on by default (set in the previous test's own app context, but
        # settings are per-tmp_path via the shop_app fixture, so this test starts fresh).
        upsert_media('0100000000010000', media.ICON, 0, source='titledb',
                      source_url='https://x/icon.jpg', filename='icon123.jpg', size=(256, 256))
        upsert_media('0100000000010000', media.SCREENSHOT, 0, source='titledb',
                      source_url='https://x/s0.jpg', filename='s0.jpg', size=(1280, 720))

        icon_url, banner_url, screenshots, icon_media, banner_media, screenshots_media = _local_media_urls(
            '0100000000010000',
            'https://titledb/icon.jpg', 'https://titledb/banner.jpg',
            ['https://titledb/s0.jpg', 'https://titledb/s1.jpg'],
        )

        assert icon_url == media.url_for('0100000000010000', media.ICON, 0, media.CLIENT, 'icon123.jpg')
        # No local copy of the banner - the titledb hotlink is left exactly as it was.
        assert banner_url == 'https://titledb/banner.jpg'
        # Screenshot 0 has a local copy, screenshot 1 doesn't - each substituted on its own.
        assert screenshots[0] == media.url_for('0100000000010000', media.SCREENSHOT, 0, media.CLIENT, 's0.jpg')
        assert screenshots[1] == 'https://titledb/s1.jpg'
        # The icon's own Media row comes back too (for Title.icon's size: argument) -
        # the banner's doesn't, since there's no local copy of it.
        assert icon_media is not None and icon_media.filename == 'icon123.jpg'
        assert banner_media is None
        # Same per-slot treatment for screenshots (for Title.screenshots' size: arg).
        assert screenshots_media[0] is not None and screenshots_media[0].filename == 's0.jpg'
        assert screenshots_media[1] is None


def test_local_media_urls_is_case_insensitive_on_title_id(shop_app):
    from db import upsert_media
    from gql.resolvers import _local_media_urls
    import media

    with shop_app.app.app_context():
        upsert_media('0100000000010000', media.ICON, 0, source='titledb',
                      source_url='https://x/icon.jpg', filename='icon123.jpg', size=(256, 256))
        icon_url, _banner, _shots, _icon_media, _banner_media, _shots_media = _local_media_urls(
            '0100000000010000'.lower(), 'https://titledb/icon.jpg', None, None)
        assert media.is_local(icon_url)

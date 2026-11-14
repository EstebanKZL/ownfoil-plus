"""A game's cover chosen in Edit: found in the eShop, cropped in the browser and saved
as the title's user-authored icon - the server's own re-encoding, never the bytes sent."""
import io

import pytest
from PIL import Image

import covers
import fixture
import titledb

TITLE = '0100000000010000'


@pytest.fixture
def admin(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code in (302, 303)
    return shop_app.client


def _png(size=(300, 200), mode='RGBA'):
    out = io.BytesIO()
    Image.new(mode, size, (200, 30, 30, 128) if mode == 'RGBA' else (200, 30, 30)).save(out, 'PNG')
    return out.getvalue()


def test_a_cropped_cover_is_saved_and_given_back(admin, shop_app, monkeypatch):
    stored = []
    monkeypatch.setattr(covers.media, 'store_bytes', lambda kind, data: stored.append(data) or ('c0ffee.jpg', (300, 200)))
    resp = admin.post(f'/api/titles/{TITLE}/cover',
                      data={'image': (io.BytesIO(_png()), 'cover.png')}, content_type='multipart/form-data')
    body = resp.get_json()
    assert body['success'] and body['url'] == f'/api/media/{TITLE}/icon/0/client/c0ffee.jpg'
    assert stored[0][:2] == b'\xff\xd8'      # re-encoded as JPEG (transparency on white)
    with shop_app.app.app_context():
        assert titledb.store.list_overrides()[TITLE]['iconUrl'] == body['url']
        # Text edits keep it; "Use the original" drops it and nothing else.
        titledb.store.set_override(TITLE, {'iconUrl': body['url'], 'name': 'Mine'})
    assert admin.delete(f'/api/titles/{TITLE}/cover').get_json()['success']
    with shop_app.app.app_context():
        record = titledb.store.list_overrides()[TITLE]
    assert 'iconUrl' not in record and record['name'] == 'Mine'


def test_only_a_real_image_is_saved(admin):
    resp = admin.post(f'/api/titles/{TITLE}/cover',
                      data={'image': (io.BytesIO(b'<svg>not a picture</svg>'), 'x.png')},
                      content_type='multipart/form-data')
    assert resp.status_code == 400


def test_the_image_proxy_reads_only_from_nintendo(admin):
    assert admin.get('/api/covers/image?url=http://127.0.0.1/x.jpg').status_code == 400
    assert admin.get('/api/covers/image?url=https://evil.example/x.jpg').status_code == 400
    assert admin.get('/api/covers/image?url=http://www.nintendo.com/x.jpg').status_code == 400   # https only
    assert covers._allowed('https://img-eshop.cdn.nintendo.net/i/abc.jpg')
    assert covers._allowed('https://www.nintendo.com/eu/media/x.jpg')
    assert not covers._allowed('https://nintendo.com.evil.example/x.jpg')


def test_the_eshop_search_asks_for_the_right_console(admin, monkeypatch):
    asked = {}

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {'response': {'docs': [
                {'title': 'Game', 'image_url_sq_s': 'https://www.nintendo.com/eu/a.jpg'},
                {'title': 'Elsewhere', 'image_url_sq_s': 'https://evil.example/b.jpg'}]}}

    def get(url, timeout, params):
        asked.update(params)
        return Reply()
    monkeypatch.setattr(covers.requests, 'get', get)
    body = admin.get('/api/covers/search?q=game&switch2=1').get_json()
    assert 'playable_on_txt:BEE' in asked['fq']
    assert body['results'] == [{'title': 'Game', 'image': 'https://www.nintendo.com/eu/a.jpg'}]
    admin.get('/api/covers/search?q=game')
    assert 'playable_on_txt:HAC' in asked['fq']


def test_covers_are_for_admins_only(shop_app):
    shop_app.client.post("/login", data={"user": "shopper", "password": fixture.PASSWORDS["shopper"]})
    assert shop_app.client.post(f'/api/titles/{TITLE}/cover').status_code in (302, 401, 403)
    assert shop_app.client.get('/api/covers/search?q=x').status_code in (302, 401, 403)


class _Redirect:
    """A Nintendo URL answering with a redirect to somewhere else."""
    def __init__(self, location):
        self.status_code = 302
        self.is_redirect = True
        self.headers = {'Location': location}

    def close(self):
        pass


def test_the_image_proxy_never_follows_a_redirect_off_nintendo(admin, monkeypatch):
    asked = []

    def get(url, **kwargs):
        asked.append(url)
        assert kwargs.get('allow_redirects') is False
        return _Redirect('http://127.0.0.1:8465/admin')

    monkeypatch.setattr(covers.requests, 'get', get)
    resp = admin.get('/api/covers/image?url=https://img-eshop.cdn.nintendo.net/i/abc.jpg')
    assert resp.status_code == 400
    # The internal address was never requested: only the Nintendo URL was.
    assert asked == ['https://img-eshop.cdn.nintendo.net/i/abc.jpg']


def test_the_image_proxy_stops_after_a_few_redirects(admin, monkeypatch):
    asked = []

    def get(url, **kwargs):
        asked.append(url)
        return _Redirect('https://img-eshop.cdn.nintendo.net/i/next.jpg')

    monkeypatch.setattr(covers.requests, 'get', get)
    assert admin.get('/api/covers/image?url=https://img-eshop.cdn.nintendo.net/i/abc.jpg').status_code == 400
    assert len(asked) <= covers.MAX_REDIRECTS + 1

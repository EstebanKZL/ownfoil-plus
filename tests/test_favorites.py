"""Favourites: each user's own starred games and the Library's filter for them."""
from pathlib import Path

import fixture
import pytest

from db import Favorite

ROOT = Path(__file__).resolve().parent.parent
GAME_ID = "0100000000010000"


def _login(shop_app, user):
    resp = shop_app.client.post("/login", data={"user": user, "password": fixture.PASSWORDS[user]})
    assert resp.status_code == 302
    return shop_app.client


def test_migration_adds_the_favorite_table():
    text = (ROOT / 'app/migrations/versions/d4e5f6a7b8c0_add_favorites.py').read_text(encoding='utf-8')
    assert "down_revision = 'c3d4e5f6a7b9'" in text
    assert "'favorite'" in text and 'uq_favorite_user_title' in text


def test_api_needs_a_signed_in_user(shop_app):
    assert shop_app.client.get('/api/favorites').status_code in (302, 401)


def test_each_user_keeps_their_own_list(shop_app):
    client = _login(shop_app, "shopper")
    assert client.post('/api/favorites', json={'title_id': GAME_ID.lower()}).get_json()['success']
    assert client.post('/api/favorites', json={'title_id': GAME_ID}).status_code == 200   # twice: one row
    assert client.get('/api/favorites').get_json() == {'title_ids': [GAME_ID]}
    assert client.post('/api/favorites', json={'title_id': 'nope'}).status_code == 400
    with shop_app.app.app_context():
        assert Favorite.query.count() == 1

    gql = '{ apps(groupByAppId: true, appType: [BASE], favorite: true, page: 1, pageSize: 50) { total items { appId } } }'
    data = client.post('/api/graphql', json={'query': gql}).get_json()['data']['apps']
    assert data['total'] == 1 and data['items'][0]['appId'] == GAME_ID

    client.get('/logout')
    admin = _login(shop_app, "admin")
    assert admin.get('/api/favorites').get_json() == {'title_ids': []}
    data = admin.post('/api/graphql', json={'query': gql}).get_json()['data']['apps']
    assert data['total'] == 0

    admin.get('/logout')
    client = _login(shop_app, "shopper")
    assert client.delete(f'/api/favorites/{GAME_ID}').status_code == 200
    assert client.get('/api/favorites').get_json() == {'title_ids': []}


def test_resolver_filters_by_the_callers_own_favourites():
    from gql.resolvers import _favorite_clause

    class Ctx:
        user = type('U', (), {'id': 7})()

    where, params = [], {}
    _favorite_clause(Ctx(), True, "ot.title_id", where, params)
    assert params == {'fav_user': 7}
    assert where[0].startswith('EXISTS') and 'fv.user_id = :fav_user' in where[0]

    where, params = [], {}
    _favorite_clause(Ctx(), False, "ot.title_id", where, params)
    assert where[0].startswith('NOT EXISTS')


def test_anonymous_caller_has_no_favourites():
    from gql.resolvers import _favorite_clause

    class Ctx:
        user = None

    where, params = [], {}
    _favorite_clause(Ctx(), True, "ot.title_id", where, params)
    assert where == ["0"] and params == {}


def test_library_page_has_the_star_and_the_pill():
    js = (ROOT / 'app/static/js/library.js').read_text(encoding='utf-8')
    assert 'function favoriteButton(game)' in js
    assert "favorite: onlyFavorites || null" in js and 'console: activeConsole || null' in js
    assert '/api/favorites' in js
    html = (ROOT / 'app/templates/index.html').read_text(encoding='utf-8')
    assert 'CAN_FAVORITE' in html and 'id="favoriteOnly"' in html and 'id="libraryPills"' not in html


def test_a_star_changes_the_cached_answer(shop_app):
    client = _login(shop_app, "shopper")
    gql = '{ apps(groupByAppId: true, appType: [BASE], favorite: true, page: 1, pageSize: 5) { total } }'
    first = client.post('/api/graphql', json={'query': gql})
    client.post('/api/favorites', json={'title_id': GAME_ID})
    second = client.post('/api/graphql', json={'query': gql}, headers={'If-None-Match': first.headers['ETag']})
    assert second.status_code == 200
    assert second.get_json()['data']['apps']['total'] == 1

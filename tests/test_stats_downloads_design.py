"""Phase 4, part D: the Statistics page's downloads in the page's own look - a section
title with its icon, the stat tiles, one card per list - with ranks and share bars, the
users' profile pictures, the clients' icons and the game covers lined up."""
import datetime
import os
import re

import fixture
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _function_body(js, name):
    start = js.index(f"function {name}(")
    depth, i = 0, js.index(") {", start) + 2
    while True:
        depth += {"{": 1, "}": -1}.get(js[i], 0)
        i += 1
        if depth == 0:
            return js[start:i]


@pytest.fixture
def admin_client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]})
    assert resp.status_code == 302
    return shop_app.client


def _section(html):
    start = html.index('id="downloadsSection"')
    return html[start:html.index('id="duplicatesSection"')]


def test_the_section_has_the_pages_title_and_no_bare_headings(admin_client):
    section = _section(admin_client.get("/admin/stats").get_data(as_text=True))
    assert re.search(r'<h3 class="stats-section__title"><i class="bi bi-download"', section)
    assert "<h4" not in section and "<h5" not in section


def test_each_list_is_its_own_card(admin_client):
    section = _section(admin_client.get("/admin/stats").get_data(as_text=True))
    assert len(re.findall(r'class="dl-card[ "]', section)) == 5     # per day, top, users, clients, recent
    for list_id in ("downloadTopTitles", "downloadByUser", "downloadByClient", "downloadRecent"):
        assert re.search(rf'<ul class="dash-list[^"]*" id="{list_id}"', section), list_id
    assert section.count('class="dl-card__title"') == 5


def test_the_figures_are_stat_tiles():
    body = _function_body(_read("app", "static", "js", "stats.js"), "renderDownloads")
    assert "stat-tile stat-tile--" in body and "stat-tile__icon" in body


def test_the_lists_carry_ranks_bars_pictures_and_chips():
    body = _function_body(_read("app", "static", "js", "stats.js"), "renderDownloads")
    assert "rank:" in body and "pct:" in body
    assert "avatarUrl: u.avatar_url" in body
    assert "chips:" in body and "r.user_avatar" in body
    row = _function_body(_read("app", "static", "js", "title-list.js"), "titleListRow")
    for part in ("dash-list__rank", "dash-list__bar", "dash-list__chip", "avatarUrl"):
        assert part in row, part


def test_the_api_gives_each_users_picture(shop_app, admin_client):
    from db import DownloadEvent, User, db
    with shop_app.app.app_context():
        db.session.get(User, User.query.filter_by(user="shopper").one().id).avatar = "g:02"
        db.session.add(DownloadEvent(downloaded_at=datetime.datetime.utcnow(), filename="a.nsp",
                                     user="shopper", client="sphaira"))
        db.session.commit()
    data = admin_client.get("/api/stats/downloads").get_json()
    assert data["by_user"][0] == {"user": "shopper", "count": 1, "avatar_url": "/static/img/avatars/02.svg"}
    assert data["recent"][0]["user_avatar"] == "/static/img/avatars/02.svg"


def test_the_new_styles_use_tokens_only():
    css = _read("app", "static", "style.css")
    for selector in (".dl-card", ".dl-grid", ".dash-list__rank", ".dash-list__bar", ".dash-list__chip"):
        rule = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert rule, selector
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", rule.group(1)), selector


def test_a_year_of_days_fits_the_chart():
    """Seen at 365 days: the bars' minimum widths and gaps added up past the page width."""
    css = _read("app", "static", "style.css")
    chart = re.search(r"\.download-chart \{([^}]*)\}", css).group(1)
    bar = re.search(r"\.download-bar \{([^}]*)\}", css).group(1)
    assert "overflow: hidden" in chart and "min-width: 0" in bar
    assert re.search(r"\.download-chart\.is-dense \{[^}]*gap: 0", css)
    body = _function_body(_read("app", "static", "js", "stats.js"), "renderDownloads")
    assert "classList.toggle('is-dense'" in body

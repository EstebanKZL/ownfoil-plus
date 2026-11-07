"""Settings keeps its long lists in dialogs - users, library paths, backups and the
artwork disk usage - opened by a "View ... (n)" button, so the page doesn't grow with
them. An edit or delete opened from a list comes back to it."""
import os
import re

import fixture
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")


@pytest.fixture
def settings_html(shop_app):
    client = shop_app.client
    assert client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]}).status_code == 302
    return client.get("/admin/settings").get_data(as_text=True)


def _dialog(html, dialog_id):
    start = html.index(f'id="{dialog_id}"')
    return html[start:html.index('class="modal fade', start + 10) if 'class="modal fade' in html[start + 10:] else len(html)]


@pytest.mark.parametrize("dialog, inner, button", [
    ("usersDialog", 'id="userTable"', "usersViewBtn"),
    ("pathsDialog", 'id="pathsTable"', "pathsViewBtn"),
    ("backupsDialog", 'id="backupsTable"', "backupsViewBtn"),
    ("mediaUsage", 'id="mediaUsageTable"', "mediaViewBtn"),
])
def test_each_list_lives_in_its_dialog(settings_html, dialog, inner, button):
    assert re.search(rf'<div class="modal fade list-dialog" id="{dialog}"', settings_html)
    assert inner in _dialog(settings_html, dialog)
    assert re.search(rf'id="{button}" data-bs-toggle="modal" data-bs-target="#{dialog}"', settings_html)


def test_the_view_buttons_show_how_many_and_lists_come_back():
    js = open(os.path.join(ROOT, "app", "static", "js", "settings.js"), encoding="utf-8").read()
    assert "$('#usersViewBtn span').text(I18N.usersView" in js
    assert "$('#pathsViewBtn span').text(I18N.pathsView" in js
    assert "$('#backupsViewBtn span').text(I18N.backupsView" in js
    assert "$('#mediaUsage').on('show.bs.modal', fillMediaUsage)" in js
    assert "listDialogToReopen" in js and "'editUserModal', 'deleteUserModal', 'deletePathModal'" in js

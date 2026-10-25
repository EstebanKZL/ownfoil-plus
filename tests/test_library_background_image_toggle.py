"""Coverage for the new Settings > Library > Organizer > "Show game background image in
Library list view" toggle (library.management.organizer.show_background_image).

Requested directly: on by default (today's behavior unchanged), and when turned off it
must stop `.list-banner-strip` (the full-card background art behind each row in the
Library page's List view) from being drawn, while `.list-cover` (the small cover icon
on the left of each row) keeps showing regardless. Scoped to that one view only - the
Card grid view and a game's own detail popup are untouched, since neither one pairs a
background with a separate icon the way the List view does.
"""
import fixture
import pytest


@pytest.fixture
def client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def test_defaults_to_on_for_an_install_with_no_settings_yaml_yet(client):
    """Existing behavior must not change for anyone who never touches this new setting -
    confirmed both ways: the Library page's own JS const, and the Settings checkbox."""
    html = client.get("/").get_data(as_text=True)
    assert "const SHOW_GAME_BACKGROUND_IMAGE = true;" in html

    settings_html = client.get("/admin/settings").get_data(as_text=True)
    assert '<input type="checkbox" class="form-check-input" id="showBackgroundImageCheck">' in settings_html


def test_turning_it_off_persists_and_flips_the_librarys_own_js_const(client):
    resp = client.post("/api/settings/library/management", json={
        "organizer": {
            "enabled": False, "remove_empty_folders": False, "windows_compatible": False,
            "clean_names": False, "show_background_image": False,
            "name_region": "", "name_language": "",
            "templates": {"base": "{titleName}", "update": "{titleName}",
                          "dlc": "{titleName}", "multi": "{titleName}"},
        },
    })
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    html = client.get("/").get_data(as_text=True)
    assert "const SHOW_GAME_BACKGROUND_IMAGE = false;" in html


def test_get_settings_round_trips_the_new_field(client):
    client.post("/api/settings/library/management", json={
        "organizer": {
            "enabled": False, "remove_empty_folders": False, "windows_compatible": False,
            "clean_names": False, "show_background_image": False,
            "name_region": "", "name_language": "",
            "templates": {"base": "{titleName}", "update": "{titleName}",
                          "dlc": "{titleName}", "multi": "{titleName}"},
        },
    })
    data = client.get("/api/settings").get_json()
    assert data["library"]["management"]["organizer"]["show_background_image"] is False


def test_the_list_view_skips_the_banner_strip_only_when_the_setting_reads_false(client):
    """Confirms the gate sits on .list-banner-strip specifically, and that .list-cover
    (the icon) has no such gate at all - string-level check on the template's own JS
    source, the same pattern this fork's other template tests already use."""
    html = client.get("/").get_data(as_text=True)
    assert "if (t.titleId && t.bannerUrl && SHOW_GAME_BACKGROUND_IMAGE) {" in html
    assert "if (t.titleId && t.iconUrl) {" in html  # .list-cover: no SHOW_GAME_BACKGROUND_IMAGE check


def test_the_list_view_js_toggles_the_no_banner_shadow_class_with_the_same_flag(client):
    """The other half of the same request: once the banner's gone there's nothing left
    for the heavy text-shadow to fight for contrast against, so renderListView also
    toggles a .no-banner class (lightened in style.css) using the exact same flag -
    never out of sync with whether the banner itself is drawn."""
    html = client.get("/").get_data(as_text=True)
    assert ".toggleClass('no-banner', !SHOW_GAME_BACKGROUND_IMAGE)" in html


def test_no_banner_css_class_lightens_but_does_not_remove_the_text_shadow(client):
    import os
    import re
    css_path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "style.css")
    with open(css_path) as f:
        css = f.read()
    m = re.search(r"\.list-card-body\.no-banner\s*,\s*\.list-card-body\.no-banner \.icon-btn\s*\{(.*?)\}",
                  css, re.DOTALL)
    assert m, ".list-card-body.no-banner rule not found in style.css"
    rule = m.group(1)
    assert "text-shadow" in rule
    # Lighter than the full-banner shadow's .85/.5 alpha values - not just a copy of it.
    assert re.search(r"rgba\(0,\s*0,\s*0,\s*\.35\)", rule)


def test_setting_label_and_help_are_translated(client):
    html = client.get("/admin/settings").get_data(as_text=True)
    assert "Show game background image in Library list view" in html

    client.set_cookie("ownfoil_lang", "es")
    html = client.get("/admin/settings").get_data(as_text=True)
    assert "Mostrar imagen de fondo del juego en la vista de lista de la Biblioteca" in html

"""Coverage for the first round of translating the Settings page
(app/templates/settings.html): the alert banners, the Authentication section, and the
top-level section headers throughout the rest of the page - not yet the deep-dive
help text within each section, which is a separate follow-up pass.
"""
import re

import fixture
import pytest


@pytest.fixture
def client(shop_app):
    import json
    import os
    from constants import TITLEDB_DIR
    os.makedirs(TITLEDB_DIR, exist_ok=True)
    with open(os.path.join(TITLEDB_DIR, "languages.json"), "w") as f:
        json.dump({"US": ["en"]}, f)

    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def test_settings_page_renders_in_english_by_default(client):
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Authentication" in html
    assert "List of users:" in html
    assert "Add new user" in html
    assert ">Library<" in html
    assert "File compression" in html
    assert "File verification" in html
    assert ">Organizer<" in html
    assert ">Titles<" in html
    assert ">Shop<" in html
    assert "Clients" in html
    assert ">Scheduler<" in html
    assert ">Workers<" in html


def test_settings_page_renders_in_spanish(client):
    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Autenticación" in html
    assert "Lista de usuarios:" in html
    assert "Agregar usuario" in html
    assert ">Biblioteca<" in html
    assert "Compresión de archivos" in html
    assert "Verificación de archivos" in html
    assert ">Organizador<" in html
    assert ">Títulos<" in html
    assert ">Tienda<" in html
    assert "Clientes" in html
    assert ">Programación<" in html
    assert ">Procesos<" in html


def test_the_missing_admin_alert_is_translated(client):
    """This alert is conditional (admin_account_created == false) - the fixture's
    admin user already exists, so exercise it by forcing the condition instead of
    relying on account state."""
    with client.application.test_request_context():
        from app import render_template
        html = render_template("settings.html", title="Settings",
                               languages_from_titledb={}, admin_account_created=False)
    assert "¡Falta la cuenta de administrador!" not in html  # default language is English here
    assert "Missing admin account!" in html


def test_the_missing_admin_alert_is_translated_in_spanish(client):
    with client.application.test_request_context(headers={"Cookie": "ownfoil_lang=es"}):
        from app import render_template
        html = render_template("settings.html", title="Settings",
                               languages_from_titledb={}, admin_account_created=False)
    assert "¡Falta la cuenta de administrador!" in html


def test_dynamic_user_table_permission_labels_are_translated(client):
    """Shop/Backup/Admin next to each user row are built in JS from the I18N object,
    not hardcoded - confirm the object carries the Spanish values through render."""
    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)

    assert "const I18N = {" in html
    assert '"Tienda"' in html    # shop
    assert '"Administrador"' in html  # admin


def test_detailed_section_content_is_translated_in_english(client):
    """Round 2 of Settings i18n: the labels/help text within each section, not just
    the section headers - compression, verification, organizer, templates, titles,
    shop, clients, scheduler, workers."""
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)

    assert "Compress files" in html
    assert "Verify files" in html
    assert "Signature only" in html
    assert "Enable organizer" in html
    assert "Clean names (remove" in html
    assert "Naming language" in html
    assert "Same as library language" in html
    assert "Base template:" in html
    assert "Library Region:" in html
    assert "Console Keys file:" in html
    assert "Shop URL:" in html
    assert "Public shop" in html
    assert "Tinfoil" in html
    assert "Encrypt shop" in html
    assert "TitleDB update interval:" in html
    assert "Worker count:" in html
    assert "Max concurrent I/O tasks:" in html


def test_detailed_section_content_is_translated_in_spanish(client):
    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)

    assert "Comprimir archivos" in html
    assert "Verificar archivos" in html
    assert "Solo firma" in html
    assert "Activar organizador" in html
    assert "Limpiar nombres (quitar" in html
    assert "Idioma de organización" in html
    assert "Igual que el idioma de la biblioteca" in html
    assert "Plantilla de juego base:" in html
    assert "Región de la biblioteca:" in html
    assert "Archivo de claves de consola:" in html
    assert "URL de la tienda:" in html
    assert "Tienda pública" in html
    assert "Cifrar tienda" in html
    assert "Intervalo de actualización de TitleDB:" in html
    assert "Cantidad de procesos:" in html
    assert "Máximo de tareas de E/S concurrentes:" in html


def test_settings_page_script_is_still_one_block(client):
    """Same regression class as the other pages' equivalent tests - re-checked here
    since this round added a second I18N-carrying script edit to the same file."""
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)

    script_blocks = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(script_blocks) == 1, (
        f"Expected exactly one inline <script>...</script> block, found {len(script_blocks)}")
    body = script_blocks[0]
    assert "const I18N = {" in body
    assert "function fillUserTable" in body
    assert "function importSettings" in body


def test_auto_resolve_duplicates_checkbox_is_present_and_translated(client):
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert 'id="autoResolveDuplicatesCheck"' in html
    assert "Automatically resolve duplicate files" in html

    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert "Resolver duplicados automáticamente" in html


def test_prefer_larger_on_tie_checkbox_is_present_and_translated(client):
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert 'id="preferLargerOnTieCheck"' in html
    assert "On a tie, prefer the larger file" in html

    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert "En caso de empate, preferir el archivo más grande" in html


def test_compression_preference_select_is_present_and_translated(client):
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert 'id="compressionPreferenceSelect"' in html
    assert "Prefer the compressed one (nsz/xcz)" in html
    assert "Prefer the uncompressed one (nsp/xci)" in html

    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert "Preferir la comprimida (nsz/xcz)" in html
    assert "Preferir la sin comprimir (nsp/xci)" in html


def test_workers_and_backup_sections_both_have_a_leading_divider(client):
    """Backup previously lacked the <hr class="hr-settings"> every other top-level
    section uses, making it look stuck onto Workers instead of its own section."""
    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)

    workers_idx = html.index("Procesos")
    backup_idx = html.index("Copia de seguridad")
    between = html[workers_idx:backup_idx]
    assert '<hr class="hr-settings">' in between, (
        "Expected a divider between Workers and Backup sections")


def test_web_clean_record_checkbox_is_present_and_translated(client):
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert 'id="webCleanRecordEnabledCheck"' in html
    assert "Enable cleaning records from Stats" in html

    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert "Habilitar limpieza de registros desde Estad" in html


def test_reset_library_tracking_section_is_present_and_translated(client):
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert 'id="resetLibraryModal"' in html
    assert 'id="resetLibraryConfirmInput"' in html
    assert 'id="resetLibraryConfirmBtn"' in html
    assert "Clean Library" in html
    assert "Type RESET below to confirm." in html
    assert "const RESET_LIBRARY_MUTATION" in html

    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert "Limpiar Biblioteca" in html
    assert "RESET" in html


def test_reset_library_confirm_button_starts_disabled(client):
    """The button must not be clickable until the exact phrase is typed - present in
    the initial markup as disabled, enabled only by the input's own JS handler."""
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    button_start = html.index('id="resetLibraryConfirmBtn"')
    button_tag = html[max(0, button_start - 200):button_start + 50]
    assert "disabled" in button_tag

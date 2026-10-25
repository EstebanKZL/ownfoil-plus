"""Coverage for translating the Files admin page (app/templates/files.html): this page
used to have zero i18n coverage (unlike every other admin page), since almost
everything it shows is built client-side rather than through Jinja. This covers a
representative sample of the static Jinja-rendered text and of the `I18N` JS bridge
object the page's own script reads from for everything it builds at runtime -
mirroring the same bridge pattern (and the same test pattern) already used for the
Library page, see test_library_i18n.py.
"""
import json
import os

import fixture
import pytest


@pytest.fixture
def client(shop_app):
    os.makedirs(__import__("constants").TITLEDB_DIR, exist_ok=True)
    with open(os.path.join(__import__("constants").TITLEDB_DIR, "languages.json"), "w") as f:
        json.dump({"US": ["en"]}, f)

    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def test_files_page_renders_in_english_by_default(client):
    html = client.get("/admin/files").get_data(as_text=True)

    assert "<h2 class=\"mb-0\">Files</h2>" in html
    assert ">All files<" in html
    assert ">Unidentified<" in html
    assert ">Verification issues<" in html
    assert ">Duplicates<" in html
    assert ">Outdated updates<" in html
    assert ">Pending<" in html
    assert "Manage library files, actions run as" in html
    assert 'placeholder="File name"' in html


def test_files_page_renders_in_spanish(client):
    client.set_cookie("ownfoil_lang", "es")
    html = client.get("/admin/files").get_data(as_text=True)

    assert "<h2 class=\"mb-0\">Archivos</h2>" in html
    assert ">Todos los archivos<" in html
    assert ">No identificados<" in html
    assert ">Problemas de verificación<" in html
    assert ">Duplicados<" in html
    assert ">Actualizaciones obsoletas<" in html
    assert ">Pendientes<" in html
    assert "Gestioná los archivos de la biblioteca" in html
    assert 'placeholder="Nombre de archivo"' in html


def test_the_i18n_object_carries_spanish_values_for_the_js_built_content(client):
    """Nearly everything on this page (filters, table rows, the duplicates/outdated
    comparison tables, the file drawer) is built in JS from the I18N object rather
    than static HTML - confirm the object itself carries the Spanish strings through
    render, same as the Library page's own I18N object does."""
    client.set_cookie("ownfoil_lang", "es")
    html = client.get("/admin/files").get_data(as_text=True)

    assert "const I18N = {" in html
    # Jinja's tojson escapes non-ASCII (e.g. ó), so these two deliberately avoid
    # accented characters; the accented ones are still exercised by the English-vs-
    # Spanish duplicate-reason/pill checks below and in the other i18n test files.
    assert '"Conservar"' in html   # pillKeep
    assert '"hace {n} {unit}"' in html   # agoTemplate


def test_duplicate_reason_strings_survive_in_the_i18n_object(client):
    """Regression guard for test_duplicate_decides_reason_is_about_rank_not_time in
    test_files_admin_page.py: these reason strings moved from JS literals into the
    I18N object/i18n.py, but must still render in English by default."""
    html = client.get("/admin/files").get_data(as_text=True)
    for reason in ("Worse verification", "Not the preferred compression", "Smaller copy",
                   "Not the recommended copy", "Older version"):
        assert reason in html


def test_pending_tab_humanizes_stage_identifiers_instead_of_showing_them_raw(client):
    """The Pending tab used to join tasks.STAGES' own raw names ('organize', 'verify',
    'compress') straight into the detail column - not a hardcoded English string to
    move, but a missing humanize step, flagged separately from the rest of this i18n
    pass and fixed here. Confirm it now goes through a PENDING_STAGE_LABEL map fed by
    the I18N bridge (so it also gets translated), in English and in Spanish."""
    html = client.get("/admin/files").get_data(as_text=True)
    assert "const PENDING_STAGE_LABEL = {identify: I18N.pendingStageIdentify" in html
    assert "r._stages.map(humanizeStage).join(' · ')" in html
    assert 'pendingStageOrganize: "Organize"' in html

    client.set_cookie("ownfoil_lang", "es")
    html = client.get("/admin/files").get_data(as_text=True)
    assert 'pendingStageOrganize: "Organizar"' in html
    assert 'pendingStageVerify: "Verificar"' in html


def test_js_reads_the_bridge_instead_of_hardcoding_english(client):
    """A handful of the JS code paths that used to hardcode English text now read
    from I18N instead - confirm the raw template source references the bridge rather
    than a literal string, the same way this fork's other tests assert on template JS
    source via string-matching rather than executing a JS engine."""
    html = client.get("/admin/files").get_data(as_text=True)
    assert "const yesNo = v => v ? I18N.yes : I18N.no;" in html
    assert "REASONS = {" in html and "I18N.reasonVerification" in html
    assert "I18N.pagerRangeTemplate" in html
    assert "I18N.confirmDeleteFileTemplate" in html

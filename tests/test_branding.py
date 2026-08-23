"""The app was rebranded from "Ownfoil" to "Ownfoil-Plus" across every user-facing
surface (page title, navbar, PWA manifest, Settings help text in both languages, setup
guide). Real technical identifiers - the titledb data source
(github.com/a1ex4/ownfoil/releases/download/titledb, a functional dependency, not
branding) and the project's own upstream GitHub repository - were deliberately left
untouched, since renaming them would either break a real download URL or point at a
GitHub location that doesn't exist for this fork.

This guards against the old name silently creeping back into any of the surfaces that
were renamed - it does not (and should not) assert anything about the technical
identifiers above, which are correctly left alone.
"""
import json
import os
import re

import fixture
import pytest


@pytest.fixture
def client(shop_app):
    resp = shop_app.client.post("/login", data={"user": "admin", "password": fixture.PASSWORDS["admin"]},
                                follow_redirects=False)
    assert resp.status_code in (302, 303), resp.get_data(as_text=True)
    return shop_app.client


def test_page_title_and_navbar_use_the_new_name(client):
    resp = client.get("/")
    html = resp.get_data(as_text=True)

    assert "Ownfoil-Plus" in html
    assert "<title>Ownfoil-Plus" in html or "<title>Ownfoil-Plus |" in html


def test_settings_help_text_uses_the_new_name_in_both_languages(client):
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert "Ownfoil-Plus" in html

    client.set_cookie("ownfoil_lang", "es")
    resp = client.get("/admin/settings")
    html = resp.get_data(as_text=True)
    assert "Ownfoil-Plus" in html


def test_setup_page_uses_the_new_name(client):
    resp = client.get("/setup")
    html = resp.get_data(as_text=True)
    assert "Ownfoil-Plus" in html


def test_pwa_manifest_uses_the_new_name():
    with open("app/static/favicon/site.webmanifest") as f:
        manifest = json.load(f)
    assert manifest["name"] == "Ownfoil-Plus"
    assert manifest["short_name"] == "Ownfoil-Plus"


def test_docker_image_is_published_under_the_new_dockerhub_repository():
    """The image is now published as estebankzl/ownfoil-plus, not the upstream
    a1ex4/ownfoil - checked everywhere it's actually built/pulled from
    (docker-compose.yml, the Helm chart's default values, and the GitHub Actions
    workflow that pushes to Docker Hub on release)."""
    root = os.path.join(os.path.dirname(__file__), "..")

    with open(os.path.join(root, "docker-compose.yml")) as f:
        compose = f.read()
    assert "estebankzl/ownfoil-plus" in compose
    assert "a1ex4/ownfoil" not in compose

    with open(os.path.join(root, "chart", "values.yaml")) as f:
        values = f.read()
    assert "repository: estebankzl/ownfoil-plus" in values

    with open(os.path.join(root, ".github", "workflows", "docker.yml")) as f:
        workflow = f.read()
    assert "images: estebankzl/ownfoil-plus" in workflow
    assert "a1ex4/ownfoil" not in workflow


def test_titledb_download_source_is_untouched_by_the_rebrand():
    """The one Docker/GitHub reference that must NEVER be renamed: this is where the
    app actually downloads titledb's game metadata from at runtime, a real functional
    dependency on the upstream project's GitHub releases - not branding. Repointing it
    at estebankzl/ownfoil-plus (which has no such release) would silently break every
    titledb update."""
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, "app", "constants.py")) as f:
        constants = f.read()
    assert "TITLEDB_RELEASE_URL = 'https://github.com/a1ex4/ownfoil/releases/download/titledb'" in constants


def test_no_bare_old_name_remains_in_the_renamed_templates(client):
    """A user-facing page must never show the bare old name once it's supposed to have
    been fully renamed - "Ownfoil-Plus" itself still contains "Ownfoil" as a substring,
    so this specifically looks for "Ownfoil" NOT immediately followed by "-Plus"."""
    for path, extra_cookies in [("/", {}), ("/admin/settings", {}), ("/setup", {})]:
        if extra_cookies:
            client.set_cookie(*extra_cookies)
        resp = client.get(path)
        html = resp.get_data(as_text=True)
        bare_matches = re.findall(r"Ownfoil(?!-Plus)", html)
        assert not bare_matches, f"{path} still has a bare 'Ownfoil' mention ({len(bare_matches)} time(s))"

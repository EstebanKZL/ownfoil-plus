"""Stage 1 quality/infrastructure: health endpoint and Docker HEALTHCHECK, a UI that
needs no CDN, CI gating the image build, the shop reporting its real version, and
Files.last_attempt getting the insert time instead of the import time.
"""
import os
import re

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


# --- health ------------------------------------------------------------------------

def test_health_is_ok_and_needs_no_login(shop_app):
    resp = shop_app.client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok", "database": "ok"}


def test_health_reports_a_database_failure(shop_app, monkeypatch):
    from db import db

    def broken(*args, **kwargs):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(db.session, "execute", broken)

    resp = shop_app.client.get("/api/health")
    assert resp.status_code == 503
    assert resp.get_json()["status"] == "error"


def test_dockerfile_has_a_healthcheck_on_the_health_endpoint():
    dockerfile = _read("Dockerfile")
    assert re.search(r"^HEALTHCHECK .*", dockerfile, re.M)
    assert "/api/health" in dockerfile


def test_helm_probes_use_the_health_endpoint():
    deploy = _read("chart", "templates", "deploy.yaml")
    assert deploy.count("path: /api/health") == 2


# --- offline UI --------------------------------------------------------------------

def test_base_template_loads_nothing_from_a_cdn():
    base = _read("app", "templates", "base.html")
    assert not re.search(r"(src|href)=\"https?://", base)
    assert "font-awesome" not in base


def test_every_static_asset_base_html_references_exists():
    base = _read("app", "templates", "base.html")
    for name in re.findall(r"url_for\('static', filename='([^']+)'\)", base):
        assert os.path.isfile(os.path.join(ROOT, "app", "static", *name.split("/"))), name


def test_bootstrap_icons_fonts_are_vendored_next_to_their_css():
    css = _read("app", "static", "vendor", "bootstrap-icons", "bootstrap-icons.min.css")
    for font in re.findall(r'url\("([^"?]+)', css):
        assert os.path.isfile(os.path.join(ROOT, "app", "static", "vendor", "bootstrap-icons", *font.split("/"))), font


def test_vendored_assets_are_served(shop_app):
    resp = shop_app.client.get("/static/vendor/bootstrap/bootstrap.min.css")
    assert resp.status_code == 200
    resp.close()


# --- CI ----------------------------------------------------------------------------

def test_tests_workflow_runs_pytest_and_is_reusable():
    workflow = yaml.safe_load(_read(".github", "workflows", "tests.yml"))
    triggers = workflow.get("on") or workflow.get(True)  # PyYAML reads a bare `on:` as True
    assert "workflow_call" in triggers and "pull_request" in triggers
    steps = workflow["jobs"]["pytest"]["steps"]
    assert any("pytest" in step.get("run", "") for step in steps)


def test_image_build_waits_for_the_tests():
    workflow = yaml.safe_load(_read(".github", "workflows", "docker.yml"))
    jobs = workflow["jobs"]
    assert jobs["tests"]["uses"] == "./.github/workflows/tests.yml"
    assert jobs["build-and-push"]["needs"] == "tests"


# --- version -----------------------------------------------------------------------

def test_app_version_falls_back_to_pyproject(monkeypatch):
    import tomllib

    import discovery
    from importlib.metadata import PackageNotFoundError

    def not_installed(name):
        raise PackageNotFoundError(name)
    monkeypatch.setattr(discovery, "_pkg_version", not_installed)

    expected = tomllib.loads(_read("pyproject.toml"))["project"]["version"]
    assert discovery._app_version() == expected


def test_dockerfile_ships_pyproject_for_the_version():
    assert "COPY ./pyproject.toml /app/pyproject.toml" in _read("Dockerfile")


# --- tracked placeholder -----------------------------------------------------------

def test_titledb_languages_placeholder_is_tracked_by_git():
    """Settings reads it before the first titledb download; CI and the Docker image
    only have what git tracks, and `/app/data/` in .gitignore once dropped it."""
    import shutil
    import subprocess

    import pytest
    if shutil.which("git") is None or not os.path.isdir(os.path.join(ROOT, ".git")):
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "ls-files", "app/data/titledb/languages.json"],
                             cwd=ROOT, capture_output=True, text=True).stdout.strip()
    assert tracked == "app/data/titledb/languages.json"


# --- Files.last_attempt --------------------------------------------------------------

def test_last_attempt_default_is_evaluated_per_insert():
    from db import Files
    default = Files.__table__.c.last_attempt.default
    # A callable default runs per insert; a plain value would be the module's import time.
    assert default.is_callable

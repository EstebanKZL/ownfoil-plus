"""Housekeeping (6.2.5.47): dead styles and strings left behind by the redesign, links
between the docs, and the Ownfoil-Plus name where people see it."""
import os
import re
import subprocess

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _app_sources():
    """Templates, scripts and Python modules of the app, without the vendored libraries."""
    out = {}
    for base, _, files in os.walk(os.path.join(ROOT, "app")):
        if "vendor" in base or "__pycache__" in base:
            continue
        for name in files:
            if name.endswith((".html", ".js", ".py")):
                path = os.path.join(base, name)
                with open(path, encoding="utf-8", errors="ignore") as f:
                    out[os.path.relpath(path, ROOT)] = f.read()
    return out


def test_the_old_library_card_and_details_modal_styles_are_gone():
    """The stage 2 cards and the stage 3 game page replaced them; nothing renders these."""
    css = _read("app", "static", "style.css")
    for selector in (".game-info", ".game-tag", ".tags-container", ".card-img", "@container game-card",
                     ".metadata-detail-", "#metadataScreenshotCarousel", ".files-suggest"):
        assert selector not in css, selector
    assert not css.startswith("/* body {"), "commented-out leftover at the top of style.css"


def test_every_translation_key_is_used():
    i18n = _read("app", "i18n.py")
    keys = re.findall(r"^\s*'([a-z0-9_]+\.[a-z0-9_.]+)':", i18n, re.M)
    sources = _app_sources()
    other = "\n".join(text for path, text in sources.items() if not path.endswith("i18n.py"))
    # Keys put together at runtime - t('style.' ~ style) in a template, f'notify.event.{e}'
    # in Python - count through their prefix.
    dynamic = tuple(set(re.findall(r"t\('([a-z0-9_.]+\.)' ~", other))
                    | set(re.findall(r"f'([a-z0-9_.]+\.)\{", other)))
    assert "style." in dynamic and "notify.event." in dynamic
    unused = [k for k in keys if k not in other and not k.startswith(dynamic)]
    assert not unused, unused


def test_links_into_usage_md_land_on_a_heading():
    usage = _read("Usage.md")
    anchors = set()
    for heading in re.findall(r"^#+ (.+)$", usage, re.M):
        slug = re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")
        anchors.add(slug)
    for doc in ("Install.md", "README.md", "DOCKERHUB.md", "Usage.md"):
        for anchor in re.findall(r"Usage\.md#([\w-]+)", _read(doc)):
            assert anchor in anchors, (doc, anchor)


def test_the_name_people_see_is_ownfoil_plus():
    i18n = _read("app", "i18n.py")
    assert "files ownfoil could not match" not in i18n
    assert "que ownfoil no pudo" not in i18n
    chart = _read("chart", "Chart.yaml")
    assert re.search(r"(?m)^name: ownfoil-plus$", chart)
    assert "EstebanKZL/ownfoil-plus" in chart and "a1ex4" not in chart
    # Helm release names must be lowercase: "Ownfoil-Plus" was rejected.
    assert "helm upgrade --install ownfoil-plus" in _read("chart", "readme.md")
    assert re.search(r"(?m)^  ownfoil-plus:$", _read("docker-compose.yml"))
    assert "'ownfoil-plus:8465'" in _read("Install.md")
    assert '"name": "Ownfoil-Plus"' in _read(".devcontainer", "devcontainer.json")
    assert 'echo "Starting Ownfoil-Plus"' in _read("docker", "run.sh")


def test_planning_notes_are_not_shipped():
    """The redesign's specs and plans live in git history and the changelog."""
    tracked = subprocess.run(["git", "ls-files", "docs/superpowers"], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    assert not tracked

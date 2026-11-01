"""Dependency and image hardening (6.2.5.45): pins past known-vulnerable versions, the
two dependency lists kept in sync, pip removed from the image, build tools removed in
the same layer, and the automation that keeps it that way (Dependabot, Security CI)."""
import os
import re

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _norm(name):
    return re.sub(r"[-_.]+", "-", name.split("[")[0]).lower()


def _requirements():
    pins = {}
    for line in _read("requirements.txt").splitlines():
        if line.strip() and not line.startswith("#"):
            name, version = line.split("==")
            pins[_norm(name)] = version.strip()
    return pins


def _pyproject():
    pins = {}
    for name, version in re.findall(r'^\s*"([A-Za-z0-9_.\-\[\]]+)==([^";\s]+)', _read("pyproject.toml"), re.M):
        pins[_norm(name)] = version
    return pins


def _version(v):
    return tuple(int(p) for p in re.findall(r"\d+", v)[:3])


def test_requirements_and_pyproject_pin_the_same_versions():
    assert _requirements() == _pyproject()


def test_no_known_vulnerable_versions_come_back():
    pins = _requirements()
    # The fixed releases from the 6.2.5.45 audit (42 known vulnerabilities before).
    assert _version(pins["pillow"]) >= (13, 0, 0)
    assert _version(pins["werkzeug"]) >= (3, 1, 9)
    assert _version(pins["strawberry-graphql"]) >= (0, 327, 2)
    assert _version(pins["urllib3"]) >= (2, 8, 0)


def test_dockerfile_installs_and_cleans_up_in_one_layer():
    dockerfile = _read("Dockerfile")
    install = re.search(r"RUN set -e;(.*?)\n\n", dockerfile, re.DOTALL)
    assert install, "expected a single `RUN set -e; ...` install step"
    step = install.group(1)
    assert "pip install --no-cache-dir --requirement /tmp/requirements.txt" in step
    assert "apk add --no-cache --virtual .build-deps" in step and "apk del --no-network .build-deps" in step
    assert "pip uninstall --yes pip" in step
    # Runtime libraries survive the -dev cleanup on the 32-bit ARM builds.
    assert "apk add --no-cache libjpeg-turbo zlib libffi" in step
    # No separate cleanup RUN left behind.
    assert dockerfile.count("apk del") == 1


def test_dependabot_watches_python_docker_and_actions():
    config = yaml.safe_load(_read(".github", "dependabot.yml"))
    assert {u["package-ecosystem"] for u in config["updates"]} == {"pip", "docker", "github-actions"}


def test_security_workflow_audits_and_scans():
    workflow = yaml.safe_load(_read(".github", "workflows", "security.yml"))
    triggers = workflow.get("on") or workflow.get(True)
    assert "pull_request" in triggers and "schedule" in triggers
    audit = " ".join(s.get("run", "") for s in workflow["jobs"]["python-dependencies"]["steps"])
    assert "pip-audit --requirement requirements.txt" in audit
    image_steps = workflow["jobs"]["docker-image"]["steps"]
    trivy = next(s for s in image_steps if "trivy-action" in s.get("uses", ""))
    assert trivy["with"]["exit-code"] == "1" and "CRITICAL" in trivy["with"]["severity"]
    assert any("import pip" in s.get("run", "") for s in image_steps)

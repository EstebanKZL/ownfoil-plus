"""Coverage for the Docker Hub vulnerability-count hardening pass, requested directly
after a scan showed 5 critical / 30 high / 16 medium / 2 low / 1 unknown findings on
the published estebankzl/ownfoil-plus image.

Two real, independently-confirmed root causes:
  1. No automated rebuild existed at all - .github/workflows/docker.yml never existed
    in this repo's history (confirmed against the real pushed history, not assumed),
    despite CHANGELOG.md and tests/test_branding.py's own
    test_docker_image_is_published_under_the_new_dockerhub_repository claiming it did.
    With nothing rebuilding the image, nothing ever picked up newer Alpine/Python
    security patches after the image was first pushed.
  2. The Dockerfile never asked Alpine for already-available patches at build time
    (`apk update` without `apk upgrade`), and dropped privileges in run.sh via `sudo`,
    a package with its own real CVE history, for a job a tiny purpose-built
    alternative (`su-exec`) already covers.

This fork had no local or CI Docker registry access to actually run a scan and show a
literal before/after number, so these tests check the two fixes landed, not a
vulnerability count the test environment can't produce.
"""
import os
import re


ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


def test_dockerfile_upgrades_os_packages_at_build_time():
    """`apk update` alone only refreshes the package index, not the installed
    packages - `apk upgrade` is what actually pulls in patches published after this
    base image layer was baked, and it has to run before any apk add so the compiler
    toolchain and bash/su-exec installed below also come from the patched index."""
    dockerfile = _read("Dockerfile")
    m = re.search(r"apk update\s*&&\s*apk upgrade\b", dockerfile)
    assert m, "expected `apk update && apk upgrade` (in that order) in the Dockerfile"


def test_dockerfile_and_run_sh_use_su_exec_not_sudo():
    """sudo has a real history of critical CVEs (e.g. CVE-2021-3156, CVE-2023-22809)
    and this image only ever used it for one privilege-drop in run.sh - su-exec is
    the standard Alpine-native, purpose-built replacement for exactly that job, a few
    KB instead of the whole sudo package."""
    dockerfile = _read("Dockerfile")
    apk_add_lines = "\n".join(line for line in dockerfile.splitlines() if "apk add" in line)
    assert "su-exec" in apk_add_lines
    assert "sudo" not in apk_add_lines

    run_sh = _read("docker", "run.sh")
    exec_lines = "\n".join(line for line in run_sh.splitlines() if line.strip().startswith("exec "))
    assert "su-exec" in exec_lines
    assert "sudo" not in exec_lines
    # su-exec's own calling convention: user[:group] as one argument, not sudo's -u.
    assert re.search(r"su-exec\s+\"\$\{uid\}:\$\{gid\}\"", exec_lines)


def test_docker_workflow_exists_and_publishes_the_right_image():
    workflow = _read(".github", "workflows", "docker.yml")
    assert "images: estebankzl/ownfoil-plus" in workflow
    assert "a1ex4/ownfoil" not in workflow


def test_docker_workflow_always_builds_fresh_rather_than_from_a_cached_base_layer():
    """The other half of the fix: pull/no-cache on every build, so a rebuild (whether
    triggered by a release tag or the weekly schedule below) always starts from
    today's base image and today's Alpine package index, never a runner-cached one."""
    workflow = _read(".github", "workflows", "docker.yml")
    assert "pull: true" in workflow
    assert "no-cache: true" in workflow


def test_docker_workflow_rebuilds_on_a_schedule_not_only_on_release():
    """The actual lever against vulnerabilities accumulating over time: even a repo
    with no new commits for months still gets a fresh image periodically, so newly
    disclosed CVEs in the base image don't just sit there unpatched in what's
    published until the next unrelated release."""
    workflow = _read(".github", "workflows", "docker.yml")
    assert "schedule:" in workflow
    assert re.search(r"cron:\s*'[^']+'", workflow)


def test_docker_workflow_covers_every_platform_the_project_claims_to_support():
    """CHANGELOG.md and docker-compose.yml's own comments describe this image as
    published for amd64, arm64, arm/v7 and arm/v6 - the workflow has to actually
    build all four or that claim becomes false the moment it runs."""
    workflow = _read(".github", "workflows", "docker.yml")
    assert "linux/amd64,linux/arm64,linux/arm/v7,linux/arm/v6" in workflow

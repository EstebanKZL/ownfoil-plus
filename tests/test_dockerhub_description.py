"""Coverage for the Docker Hub overview page, requested directly: a more convincing
write-up ("algo mejor mas convincente") with the fork's newer features folded in, and
a way to actually get it onto Docker Hub - this fork has no Docker Hub credentials or
push access from here, so a manual copy/paste wasn't an option to verify or repeat.

Instead: DOCKERHUB.md is the single source of truth for that page's text, and a
dedicated GitHub Actions workflow (.github/workflows/dockerhub-description.yml) pushes
it to Docker Hub automatically whenever it changes on main - so the next edit to this
file is the only step needed, not a trip to Docker Hub's own editor.
"""
import os
import re


ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


def test_dockerhub_md_exists_and_covers_the_forks_newer_features():
    text = _read("DOCKERHUB.md")
    # The pitch for why to pull this image specifically, not just a feature dump.
    assert "Rebuilt on a schedule" in text
    assert "multi-arch" in text.lower() or "amd64" in text
    # Newer, fork-specific features that weren't in the old Docker Hub write-up.
    assert "Files admin page" in text
    assert "Sphaira" in text and "Tinfoil" in text and "CyberFoil" in text
    assert "LAN discovery" in text
    # Still a real quick start, not just marketing copy.
    assert "docker run" in text
    assert "docker-compose" in text.lower() or "services:" in text
    # Legal section required by the AGPLv3 fork notice, carried over unchanged.
    assert "AGPLv3" in text
    assert "https://github.com/EstebanKZL/ownfoil-plus" in text


def test_dockerhub_description_workflow_syncs_on_every_change_to_the_file():
    workflow = _read(".github", "workflows", "dockerhub-description.yml")
    assert "paths:" in workflow
    assert "DOCKERHUB.md" in workflow
    assert "branches:" in workflow and "main" in workflow
    assert "workflow_dispatch" in workflow


def test_dockerhub_description_workflow_pushes_to_the_right_repository():
    workflow = _read(".github", "workflows", "dockerhub-description.yml")
    assert "peter-evans/dockerhub-description" in workflow
    assert "repository: estebankzl/ownfoil-plus" in workflow
    assert "readme-filepath: ./DOCKERHUB.md" in workflow
    assert "${{ secrets.DOCKERHUB_USERNAME }}" in workflow
    assert "${{ secrets.DOCKERHUB_TOKEN }}" in workflow


def test_short_description_fits_docker_hubs_100_character_limit():
    workflow = _read(".github", "workflows", "dockerhub-description.yml")
    m = re.search(r'short-description:\s*"([^"]*)"', workflow)
    assert m, "expected a quoted short-description: value"
    assert len(m.group(1)) <= 100


def test_description_workflow_is_separate_from_the_image_build_workflow():
    """A broken image build must never block a description update, and editing the
    description must never trigger a full multi-arch rebuild - confirmed by these
    living in two different workflow files rather than one shared job."""
    docker_workflow = _read(".github", "workflows", "docker.yml")
    assert "dockerhub-description" not in docker_workflow


def test_github_readme_got_the_same_more_convincing_treatment():
    """Same request, applied to the GitHub README.md right after DOCKERHUB.md: lead
    with why to use this fork, not just what it does, and mention the same newer
    features (the Files admin page, and that the published image is rebuilt weekly
    rather than left to rot between releases)."""
    readme = _read("README.md")
    assert "Files admin page" in readme
    assert "rebuilt weekly" in readme
    assert "LAN discovery" in readme
    # The legal fork notice must still be there, worded the same as before.
    assert "GNU AGPLv3" in readme
    assert "[@a1ex4](https://github.com/a1ex4)" in readme

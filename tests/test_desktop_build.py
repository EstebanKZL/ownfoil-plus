"""The desktop builds (packaging/, .github/workflows/desktop.yml): one program per
system, started once before it ships, carrying what the app reads from disk."""
import os

ROOT = os.path.join(os.path.dirname(__file__), '..')


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as f:
        return f.read()


def test_the_program_prepares_its_worker_processes_and_never_uses_gunicorn():
    entry = _read('packaging', 'desktop.py')
    assert 'multiprocessing.freeze_support()' in entry
    assert 'from local import main' in entry and 'gunicorn' not in entry.split('"""', 2)[2]
    # Its data next to the program, so an update over the folder keeps it.
    assert "os.path.dirname(os.path.abspath(sys.executable))" in entry


def test_the_build_carries_what_the_app_reads_from_disk():
    spec = _read('packaging', 'ownfoil.spec')
    for folder in ("'templates'", "'static'", "'locales'", "'migrations'"):
        assert folder in spec, folder
    assert "languages.json" in spec and "'LICENSE.md'" in spec and "'NOTICE.md'" in spec
    assert "hiddenimports = app_modules()" in spec


def test_every_system_is_built_and_checked_before_it_ships():
    workflow = _read('.github', 'workflows', 'desktop.yml')
    for name in ('windows-x64', 'windows-arm64', 'macos-apple', 'macos-intel', 'linux-x64', 'linux-arm64'):
        assert f'name: {name}' in workflow, name
    assert '/api/health' in workflow and 'gh release upload' in workflow and '.sha256' in workflow


def test_a_release_made_before_the_builds_can_get_its_programs():
    """6.2.5.59 was released before packaging/ existed: built from main, attached to it."""
    workflow = _read('.github', 'workflows', 'desktop.yml')
    assert 'ref: ${{ inputs.ref || env.TAG }}' in workflow

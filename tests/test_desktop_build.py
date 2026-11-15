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


def test_the_programs_go_into_the_draft_before_it_is_published():
    """Published releases are immutable: the workflow attaches to a draft, built from its
    target commit, and refuses a release already published."""
    workflow = _read('.github', 'workflows', 'desktop.yml')
    assert 'types: [published]' not in workflow
    assert 'ref: ${{ needs.release.outputs.sha }}' in workflow
    assert '.target_commitish' in workflow and '"$draft" != true' in workflow
    assert 'macos-14' not in workflow


def test_the_check_stops_every_process_before_cleaning_up():
    """On Windows the workers kept the database open after `kill` stopped the main one."""
    workflow = _read('.github', 'workflows', 'desktop.yml')
    assert 'taskkill //F //T //IM Ownfoil-Plus.exe' in workflow

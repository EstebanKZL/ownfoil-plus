"""set_library_management_settings must re-trigger organization whenever a setting that
affects the organizer's computed path changes: naming language, clean names, Windows
compatibility, or the templates themselves. Files already organized under the old
settings need renaming, not just newly-added ones - the same reasoning that already
applied to a display-locale change.
"""
import copy
import types

import pytest

import constants
import db as db_mod
import settings as settings_mod
from settings import set_library_management_settings


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "CONFIG_FILE", str(tmp_path / "settings.yaml"))
    monkeypatch.setattr(settings_mod, "_cached_settings", None)
    # load_settings() also primes console keys from KEYS_FILE; point it somewhere empty
    # rather than the developer's real one.
    monkeypatch.setattr(settings_mod, "KEYS_FILE", str(tmp_path / "keys.txt"))
    # When CONFIG_FILE doesn't exist yet, load_settings() hands back DEFAULT_SETTINGS
    # itself (by reference, not a copy) - mutating it in one test would otherwise leak
    # into every other test sharing this process.
    monkeypatch.setattr(settings_mod, "DEFAULT_SETTINGS", copy.deepcopy(constants.DEFAULT_SETTINGS))

    reset_calls = []
    monkeypatch.setattr(db_mod, "reset_files_organized", lambda: reset_calls.append(True))
    return types.SimpleNamespace(reset_calls=reset_calls)


DEFAULT_TEMPLATES = dict(constants.DEFAULT_SETTINGS['library']['management']['organizer']['templates'])


def _organizer_payload(**overrides):
    base = {
        "enabled": True,
        "remove_empty_folders": False,
        "windows_compatible": False,
        "clean_names": False,
        "name_region": "",
        "name_language": "",
        "templates": dict(DEFAULT_TEMPLATES),
    }
    base.update(overrides)
    return {"organizer": base}


# ------------- changes that must reset -------------

def test_turning_on_a_naming_language_resets_organized_flag(isolated_settings):
    set_library_management_settings(_organizer_payload())  # baseline: disabled

    set_library_management_settings(_organizer_payload(name_region="GB", name_language="en"))

    assert isolated_settings.reset_calls == [True]


def test_switching_between_two_naming_languages_resets_again(isolated_settings):
    set_library_management_settings(_organizer_payload(name_region="GB", name_language="en"))
    isolated_settings.reset_calls.clear()

    set_library_management_settings(_organizer_payload(name_region="FR", name_language="fr"))

    assert isolated_settings.reset_calls == [True]


def test_turning_off_a_naming_language_resets_too(isolated_settings):
    set_library_management_settings(_organizer_payload(name_region="GB", name_language="en"))
    isolated_settings.reset_calls.clear()

    set_library_management_settings(_organizer_payload())  # back to disabled

    assert isolated_settings.reset_calls == [True]


def test_turning_on_clean_names_resets_organized_flag(isolated_settings):
    """The bug report this covers: enabling Clean Names left already-organized files
    (e.g. carrying '：') untouched, since only newly-scanned files went through the new
    setting - only a re-evaluation via reset_files_organized() fixes existing ones too."""
    set_library_management_settings(_organizer_payload(clean_names=False))
    isolated_settings.reset_calls.clear()

    set_library_management_settings(_organizer_payload(clean_names=True))

    assert isolated_settings.reset_calls == [True]


def test_turning_off_clean_names_resets_too(isolated_settings):
    set_library_management_settings(_organizer_payload(clean_names=True))
    isolated_settings.reset_calls.clear()

    set_library_management_settings(_organizer_payload(clean_names=False))

    assert isolated_settings.reset_calls == [True]


def test_toggling_windows_compatible_resets(isolated_settings):
    set_library_management_settings(_organizer_payload(windows_compatible=False))
    isolated_settings.reset_calls.clear()

    set_library_management_settings(_organizer_payload(windows_compatible=True))

    assert isolated_settings.reset_calls == [True]


def test_editing_a_template_resets(isolated_settings):
    set_library_management_settings(_organizer_payload())
    isolated_settings.reset_calls.clear()

    set_library_management_settings(_organizer_payload(
        templates=dict(DEFAULT_TEMPLATES, base="{titleName} [{appId}]")))

    assert isolated_settings.reset_calls == [True]


def test_multiple_naming_changes_in_one_save_still_reset_once(isolated_settings):
    set_library_management_settings(_organizer_payload())
    isolated_settings.reset_calls.clear()

    set_library_management_settings(_organizer_payload(
        clean_names=True, name_region="GB", name_language="en", windows_compatible=True))

    assert isolated_settings.reset_calls == [True]


# ------------- changes that must NOT reset -------------

def test_toggling_enabled_alone_does_not_reset(isolated_settings):
    """Whether the organizer runs at all doesn't change what path it would produce."""
    set_library_management_settings(_organizer_payload(enabled=True))
    isolated_settings.reset_calls.clear()

    set_library_management_settings(_organizer_payload(enabled=False))

    assert isolated_settings.reset_calls == []


def test_toggling_remove_empty_folders_alone_does_not_reset(isolated_settings):
    set_library_management_settings(_organizer_payload(remove_empty_folders=False))
    isolated_settings.reset_calls.clear()

    set_library_management_settings(_organizer_payload(remove_empty_folders=True))

    assert isolated_settings.reset_calls == []


def test_saving_identical_settings_again_does_not_reset(isolated_settings):
    payload = _organizer_payload(name_region="GB", name_language="en", clean_names=True)
    set_library_management_settings(payload)
    isolated_settings.reset_calls.clear()

    set_library_management_settings(payload)

    assert isolated_settings.reset_calls == []


def test_first_ever_save_with_defaults_does_not_reset(isolated_settings):
    """No prior organizer settings exist yet - going from "nothing configured" to
    "still nothing configured" is not a change worth reorganizing for."""
    set_library_management_settings(_organizer_payload())

    assert isolated_settings.reset_calls == []

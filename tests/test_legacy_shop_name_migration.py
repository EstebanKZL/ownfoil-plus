"""migrate_legacy_shop_name (settings.py, CHANGELOG 6.2.4.14): a settings.yaml carried
over from upstream Ownfoil, or from an early install of this fork before the default
changed, still has shop.name saved as upstream's own stock default "Ownfoil" - which
merge_dicts_recursive can never fix, since it only ever fills in a key that's missing,
not one already set. Reported by a real user as the browser tab and navbar still
saying "Ownfoil" instead of this fork's own "Ownfoil-Plus" fallback.
"""
import copy

import pytest
import yaml

import constants
import settings as settings_mod
from settings import load_settings, migrate_legacy_shop_name


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "CONFIG_FILE", str(tmp_path / "settings.yaml"))
    monkeypatch.setattr(settings_mod, "KEYS_FILE", str(tmp_path / "keys.txt"))
    monkeypatch.setattr(settings_mod, "_cached_settings", None)
    monkeypatch.setattr(settings_mod, "DEFAULT_SETTINGS", copy.deepcopy(constants.DEFAULT_SETTINGS))
    return tmp_path / "settings.yaml"


def _write_legacy_settings(path, **shop_overrides):
    shop = {"name": "Ownfoil", "host": "", "public": False, "motd": "hi"}
    shop.update(shop_overrides)
    path.write_text(yaml.safe_dump({"shop": shop}))


def test_a_legacy_ownfoil_name_is_blanked_on_load(isolated_settings):
    _write_legacy_settings(isolated_settings)
    settings = load_settings()
    assert settings["shop"]["name"] == ""


def test_the_migration_is_written_back_to_disk_so_it_only_runs_once(isolated_settings):
    _write_legacy_settings(isolated_settings)
    load_settings()

    on_disk = yaml.safe_load(isolated_settings.read_text())
    assert on_disk["shop"]["name"] == ""


def test_a_shop_deliberately_renamed_back_to_ownfoil_afterward_is_left_alone(isolated_settings):
    _write_legacy_settings(isolated_settings)
    load_settings()  # first load: migrates "Ownfoil" -> ""

    # The admin later types "Ownfoil" back in on purpose, directly on disk (as
    # set_shop_settings would leave it).
    on_disk = yaml.safe_load(isolated_settings.read_text())
    on_disk["shop"]["name"] = "Ownfoil"
    isolated_settings.write_text(yaml.safe_dump(on_disk))

    settings = load_settings()
    assert settings["shop"]["name"] == "Ownfoil", (
        "the migration must only fire on the name an install started with, not "
        "reassert itself against a later, deliberate choice")


def test_a_custom_shop_name_is_never_touched(isolated_settings):
    _write_legacy_settings(isolated_settings, name="Esteban's Switch Shop")
    settings = load_settings()
    assert settings["shop"]["name"] == "Esteban's Switch Shop"


def test_migrate_legacy_shop_name_runs_exactly_once_per_settings_object():
    legacy = {"shop": {"name": "Ownfoil"}}
    assert migrate_legacy_shop_name(legacy) is True  # first call: migrates and sets the flag
    assert legacy["shop"]["name"] == ""
    assert legacy["server"]["legacy_shop_name_migrated"] is True

    # A later call against the same (now-flagged) settings is a no-op, even if the
    # name were somehow "Ownfoil" again - this is what lets a deliberate rename
    # back to "Ownfoil" stick instead of being wiped on the next restart.
    legacy["shop"]["name"] = "Ownfoil"
    assert migrate_legacy_shop_name(legacy) is False
    assert legacy["shop"]["name"] == "Ownfoil"


def test_migrate_legacy_shop_name_leaves_a_custom_name_alone_but_still_sets_the_flag():
    custom = {"shop": {"name": "Esteban's Switch Shop"}}
    assert migrate_legacy_shop_name(custom) is True  # flag not set yet - first load always persists it
    assert custom["shop"]["name"] == "Esteban's Switch Shop"
    assert custom["server"]["legacy_shop_name_migrated"] is True

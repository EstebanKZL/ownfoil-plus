"""Settings > Titles says up to which firmware the console keys open games, and its
key messages come from the translations, not text fixed in English."""
import os

from settings import keys_firmware

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_the_newest_master_key_names_its_firmware():
    assert keys_firmware(['master_key_00', 'master_key_12', 'master_key_0b']) == '19.0.0'
    assert keys_firmware(['master_key_00']) == '1.0.0'
    assert keys_firmware(['master_key_14']) == '21.0.0'


def test_a_revision_newer_than_the_table_says_so():
    assert keys_firmware(['master_key_1f']) == '21.0.0+'


def test_no_keys_name_no_firmware():
    assert keys_firmware([]) is None and keys_firmware(None) is None
    assert keys_firmware(['not_a_key']) is None


def test_the_key_messages_are_translated():
    with open(os.path.join(ROOT, "app", "static", "js", "settings.js"), encoding="utf-8") as f:
        js = f.read()
    for english in ("Keys are valid!", "Missing keys file!", "is invalid'", "All master key revisions"):
        assert english not in js
    assert "I18N.keys.firmware" in js

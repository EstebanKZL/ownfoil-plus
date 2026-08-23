"""library.py's duplicate-file resolution: finding apps with more than one physical
file attached, deciding automatically which to keep only when every file has a
complete, unambiguous Valid/Repack/Corrupt verdict and there's a single clear winner,
and the shared delete-losers-then-rename-survivor action both the automatic task and
the manual GraphQL mutation use.
"""
import os
import types

import pytest

from app import create_app
from constants import APP_TYPE_BASE
from db import Apps, Files, Libraries, Titles, db
from library import (automatic_duplicate_winner, duplicate_file_groups,
                     duplicate_winner_preferring_largest, duplicate_winner_with_preferences,
                     resolve_duplicate_files)


@pytest.fixture
def env(tmp_path):
    app = create_app(f"sqlite:///{tmp_path/'test.db'}")
    lib_dir = tmp_path / "games"
    lib_dir.mkdir()
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    library = Libraries(path=str(lib_dir))
    db.session.add(library)
    title = Titles(title_id="0100000000010000", have_base=True)
    db.session.add(title)
    db.session.flush()
    app_row = Apps(title_id=title.id, app_id="0100000000010000", app_version="0",
                   app_type=APP_TYPE_BASE, owned=True)
    db.session.add(app_row)
    db.session.commit()

    def seed(name, content=b"RAWDATA", **columns):
        path = lib_dir / name
        path.write_bytes(content)
        f = Files(filepath=str(path), library_id=library.id, folder=str(lib_dir),
                 filename=name, extension="nsp", size=len(content), identified=True, **columns)
        db.session.add(f)
        db.session.flush()
        app_row.files.append(f)
        db.session.commit()
        return f

    yield types.SimpleNamespace(app=app, lib_dir=lib_dir, seed=seed, app_row=app_row)
    ctx.pop()


VALID = dict(signature_valid=True, hash_valid=True)
REPACK = dict(signature_valid=False, hash_valid=True)
CORRUPT = dict(signature_valid=True, hash_valid=False, hash_modified=False)
MODIFIED = dict(signature_valid=True, hash_valid=False, hash_modified=True)
SIGNATURE_OK = dict(signature_valid=True, hash_valid=None)
SIGNATURE_FAILED = dict(signature_valid=False, hash_valid=None)
UNVERIFIED = dict(signature_valid=None, hash_valid=None)


# --- duplicate_file_groups -----------------------------------------------------------

def test_an_app_with_one_file_is_not_a_duplicate_group(env):
    env.seed("Game.nsp", **VALID)
    assert duplicate_file_groups() == []


def test_an_app_with_two_files_is_a_duplicate_group(env):
    f1 = env.seed("Game.nsp", **VALID)
    f2 = env.seed("Game(2).nsp", content=b"DIFFERENT", **VALID)

    groups = duplicate_file_groups()

    assert len(groups) == 1
    app, files = groups[0]
    assert app.id == env.app_row.id
    assert {f.id for f in files} == {f1.id, f2.id}


def test_an_unowned_app_is_not_included(env):
    env.app_row.owned = False
    env.seed("Game.nsp", **VALID)
    env.seed("Game(2).nsp", content=b"DIFFERENT", **VALID)
    db.session.commit()

    assert duplicate_file_groups() == []


# --- automatic_duplicate_winner -------------------------------------------------------

def test_valid_beats_repack_and_corrupt(env):
    valid = env.seed("A.nsp", **VALID)
    env.seed("B.nsp", content=b"X", **REPACK)
    env.seed("C.nsp", content=b"Y", **CORRUPT)

    winner = automatic_duplicate_winner(env.app_row.files)

    assert winner.id == valid.id


def test_repack_beats_corrupt_when_no_valid_present(env):
    repack = env.seed("A.nsp", **REPACK)
    env.seed("B.nsp", content=b"X", **CORRUPT)

    winner = automatic_duplicate_winner(env.app_row.files)

    assert winner.id == repack.id


def test_a_tie_between_two_valid_files_is_not_decided(env):
    env.seed("A.nsp", **VALID)
    env.seed("B.nsp", content=b"X", **VALID)

    assert automatic_duplicate_winner(env.app_row.files) is None


def test_a_tie_between_two_repack_files_is_not_decided(env):
    env.seed("A.nsp", **REPACK)
    env.seed("B.nsp", content=b"X", **REPACK)

    assert automatic_duplicate_winner(env.app_row.files) is None


@pytest.mark.parametrize("ambiguous_status", [MODIFIED, SIGNATURE_OK, SIGNATURE_FAILED, UNVERIFIED])
def test_any_file_with_an_ambiguous_status_blocks_the_whole_group(env, ambiguous_status):
    """The core safety rule: even with an otherwise-clear Valid winner, a single file
    that isn't fully verified (or was flagged Modified) makes the group ineligible -
    never guess when one of the copies hasn't given a complete answer yet."""
    env.seed("A.nsp", **VALID)
    env.seed("B.nsp", content=b"X", **ambiguous_status)

    assert automatic_duplicate_winner(env.app_row.files) is None


def test_three_files_still_picks_the_single_best(env):
    env.seed("A.nsp", **CORRUPT)
    valid = env.seed("B.nsp", content=b"X", **VALID)
    env.seed("C.nsp", content=b"Y", **REPACK)

    winner = automatic_duplicate_winner(env.app_row.files)

    assert winner.id == valid.id


# --- duplicate_winner_preferring_largest ---------------------------------------------

def test_prefer_largest_matches_automatic_winner_when_there_is_no_tie(env):
    """When there's already a single clear best, the size-preferring version agrees
    with the strict one - the tiebreak only ever matters once ranks are tied."""
    valid = env.seed("A.nsp", content=b"SMALL", **VALID)
    env.seed("B.nsp", content=b"BIGGER-CONTENT", **REPACK)

    winner = duplicate_winner_preferring_largest(env.app_row.files)

    assert winner.id == valid.id


def test_prefer_largest_breaks_a_tie_by_size(env):
    """The exact case reported: two files both Valid, differing only in size - the
    larger one wins instead of the group being left undecided."""
    env.seed("A.nsp", content=b"SMALL", **VALID)                 # 5 bytes
    bigger = env.seed("B.nsp", content=b"A LOT BIGGER CONTENT", **VALID)  # 21 bytes

    winner = duplicate_winner_preferring_largest(env.app_row.files)

    assert winner.id == bigger.id


def test_prefer_largest_breaks_a_repack_tie_too(env):
    """Not just Valid ties - any tie at whichever rank turns out to be the best one."""
    env.seed("A.nsp", content=b"SMALL", **REPACK)
    bigger = env.seed("B.nsp", content=b"A LOT BIGGER CONTENT", **REPACK)

    winner = duplicate_winner_preferring_largest(env.app_row.files)

    assert winner.id == bigger.id


def test_prefer_largest_still_refuses_a_group_with_an_ambiguous_file(env):
    """The safety gate is identical to the strict function - only the final tiebreak
    step differs. A file that isn't fully verified still blocks the whole group,
    even though the other two are tied at Valid with clearly different sizes."""
    env.seed("A.nsp", content=b"SMALL", **VALID)
    env.seed("B.nsp", content=b"A LOT BIGGER CONTENT", **VALID)
    env.seed("C.nsp", content=b"Z", **UNVERIFIED)

    assert duplicate_winner_preferring_largest(env.app_row.files) is None


def test_prefer_largest_picks_only_among_the_best_rank_not_across_all(env):
    """A Corrupt file, however large, must never beat a smaller Valid one - the size
    tiebreak only applies *within* the best rank, never across ranks."""
    env.seed("A.nsp", content=b"HUGE " * 100, **CORRUPT)
    small_valid = env.seed("B.nsp", content=b"TINY", **VALID)

    winner = duplicate_winner_preferring_largest(env.app_row.files)

    assert winner.id == small_valid.id


# --- duplicate_winner_with_preferences (compression-aware) --------------------------

def test_compression_preference_picks_the_compressed_file_on_a_tie(env):
    """The exact case that motivated this: a compressed copy is inherently smaller,
    so a pure size comparison would always penalize it. With compression_preference
    set, it wins the tie regardless of being the smaller file."""
    uncompressed = env.seed("A.nsp", content=b"BIGGER-UNCOMPRESSED", compressed=False, **VALID)
    compressed = env.seed("B.nsz", content=b"SMALL", compressed=True, **VALID)

    winner = duplicate_winner_with_preferences(
        env.app_row.files, compression_preference="compressed")

    assert winner.id == compressed.id


def test_compression_preference_can_prefer_uncompressed_instead(env):
    uncompressed = env.seed("A.nsp", content=b"BIGGER-UNCOMPRESSED", compressed=False, **VALID)
    compressed = env.seed("B.nsz", content=b"SMALL", compressed=True, **VALID)

    winner = duplicate_winner_with_preferences(
        env.app_row.files, compression_preference="uncompressed")

    assert winner.id == uncompressed.id


def test_compression_preference_is_applied_before_size(env):
    """Even when prefer_larger_on_tie is also on, compression_preference wins first -
    the smaller compressed file must still beat the larger uncompressed one."""
    uncompressed = env.seed("A.nsp", content=b"MUCH BIGGER UNCOMPRESSED FILE HERE", compressed=False, **VALID)
    compressed = env.seed("B.nsz", content=b"TINY", compressed=True, **VALID)

    winner = duplicate_winner_with_preferences(
        env.app_row.files, prefer_larger_on_tie=True, compression_preference="compressed")

    assert winner.id == compressed.id


def test_compression_preference_falls_back_to_size_when_it_does_not_distinguish(env):
    """Two files with the SAME compression status - the preference can't settle
    anything, so it falls through to the size tiebreak when that's also enabled."""
    small = env.seed("A.nsz", content=b"SMALL", compressed=True, **VALID)
    bigger = env.seed("B.nsz", content=b"A LOT BIGGER CONTENT HERE", compressed=True, **VALID)

    winner = duplicate_winner_with_preferences(
        env.app_row.files, prefer_larger_on_tie=True, compression_preference="compressed")

    assert winner.id == bigger.id


def test_compression_preference_alone_without_size_tiebreak_returns_none_when_it_does_not_distinguish(env):
    """Same-compression tie, and prefer_larger_on_tie is off - correctly refuses,
    exactly like the strict function would."""
    env.seed("A.nsz", content=b"SMALL", compressed=True, **VALID)
    env.seed("B.nsz", content=b"BIGGER", compressed=True, **VALID)

    winner = duplicate_winner_with_preferences(
        env.app_row.files, prefer_larger_on_tie=False, compression_preference="compressed")

    assert winner is None


def test_neither_preference_set_behaves_exactly_like_the_strict_function(env):
    env.seed("A.nsp", **VALID)
    env.seed("B.nsp", content=b"X", **VALID)

    assert duplicate_winner_with_preferences(env.app_row.files) is None


def test_compression_preference_still_refuses_an_unverified_group(env):
    """The safety gate is unaffected - an unverified file in the group still blocks
    resolution entirely, regardless of either preference."""
    env.seed("A.nsp", content=b"X", compressed=False, **VALID)
    env.seed("B.nsz", content=b"Y", compressed=True, **VALID)
    env.seed("C.nsp", content=b"Z", **UNVERIFIED)

    winner = duplicate_winner_with_preferences(
        env.app_row.files, prefer_larger_on_tie=True, compression_preference="compressed")

    assert winner is None


# --- resolve_duplicate_files (real files on disk) -------------------------------------

def test_resolve_deletes_losers_and_keeps_the_winner_on_disk(env):
    valid = env.seed("Game.nsp", **VALID)
    repack = env.seed("Game(2).nsp", content=b"X", **REPACK)
    corrupt = env.seed("Game(3).nsp", content=b"Y", **CORRUPT)
    repack_path, corrupt_path = repack.filepath, corrupt.filepath

    result = resolve_duplicate_files(valid.id, [valid.id, repack.id, corrupt.id])
    db.session.expire_all()

    assert result is True
    assert os.path.exists(valid.filepath)
    assert not os.path.exists(repack_path)
    assert not os.path.exists(corrupt_path)
    assert {f.id for f in db.session.get(Apps, env.app_row.id).files} == {valid.id}


def test_the_surviving_file_is_renamed_off_its_suffix_when_the_plain_name_frees_up(env):
    """The exact scenario reported: the (2)-suffixed copy turns out healthier, so once
    the plain-named loser is gone, the survivor takes over the plain name - the file
    left standing should not still look like a leftover duplicate."""
    plain_loser = env.seed("Game.nsp", content=b"BAD-CONTENT", **CORRUPT)
    suffixed_winner = env.seed("Game(2).nsp", content=b"GOOD-CONTENT", **VALID)
    plain_path, winner_id = plain_loser.filepath, suffixed_winner.id

    resolve_duplicate_files(winner_id, [plain_loser.id, winner_id])
    db.session.expire_all()
    survivor = db.session.get(Files, winner_id)

    # The plain name is occupied again, but by the survivor's own content now - it
    # moved into the slot the deleted loser vacated, rather than the path staying empty.
    assert os.path.exists(plain_path)
    assert open(plain_path, "rb").read() == b"GOOD-CONTENT"
    assert survivor.filename == "Game.nsp"
    assert survivor.filepath == str(env.lib_dir / "Game.nsp")


def test_no_rename_needed_when_the_winner_already_has_the_plain_name(env):
    plain_winner = env.seed("Game.nsp", **VALID)
    suffixed_loser = env.seed("Game(2).nsp", content=b"X", **CORRUPT)
    winner_id = plain_winner.id

    resolve_duplicate_files(winner_id, [winner_id, suffixed_loser.id])
    db.session.expire_all()
    survivor = db.session.get(Files, winner_id)

    assert survivor.filename == "Game.nsp"
    assert survivor.filepath == str(env.lib_dir / "Game.nsp")


def test_rename_is_skipped_if_the_plain_name_is_still_somehow_occupied(env):
    """Defensive: never clobber an unrelated file that happens to already sit at the
    plain name - leave the suffix rather than risk destroying something else."""
    suffixed_winner = env.seed("Game(2).nsp", **VALID)
    # An unrelated file (not part of this app/group) already occupies the plain name.
    (env.lib_dir / "Game.nsp").write_bytes(b"SOMEONE ELSE'S FILE")

    resolve_duplicate_files(suffixed_winner.id, [suffixed_winner.id])
    db.session.refresh(suffixed_winner)

    assert suffixed_winner.filename == "Game(2).nsp"  # left alone
    assert (env.lib_dir / "Game.nsp").read_bytes() == b"SOMEONE ELSE'S FILE"  # untouched


def test_resolve_returns_false_for_an_unknown_keep_file_id(env):
    env.seed("Game.nsp", **VALID)

    assert resolve_duplicate_files(999999, [999999]) is False

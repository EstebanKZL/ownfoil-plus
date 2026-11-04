"""Sagas: which series each Switch game belongs to, from Wikidata (CC0), built on the
server itself and kept in data/series.json. These tests use saved answers; nothing here
goes online."""
import json
import os

import pytest

import series

Q_ZELDA = "http://www.wikidata.org/entity/Q12395"
Q_SPLATOON = "http://www.wikidata.org/entity/Q20888356"


def _binding(**values):
    return {k: {"type": "literal", "value": v} for k, v in values.items()}


BY_ID = {"results": {"bindings": [
    dict(_binding(tid="01007EF00011E000", sen="The Legend of Zelda", ses="The Legend of Zelda"),
         s={"type": "uri", "value": Q_ZELDA}),
    dict(_binding(tid="0100F2C0115B6000", sen="The Legend of Zelda"),
         s={"type": "uri", "value": Q_ZELDA}),
]}}
BY_NAME = {"results": {"bindings": [
    dict(_binding(name="Splatoon 3", sen="Splatoon", ses="Splatoon"), s={"type": "uri", "value": Q_SPLATOON}),
    dict(_binding(name="Splatoon 2", sen="Splatoon"), s={"type": "uri", "value": Q_SPLATOON}),
    dict(_binding(name="Pokémon™ Brilliant Diamond", sen="Pokémon", ses="Pokémon"),
         s={"type": "uri", "value": "http://www.wikidata.org/entity/Q864"}),
]}}


def test_names_compare_without_accents_marks_or_punctuation():
    assert series.normalize("Pokémon™ Brilliant Diamond") == "pokemon brilliant diamond"
    assert series.normalize("  The Legend of Zelda®: Breath of the Wild ") == "the legend of zelda breath of the wild"
    assert series.normalize("SPLATOON™ 3") == series.normalize("Splatoon 3")
    assert series.normalize(None) == ""


def test_build_links_series_to_title_ids_and_names():
    data = series.build(BY_ID, BY_NAME)
    assert data["series"]["Q12395"] == {"en": "The Legend of Zelda", "es": "The Legend of Zelda"}
    assert data["series"]["Q20888356"]["en"] == "Splatoon"
    assert data["ids"]["01007EF00011E000"] == ["Q12395"]
    assert data["ids"]["0100F2C0115B6000"] == ["Q12395"]
    assert data["names"]["splatoon 3"] == ["Q20888356"]
    assert data["names"]["pokemon brilliant diamond"] == ["Q864"]
    assert "updated" in data


def test_series_of_a_game_by_id_first_then_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "SERIES_FILE", str(tmp_path / "series.json"))
    series.save(series.build(BY_ID, BY_NAME))
    assert series.series_of("01007ef00011e000", "anything") == ["Q12395"]
    assert series.series_of("0100000000000000", "Splatoon™ 3") == ["Q20888356"]
    assert series.series_of("0100000000000000", "Not a saga") == []


def test_series_names_follow_the_language_with_english_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "SERIES_FILE", str(tmp_path / "series.json"))
    series.save(series.build(BY_ID, BY_NAME))
    assert series.series_name("Q20888356", "es") == "Splatoon"
    assert series.series_name("Q12395", "fr") == "The Legend of Zelda"
    assert series.series_name("Q0", "es") is None


def test_refresh_keeps_the_last_copy_when_wikidata_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "SERIES_FILE", str(tmp_path / "series.json"))
    series.save(series.build(BY_ID, BY_NAME))

    def broken(_query):
        raise OSError("offline")
    monkeypatch.setattr(series, "_query", broken)
    assert series.refresh(force=True) is False
    assert series.series_of("01007EF00011E000", "") == ["Q12395"]


def test_refresh_skips_a_fresh_copy_unless_forced(tmp_path, monkeypatch):
    monkeypatch.setattr(series, "SERIES_FILE", str(tmp_path / "series.json"))
    calls = []
    monkeypatch.setattr(series, "_query", lambda q: calls.append(q) or (BY_ID if q == series.QUERY_BY_ID else BY_NAME))
    assert series.refresh() is True and len(calls) == 2
    assert series.refresh() is None and len(calls) == 2        # a week hasn't passed
    assert series.refresh(force=True) is True and len(calls) == 4
    assert json.loads(open(series.SERIES_FILE, encoding="utf-8").read())["ids"]


def test_the_queries_ask_wikidata_for_switch_games_and_their_series():
    assert "wdt:P179" in series.QUERY_BY_ID and "wdt:P11072" in series.QUERY_BY_ID
    assert "wdt:P179" in series.QUERY_BY_NAME and "wd:Q19610114" in series.QUERY_BY_NAME
    assert "query.wikidata.org" in series.WIKIDATA_URL


def test_the_titledb_task_refreshes_the_series_afterwards():
    import tasks
    assert "update_series" in tasks.TASK_REGISTRY
    with open(os.path.join(os.path.dirname(__file__), "..", "app", "tasks.py"), encoding="utf-8") as f:
        source = f.read()
    body = source[source.index("def update_titledb_task"):source.index("def utc_offset")]
    assert "enqueue_task('update_series')" in body


def test_a_series_named_only_in_mul_still_has_a_name(tmp_path, monkeypatch):
    """Found with real data: Wikidata names many series once for every language ("mul"),
    as Mario Kart: without it 122 links had no series name and their saga vanished."""
    monkeypatch.setattr(series, "SERIES_FILE", str(tmp_path / "series.json"))
    by_id = {"results": {"bindings": [
        dict(_binding(tid="0100152000022000", smul="Mario Kart"),
             s={"type": "uri", "value": "http://www.wikidata.org/entity/Q188196"})]}}
    by_name = {"results": {"bindings": [
        dict(_binding(name="Mario Kart Live", smul="Mario Kart"),
             s={"type": "uri", "value": "http://www.wikidata.org/entity/Q188196"})]}}
    series.save(series.build(by_id, by_name))
    assert series.series_name("Q188196", "es") == "Mario Kart"
    assert series.series_name("Q188196", "en") == "Mario Kart"
    assert 'LANG(?smul) = "mul"' in series.QUERY_BY_ID and 'LANG(?smul) = "mul"' in series.QUERY_BY_NAME
    assert 'FILTER(LANG(?name) IN ("en", "es", "mul"))' in series.QUERY_BY_NAME   # game names too

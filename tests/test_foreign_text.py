"""A description in another script than TitleDB's language is not shown
(titledb/language.py, gql/resolvers.py).

Asked for: some games showed a Japanese tagline over the Spanish description - the
regional TitleDB file carries Nintendo's text as Nintendo left it. A text written mostly
in Japanese, Chinese or Korean is dropped when the chosen language is none of those.
"""
import inspect

import pytest

from titledb.language import foreign_text

JA = "HD振動、タッチスクリーン、携帯モードで「アサシン クリード III リマスター」をプレイ。"
ES = "Revive la Revolución Estadounidense o vívela por primera vez."


@pytest.mark.parametrize("text,language,foreign", [
    (JA, "es", True),
    ("最大32人のライバルワームたちと白熱の戦い！\n『Worms』シリーズ初のリアルタイムアクションゲーム！", "es", True),
    ("젤다의 전설", "en", True),
    ("塞尔达传说", "fr", True),
    (ES, "es", False),
    ("Pokémon™ Escarlata - 「ポケモン」", "es", False),     # a Latin text quoting a name
    ("Приключение", "ru", False),
    (JA, "ja", False),
    ("塞尔达传说", "zh", False),
    ("젤다의 전설", "ko", False),
    ("", "es", False),
    (None, "es", False),
])
def test_foreign_text(text, language, foreign):
    assert foreign_text(text, language) is foreign


def test_the_titles_drop_it_for_every_view():
    """The one place every Title is built from (the game page, the Library's views,
    a DLC's own card) leaves out a foreign intro or description."""
    from gql import resolvers
    src = inspect.getsource(resolvers._build_title)
    assert "_shown_text(m.get('description'))" in src
    assert "_shown_text(m.get('intro'))" in src
    shown = inspect.getsource(resolvers._shown_text)
    assert "foreign_text(" in shown and "['titles']['language']" in shown

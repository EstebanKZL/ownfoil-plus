"""Whether a TitleDB text is written in the chosen language's script.

The regional files carry Nintendo's text as Nintendo left it: a Spanish file can hold a
game whose tagline is still in Japanese. Shown over the Spanish description it reads as
noise, so a text written mostly in Japanese, Chinese or Korean is left out when TitleDB's
language is none of those. A Latin text quoting a name in kana stays.
"""

# Kana, CJK ideographs (and their extensions and compatibility forms), Hangul.
_CJK_RANGES = (
    (0x3040, 0x30FF),     # hiragana, katakana
    (0x31F0, 0x31FF),     # katakana extensions
    (0x3400, 0x4DBF),     # CJK extension A
    (0x4E00, 0x9FFF),     # CJK unified ideographs
    (0xF900, 0xFAFF),     # CJK compatibility ideographs
    (0xFF66, 0xFF9F),     # half-width katakana
    (0x1100, 0x11FF),     # Hangul jamo
    (0x3130, 0x318F),     # Hangul compatibility jamo
    (0xAC00, 0xD7AF),     # Hangul syllables
    (0x20000, 0x2FA1F),   # CJK extensions B and later
)
_CJK_LANGUAGES = {'ja', 'zh', 'ko'}
# Share of the letters that makes a text "written in" those scripts.
_THRESHOLD = 0.3


def _is_cjk(ch):
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


def foreign_text(text, language):
    """True when `text` is written mostly in Japanese, Chinese or Korean and the chosen
    `language` (TitleDB's, 'es', 'en', ...) is none of those."""
    if not text or (language or '').lower()[:2] in _CJK_LANGUAGES:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    cjk = sum(1 for ch in letters if _is_cjk(ch))
    return cjk / len(letters) >= _THRESHOLD

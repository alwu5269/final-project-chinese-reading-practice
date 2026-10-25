"""Tap-for-meaning: offline CC-CEDICT lookups (bundled with the hanzipy package). No AI, no network."""

import logging
import re
from functools import lru_cache

logging.getLogger().setLevel(logging.WARNING)  # hanzipy logs every load step at DEBUG
from hanzipy.dictionary import HanziDictionary  # noqa: E402

_dict = None
TONE_MARKS = {"a": "āáǎà", "e": "ēéěè", "i": "īíǐì", "o": "ōóǒò", "u": "ūúǔù", "ü": "ǖǘǚǜ"}


def _d() -> HanziDictionary:
    global _dict
    if _dict is None:
        _dict = HanziDictionary()
    return _dict


def _mark(syllable: str) -> str:
    """'qi4' -> 'qì' (CC-CEDICT uses tone numbers)."""
    m = re.fullmatch(r"([a-zA-Zü:]+)([1-5])", syllable)
    if not m:
        return syllable
    s, tone = m.group(1).replace("u:", "ü").replace("v", "ü"), int(m.group(2))
    if tone == 5:
        return s
    for vowel in ("a", "e", "ou"):  # standard placement rules
        if vowel in s.lower():
            i = s.lower().index(vowel)
            break
    else:
        i = max(j for j, c in enumerate(s.lower()) if c in "aeiouü")
    c = s[i].lower()
    return s[:i] + TONE_MARKS[c][tone - 1] + s[i + 1:]


@lru_cache(maxsize=4096)
def _lookup(word: str) -> list[dict]:
    try:
        return _d().definition_lookup(word)
    except KeyError:
        return []


def define(text: str, index: int) -> dict | None:
    """The longest dictionary word in `text` that covers the character at `index` (up to 4 characters)."""
    if not (0 <= index < len(text)):
        return None
    for size in (4, 3, 2, 1):
        for start in range(max(0, index - size + 1), index + 1):
            word = text[start:start + size]
            if len(word) < size or not all("一" <= c <= "鿿" for c in word):
                continue
            entries = _lookup(word)
            if entries:
                return {
                    "word": word,
                    "start": start,
                    "entries": [{
                        "simplified": e["simplified"],
                        "traditional": e["traditional"],
                        "pinyin": " ".join(_mark(p) for p in e["pinyin"].split()),
                        "meanings": [m for m in e["definition"].split("/") if m and not m.startswith("CL:")][:6],
                    } for e in entries[:3]],
                }
    return None

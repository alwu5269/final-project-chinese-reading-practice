"""Measured reading level (no AI): how much of a passage a learner at each HSK level already knows.

data/hsk_words.json is the official HSK 2.0 word list (word -> level 1-6), from
github.com/drkameleon/complete-hsk-vocabulary (MIT licence).

The passage is split into words by longest match against that list (up to 4 characters). Each
character takes the level of the word it sits in; characters outside any HSK word take the lowest
level of any HSK word that contains them, or 7. A passage is at level L when at least 90% of its
characters are known at level L. Digits, Latin letters and punctuation are not counted.
"""

import json
from functools import lru_cache
from pathlib import Path

import script

TARGET = 0.90
WORDS = Path(__file__).parent / "data" / "hsk_words.json"


@lru_cache(maxsize=1)
def _tables() -> tuple[dict[str, int], dict[str, int]]:
    words = json.loads(WORDS.read_text(encoding="utf-8"))
    chars: dict[str, int] = {}
    for w, lvl in words.items():
        for c in w:
            chars[c] = min(chars.get(c, 7), lvl)
    return words, chars


def char_levels(text: str) -> list[int]:
    """The HSK level (1-7) of every Chinese character in `text`, in order."""
    words, chars = _tables()
    s = script.to_simplified(text)
    out, i = [], 0
    while i < len(s):
        if not "一" <= s[i] <= "鿿":
            i += 1
            continue
        for size in (4, 3, 2, 1):
            w = s[i:i + size]
            if w in words:
                out += [words[w]] * size
                i += size
                break
        else:
            out.append(chars.get(s[i], 7))
            i += 1
    return out


def measure(text: str) -> dict:
    """{'hsk': 1-7 (0 if no Chinese), 'known': share of characters known at levels 1-6}."""
    lv = char_levels(text)
    if not lv:
        return {"hsk": 0, "known": []}
    known = [round(sum(x <= n for x in lv) / len(lv), 2) for n in range(1, 7)]
    return {"hsk": next((i + 1 for i, k in enumerate(known) if k >= TARGET), 7), "known": known}

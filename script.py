"""Traditional <-> simplified Chinese conversion (OpenCC, offline). Conversion is character-for-character
in practice, which lets the desktop app swap characters on a web page in place."""

import opencc

_t2s, _s2t = opencc.OpenCC("t2s"), opencc.OpenCC("s2t")


def to_simplified(text: str) -> str:
    return _t2s.convert(text)


def convert(text: str, script: str) -> str:
    """script: "s" (simplified), "t" (traditional), anything else leaves the text as it is."""
    if script == "s":
        return _t2s.convert(text)
    if script == "t":
        return _s2t.convert(text)
    return text

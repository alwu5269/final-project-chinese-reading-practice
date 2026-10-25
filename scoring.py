"""Deterministic read-aloud scoring. No LLM involved, so scores cannot be invented or talked into 100%.

Chinese is scored per character (with tones via pinyin); English is scored per word.
Every function takes lang = "zh" (default) or "en".
"""

import re
from difflib import SequenceMatcher

from pypinyin import Style, pinyin

import script

HAN = re.compile(r"[一-鿿]")


WORD = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)*")
# English scoring units: one written token each, shared by the screen and the scorer so highlights line up.
EN_TOKEN = re.compile(r"\d+/\d+|[½⅓¼¾⅔]|\d+(?:[.,]\d+)*%?°?|&|[A-Za-z]+(?:['’.][A-Za-z]+)*")
NUMBERS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()


def han_only(text: str) -> str:
    return "".join(HAN.findall(text))


def has_text(text: str, lang: str = "zh") -> bool:
    return bool(han_only(text)) if lang == "zh" else len(EN_TOKEN.findall(text)) >= 1


def annotate(text: str, lang: str = "zh") -> list[dict]:
    """The text split into display tokens; w=True marks the ones that get scored (characters or words)."""
    if lang == "en":
        out, last = [], 0
        for m in EN_TOKEN.finditer(text):
            if m.start() > last:
                out.append({"ch": text[last:m.start()], "pinyin": "", "w": False})
            out.append({"ch": m.group(), "pinyin": "", "w": True})
            last = m.end()
        if last < len(text):
            out.append({"ch": text[last:], "pinyin": "", "w": False})
        return out
    han = han_only(text)
    marks = iter(p[0] for p in pinyin(han, style=Style.TONE))  # whole-text call keeps word context (e.g. 行 háng/xíng)
    return [{"ch": ch, "pinyin": next(marks) if HAN.match(ch) else "", "w": bool(HAN.match(ch))} for ch in text]


# Written forms people read out loud differently. Each maps to the spoken words (any of the options counts).
ABBREVIATIONS = {
    "tbsp": ["tablespoon"], "tbs": ["tablespoon"], "tsp": ["teaspoon"], "oz": ["ounce"], "lb": ["pound"], "lbs": ["pounds"],
    "kg": ["kilogram"], "g": ["gram"], "ml": ["milliliter"], "mins": ["minutes"], "min": ["minute"], "hr": ["hour"], "hrs": ["hours"],
    "mr": ["mister"], "mrs": ["missus"], "ms": ["miz"], "dr": ["doctor"], "st": ["street"], "ave": ["avenue"], "vs": ["versus"],
    "etc": ["etcetera"], "approx": ["approximately"], "pkg": ["package"], "qt": ["quart"], "pt": ["pint"], "f": ["fahrenheit"], "c": ["celsius"],
    "no": ["number"], "jan": ["january"], "feb": ["february"], "aug": ["august"], "sept": ["september"], "oct": ["october"], "nov": ["november"], "dec": ["december"],
    "u.s.": ["us"], "ok": ["okay"],
}
SPOKEN_EQUIV = {"tablespoons": "tablespoon", "teaspoons": "teaspoon", "ounces": "ounce", "grams": "gram", "minutes": "minute", "hours": "hour",
                "kilograms": "kilogram", "milliliters": "milliliter", "pounds": "pound", "okay": "okay", "ok": "okay", "percent": "percent"}
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
# Only the core word is required ("half"), so "one half", "a half" and "half a" all count (extra words aren't penalized)
FRACTIONS = {"1/2": "half", "½": "half", "1/3": "third", "⅓": "third", "1/4": "quarter", "¼": "quarter",
             "3/4": "three quarters", "¾": "three quarters", "2/3": "two thirds", "⅔": "two thirds", "1/8": "eighth"}


def _number_words(n: int) -> list[str]:
    if n < 20:
        return [ONES[n]]
    if n < 100:
        return [TENS[n // 10]] + ([ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        return [ONES[n // 100], "hundred"] + (_number_words(n % 100) if n % 100 else [])
    if n < 1_000_000:
        rest = n % 1000
        return _number_words(n // 1000) + ["thousand"] + (_number_words(rest) if rest else [])
    return [str(n)]


def _spoken(token: str) -> list[str]:
    """The words a written token is read as: 'tbsp' -> ['tablespoon'], '350' -> ['three','hundred','fifty']."""
    w = token.lower().replace("’", "'").strip(".")
    if w in FRACTIONS:
        return FRACTIONS[w].split()
    if w == "&":
        return ["and"]
    suffix = []
    if w.endswith("°"):
        w, suffix = w[:-1], ["degrees"]
    if w.endswith("%"):
        w, suffix = w[:-1], ["percent"]
    if re.fullmatch(r"\d{1,3}(,\d{3})+", w):
        w = w.replace(",", "")
    if re.fullmatch(r"\d+\.\d+", w):  # 2.5 -> two point five
        a, b = w.split(".")
        return _number_words(int(a)) + ["point"] + [ONES[int(d)] for d in b] + suffix
    if w.isdigit():
        if suffix:
            return _number_words(int(w)) + suffix
        if len(w) == 4 and 1100 <= int(w) <= 2099 and int(w) % 100:  # years: 2026 -> twenty twenty-six
            return _number_words(int(w) // 100) + _number_words(int(w) % 100)
        return _number_words(int(w))
    if w in ABBREVIATIONS:
        w = ABBREVIATIONS[w][0]
    return [SPOKEN_EQUIV.get(w, w)]


def _expand(text: str) -> tuple[list[str], list[str], list[int]]:
    """Original word tokens, their spoken words, and for each spoken word the index of its original token."""
    originals = EN_TOKEN.findall(text)
    words, owner = [], []
    for i, tok in enumerate(originals):
        for sw in _spoken(tok):
            words.append(sw)
            owner.append(i)
    return originals, words, owner


def compare_en(target: str, heard: str) -> list[dict]:
    """Word-level alignment for English, on spoken forms: 'tbsp' read as 'tablespoon' or '350' as
    'three hundred fifty' is correct. Near-identical spellings (colour/color, plural s) also count."""
    t_words, t, t_owner = _expand(target)
    h_words, h, h_owner = _expand(heard)
    spoken = [{"status": "ok", "heard": w, "j": None} for w in t]  # one entry per spoken target word
    for op, i1, i2, j1, j2 in SequenceMatcher(None, t, h, autojunk=False).get_opcodes():
        for k, i in enumerate(range(i1, i2)):
            j = j1 + k
            if op == "equal":
                spoken[i]["j"] = h_owner[j]
            elif op == "delete" or j >= j2:
                spoken[i].update(status="skipped", heard="")
            elif op == "replace":
                close = SequenceMatcher(None, t[i], h[j]).ratio() >= 0.85
                spoken[i].update(status="homophone" if close else "misread", heard=h_words[h_owner[j]], j=h_owner[j])
    results = [{"ch": w, "status": "ok", "heard": w, "heard_pinyin": ""} for w in t_words]
    rank = {"ok": 0, "homophone": 1, "misread": 3, "skipped": 2}
    for sp, i in zip(spoken, t_owner):  # a written token is as good as its worst spoken word
        r = results[i]
        if "j" not in r and sp["j"] is not None:
            r["j"] = sp["j"]
        if rank[sp["status"]] > rank[r["status"]]:
            r["status"], r["heard"] = sp["status"], sp["heard"]
    for k, r in enumerate(results):  # "350°F" read as "350 degrees": the unit letter is optional
        if r["status"] == "skipped" and r["ch"].lower() in ("f", "c") and k and results[k - 1]["ch"].endswith("°"):
            r["status"] = "ok"
    for r in reversed(results):
        if r["status"] != "skipped":
            break
        r["status"] = "unread"
    return results


def compare(target: str, heard: str, lang: str = "zh") -> list[dict]:
    if lang == "en":
        return compare_en(target, heard)
    return compare_zh(target, heard)


def compare_zh(target: str, heard: str) -> list[dict]:
    """Align the heard transcript to the target, one result per target Chinese character.

    status: ok | homophone (different character, same sound: pronounced fine)
            | tone (same syllable, wrong tone) | misread | skipped
    """
    t, h = han_only(target), han_only(heard)
    t_cmp, h_cmp = script.to_simplified(t), script.to_simplified(h)  # 學 and 学 are the same character for matching
    want_all = [p[0] for p in pinyin(t, style=Style.TONE3, neutral_tone_with_five=True)]  # in-context readings
    heard_all = [p[0] for p in pinyin(h, style=Style.TONE3, neutral_tone_with_five=True)]
    heard_marks = [p[0] for p in pinyin(h)]
    results = [{"ch": c, "status": "ok", "heard": c} for c in t]
    for op, i1, i2, j1, j2 in SequenceMatcher(None, t_cmp, h_cmp, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                results[i1 + k]["j"] = j1 + k
        if op == "delete":
            for i in range(i1, i2):
                results[i].update(status="skipped", heard="")
        elif op == "replace":
            for k, i in enumerate(range(i1, i2)):
                j = j1 + k
                if j >= j2:
                    results[i].update(status="skipped", heard="")
                    continue
                said, want = heard_all[j], want_all[i]
                if said == want:
                    status = "homophone"
                elif said.rstrip("12345") == want.rstrip("12345"):
                    status = "tone"
                else:
                    status = "misread"
                results[i].update(status=status, heard=h[j], heard_pinyin=heard_marks[j], j=j)
    # Characters after the last one you read were not attempted yet (you stopped early), not skipped
    for r in reversed(results):
        if r["status"] != "skipped":
            break
        r["status"] = "unread"
    return results


def add_pauses(results: list[dict], target: str, units: list[dict], lang: str, min_gap: float = 0.6) -> None:
    """Mark a hesitation before a target unit when you paused there and the text has no punctuation break."""
    tokens = [a for a in annotate(target, lang)]
    breaks, k, prev_break = [], 0, True
    for tok in tokens:  # does a punctuation mark (or the start) come right before each scored unit?
        if tok["w"]:
            breaks.append(prev_break)
            prev_break = False
        elif re.search(r"[，。！？、；：,.!?;:—…]", tok["ch"]):
            prev_break = True
    for i, r in enumerate(results):
        j = r.get("j")
        if j is None or j >= len(units) or i >= len(breaks) or breaks[i]:
            continue
        gap = units[j].get("gap_before", 0)
        if gap >= min_gap:
            r["pause"] = round(gap, 1)


def add_tones(results: list[dict], checks: list[dict]) -> None:
    """Attach pitch contours; a clear pitch mismatch on a character that was otherwise heard right becomes a tone slip."""
    for r, c in zip(results, checks):
        r["you"], r["native"] = c["you"], c["native"]
        r["you_shape"], r["native_shape"] = c["you_shape"], c["native_shape"]
        if c["slip"] and r["status"] in ("ok", "homophone"):
            r["status"], r["tone_from_pitch"] = "tone", True


def summarize(results: list[dict], seconds: float) -> dict:
    read = [r for r in results if r["status"] != "unread"]
    good = sum(r["status"] in ("ok", "homophone") for r in read)
    return {
        "accuracy": round(100 * good / (len(read) or 1)),
        "chars": len(read),
        "errors": len(read) - good,
        "unread": len(results) - len(read),
        "pauses": sum(1 for r in read if r.get("pause")),
        "tone_slips": sum(1 for r in read if r.get("tone_from_pitch")),
        "chars_per_minute": round(len(read) / seconds * 60) if seconds > 0 else None,
    }

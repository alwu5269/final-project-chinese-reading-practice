"""Tone and pause analysis from the recording itself (no AI).

Speech-to-text "auto-corrects" tones: it writes 妈 even if you said má. So for each character we
compare the *pitch shape* of your voice with a native reading of the same passage:

1. A native reference reading is synthesized (voice.reference) with word timings.
2. Your recording is lined up with it by dynamic time warping (DTW) on MFCC sound features,
   which tells us where each character is in your audio.
3. Praat (parselmouth) measures the pitch contour of each character in both recordings.
4. Only clear-cut mismatches are flagged: a rise where the native speaker falls (or the reverse),
   or a high level tone said very low (or the reverse). Borderline shapes are never flagged.

Pauses come from Whisper's word timings: a long gap between two words that is not at punctuation.
"""

import numpy as np
import parselmouth

import voice

HAN_LO, HAN_HI = "一", "鿿"
PAUSE_SECONDS = 0.6
STEP = 0.01  # analysis frame step (seconds)


def is_han(c: str) -> bool:
    return HAN_LO <= c <= HAN_HI


# ---------- timings from Whisper (used for pauses) ----------

def timed_units(segments, lang: str) -> list[dict]:
    """Per-character (zh) or per-word (en) start/end times from Whisper word timestamps."""
    units = []
    for seg in segments:
        for w in seg.words or []:
            if lang == "en":
                if w.word.strip():
                    units.append({"ch": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)})
                continue
            chars = [c for c in w.word if is_han(c)]
            step = (w.end - w.start) / max(len(chars), 1)
            units += [{"ch": c, "start": round(w.start + k * step, 2), "end": round(w.start + (k + 1) * step, 2)}
                      for k, c in enumerate(chars)]
    return units


# ---------- pitch and alignment helpers ----------

def _sound(audio: np.ndarray) -> parselmouth.Sound:
    return parselmouth.Sound(audio.astype(np.float64), sampling_frequency=16000)


def _mfcc(snd: parselmouth.Sound) -> np.ndarray:
    m = snd.to_mfcc(number_of_coefficients=12, window_length=0.025, time_step=STEP).to_array()[1:].T  # drop energy
    return (m - m.mean(0)) / (m.std(0) + 1e-6)


def _semitones(snd: parselmouth.Sound) -> tuple[np.ndarray, np.ndarray]:
    pitch = snd.to_pitch(time_step=STEP, pitch_floor=75, pitch_ceiling=500)
    f0, t = pitch.selected_array["frequency"], pitch.xs()
    voiced = f0[f0 > 0]
    ref = np.median(voiced) if len(voiced) else 200.0
    return t, np.where(f0 > 0, 12 * np.log2(np.maximum(f0, 1) / ref), np.nan)


def _contour(t: np.ndarray, st: np.ndarray, a: float, b: float) -> list[float] | None:
    pad = (b - a) * 0.15  # ignore the edges, where neighbours bleed in
    v = st[(t >= a + pad) & (t <= b - pad) & ~np.isnan(st)]
    if len(v) < 4:
        return None
    return [round(float(x), 1) for x in v[np.linspace(0, len(v) - 1, 5).astype(int)]]


def dtw(user: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """For each user frame, the matching reference frame. Open end: you may stop before the passage ends.

    Steps per user frame: stay on the same reference frame (you are slower) or advance 1-2 frames.
    Each row depends only on the previous one, so every row is a single vectorized numpy step.
    """
    n, m = len(user), len(ref)
    cost = np.sqrt(((user[:, None, :] - ref[None, :, :]) ** 2).sum(-1)) if n * m < 6e6 else None
    big = np.inf
    prev = np.full(m, big)
    rowcost = cost[0] if cost is not None else np.linalg.norm(ref - user[0], axis=1)
    prev[:3] = np.cumsum(rowcost[:3])  # allow a little slack at the start
    back = np.zeros((n, m), np.int8)
    for i in range(1, n):
        rowcost = cost[i] if cost is not None else np.linalg.norm(ref - user[i], axis=1)
        stay = prev
        one = np.concatenate(([big], prev[:-1]))
        two = np.concatenate(([big, big], prev[:-2]))
        choices = np.vstack([stay, one, two])
        back[i] = np.argmin(choices, 0)
        prev = rowcost + choices[back[i], np.arange(m)]
    j = int(np.argmin(prev))
    path = np.zeros(n, int)
    for i in range(n - 1, -1, -1):
        path[i] = j
        j = max(j - int(back[i, j]), 0)
    return path


def _ref_char_times(text: str, words: tuple, t: np.ndarray | None = None, st: np.ndarray | None = None) -> list[tuple[str, float, float]]:
    """Split the native voice's word timings into per-character times.

    The voice service's timings run slightly ahead of its audio (mp3 encoder delay), so we try small
    shifts and keep the one that puts the middle of each character on voiced sound most often.
    """
    out = []
    for word, a, b in words:
        chars = [c for c in word if is_han(c)]
        step = (b - a) / max(len(chars), 1)
        out += [(c, a + k * step, a + (k + 1) * step) for k, c in enumerate(chars)]
    if t is None or not out:
        return out
    voiced = ~np.isnan(st)

    def coverage(shift):
        total = 0.0
        for _, a, b in out:
            v = voiced[(t >= a + shift + (b - a) * .3) & (t <= b + shift - (b - a) * .3)]
            total += v.mean() if len(v) else 0.0
        return total

    best = max(np.arange(0, 0.25, 0.01), key=coverage)
    return [(c, a + best, b + best) for c, a, b in out]


def _shape(c: list[float] | None) -> str:
    if c is None:
        return ""
    start, end, lo, mean = c[0], c[-1], min(c), sum(c) / 5
    if start - end >= 2.5:
        return "falling"
    if end - start >= 2.5:
        return "rising"
    if 0 < c.index(lo) < 4 and min(start, end) - lo >= 1.0:
        return "dipping"
    return "high and level" if mean > 1 else ("low" if mean < -2 else "level")


def _clear_mismatch(you: list[float], native: list[float]) -> bool:
    ys, ns = you[-1] - you[0], native[-1] - native[0]
    if ns >= 2.5 and ys <= -2.5:       # should rise, you fell
        return True
    if ns <= -3.0 and ys >= 2.5:       # should fall, you rose
        return True
    ym, nm = sum(you) / 5, sum(native) / 5
    if abs(ns) < 1.5 and nm > 1.5 and ym < nm - 5 and abs(ys) < 2.5:   # high level said low
        return True
    if nm < -2.5 and ym > nm + 5 and abs(ys) < 1.5:                    # low said high and level
        return True
    return False


def check_tones(audio: np.ndarray, target: str) -> list[dict]:
    """One entry per Chinese character of `target`: your contour, the native contour and a clear-mismatch flag."""
    ref_audio, words = voice.reference(target, "zh")
    user_snd, ref_snd = _sound(audio), _sound(ref_audio)
    path = dtw(_mfcc(user_snd), _mfcc(ref_snd))
    ut, ust = _semitones(user_snd)
    rt, rst = _semitones(ref_snd)
    out = []
    for ch, a, b in _ref_char_times(target, words, rt, rst):
        frames = np.where((path * STEP >= a) & (path * STEP < b))[0]
        native = _contour(rt, rst, a, b)
        you = _contour(ut, ust, frames[0] * STEP, (frames[-1] + 1) * STEP) if len(frames) >= 4 else None
        slip = bool(you and native and _clear_mismatch(you, native))
        out.append({"ch": ch, "you": you, "native": native, "you_shape": _shape(you), "native_shape": _shape(native), "slip": slip})
    return out

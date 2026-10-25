"""Local speech-to-text with Whisper (runs on this computer, no API key, no audio leaves the machine)."""

import io
import os
import threading
import uuid
import wave
from collections import OrderedDict

import numpy as np
from faster_whisper import WhisperModel

import tones

MODEL_NAME = os.environ.get("WHISPER_MODEL", "small")  # "base" is faster but less accurate
_model = None
_lock = threading.Lock()


def model() -> WhisperModel:
    global _model
    with _lock:
        if _model is None:
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")  # downloads once (~480 MB for small)
    return _model


def preload() -> None:
    threading.Thread(target=model, daemon=True).start()


RECENT: "OrderedDict[str, tuple[np.ndarray, list[dict]]]" = None  # set below


def transcribe(wav_bytes: bytes, lang: str = "zh") -> dict:
    """16-bit mono WAV in: text, per-unit timings, and an id so scoring can analyze tones on the same audio."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1 or w.getframerate() != 16000:
            raise ValueError("Expected 16 kHz mono 16-bit WAV")
        audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    # A neutral prompt nudges Whisper to simplified characters; it never includes the target passage,
    # since that would make Whisper "hear" the correct text and hide mistakes.
    prompt = "以下是普通话的句子。" if lang == "zh" else None
    segments, _ = model().transcribe(audio, language=lang, initial_prompt=prompt, vad_filter=True, word_timestamps=True)
    segments = list(segments)
    units = tones.timed_units(segments, lang)
    for k, u in enumerate(units):
        u["gap_before"] = round(u["start"] - units[k - 1]["end"], 2) if k else 0.0
    audio_id = uuid.uuid4().hex
    RECENT[audio_id] = (audio, units)
    while len(RECENT) > 20:  # keep only the last few recordings, in memory
        RECENT.popitem(last=False)
    return {"text": "".join(s.text for s in segments).strip(), "audio_id": audio_id, "units": units}


RECENT = OrderedDict()

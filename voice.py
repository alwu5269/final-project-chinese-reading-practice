"""Natural Mandarin (and English) voice for "Hear it" using Microsoft Edge's neural voices (edge-tts, no API key).

Only the passage text is sent; results are cached in memory. The page falls back to the
browser's built-in voice if this service is unreachable.
"""

import asyncio
import io
from functools import lru_cache

import av
import edge_tts
import numpy as np

VOICES = {"zh": "zh-CN-XiaoxiaoNeural", "en": "en-US-AriaNeural"}


@lru_cache(maxsize=256)
def synthesize(text: str, slow: bool = False, lang: str = "zh") -> bytes:
    async def run() -> bytes:
        audio = b""
        async for chunk in edge_tts.Communicate(text, VOICES.get(lang, VOICES["zh"]), rate="-30%" if slow else "-10%").stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        return audio

    audio = asyncio.run(run())
    if not audio:
        raise RuntimeError("no audio returned")
    return audio


@lru_cache(maxsize=64)
def reference(text: str, lang: str = "zh") -> tuple[np.ndarray, tuple]:
    """A native reading of `text` at normal speed: 16 kHz audio plus (word, start, end) timings in seconds."""
    async def run():
        audio, words = b"", []
        comm = edge_tts.Communicate(text, VOICES.get(lang, VOICES["zh"]), boundary="WordBoundary")
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append((chunk["text"], start, start + chunk["duration"] / 1e7))
        return audio, words

    mp3, words = asyncio.run(run())
    container = av.open(io.BytesIO(mp3))
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    chunks = [f.to_ndarray().reshape(-1) for frame in container.decode(audio=0) for f in resampler.resample(frame)]
    chunks += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]  # flush
    return np.concatenate(chunks).astype(np.float32) / 32768, tuple(words)

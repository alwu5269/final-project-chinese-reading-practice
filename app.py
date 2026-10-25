"""MaoMao Read: read Chinese (or English, for testers) aloud and see which characters or words you misread."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agents
import dictionary
import fetcher
import levels
import scoring
import script
import sources
import speech
import tones
import voice

ROOT = Path(__file__).parent
app = FastAPI(title="Read Aloud")
speech.preload()


Lang = str  # "zh" (default) or "en"


class PrepareIn(BaseModel):
    text: str
    lang: Lang = "zh"
    script: str = ""  # "s" or "t": convert Chinese text to simplified / traditional first


class ScoreIn(BaseModel):
    text: str
    heard: str
    seconds: float = 0
    coach: bool = True  # review cards skip the AI coach to save tokens
    lang: Lang = "zh"
    audio_id: str = ""  # from /api/transcribe: enables tone and pause checks on the same recording


class ProfileIn(BaseModel):
    kind: str = "news"  # a key of sources.CATEGORIES
    lang: Lang = "zh"
    script: str = ""
    level: int = 2
    interests: list[str] = []
    exclude: list[str] = []


class FetchIn(BaseModel):
    url: str
    lang: Lang = "zh"
    script: str = ""


class ConvertIn(BaseModel):
    text: str
    script: str = "s"


def clean_lang(lang: str) -> str:
    return "en" if lang == "en" else "zh"


def check_text(text: str, lang: str = "zh") -> str:
    text = text.strip()
    if not scoring.has_text(text, lang):
        raise HTTPException(400, "Paste some Chinese text first." if lang == "zh" else "Paste some English text first.")
    if len(text) > agents.MAX_TEXT_CHARS:
        raise HTTPException(400, f"Please keep passages under {agents.MAX_TEXT_CHARS} characters.")
    return text


def run_agent(fn, *args):
    try:
        return fn(*args)
    except agents.BudgetExceeded as e:
        raise HTTPException(429, str(e))
    except agents.BadRequestError as e:
        if "content_filter" in str(e):
            raise HTTPException(400, "Blocked by the safety filter: this text looks like it contains instructions aimed at the AI.")
        raise HTTPException(502, "AI agent error: bad request")
    except Exception as e:  # keep the page usable even if the model call fails
        raise HTTPException(502, f"AI agent error: {type(e).__name__}")


@app.post("/api/prepare")
def prepare(body: PrepareIn):
    lang = clean_lang(body.lang)
    text = check_text(body.text, lang)
    if lang == "zh":
        text = script.convert(text, body.script)
    out = {"text": text, "chars": scoring.annotate(text, lang), **run_agent(agents.prepare, text, lang)}
    if lang == "zh":  # the level shown is measured against the HSK word list, not the AI's guess
        m = levels.measure(text)
        out.update(hsk_level=m["hsk"] or out["hsk_level"], known=m["known"])
    return out


@app.post("/api/score")
def score(body: ScoreIn):
    lang = clean_lang(body.lang)
    text = check_text(body.text, lang)
    results = scoring.compare(text, body.heard, lang)
    recording = speech.RECENT.get(body.audio_id)
    if recording:
        audio, units = recording
        scoring.add_pauses(results, text, units, lang)
        if lang == "zh":
            try:
                scoring.add_tones(results, tones.check_tones(audio, text))
            except Exception:  # the native reference voice is online; scoring still works without it
                pass
    stats = scoring.summarize(results, body.seconds)
    errors = [{k: r[k] for k in ("ch", "status", "heard", "heard_pinyin", "you_shape", "native_shape", "pause") if r.get(k)}
              for r in results if r["status"] in ("tone", "misread", "skipped") or r.get("pause")]
    feedback = run_agent(agents.coach, text, errors, stats, lang) if body.coach else None
    return {"results": results, "stats": stats, "coach": feedback}


@app.post("/api/transcribe")
async def transcribe(request: Request, lang: str = "zh"):
    audio = await request.body()
    if len(audio) > 20_000_000:
        raise HTTPException(400, "Recording too long. Please read one passage at a time.")
    try:
        return speech.transcribe(audio, clean_lang(lang))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/tts")
def tts(text: str, slow: bool = False, lang: str = "zh"):
    text = text.strip()[: agents.MAX_TEXT_CHARS]
    if not text:
        raise HTTPException(400, "Nothing to say.")
    try:
        return Response(voice.synthesize(text, slow, clean_lang(lang)), media_type="audio/mpeg")
    except Exception:
        raise HTTPException(502, "Voice service unavailable")


@app.post("/api/fetch")
def fetch(body: FetchIn):
    try:
        return convert_article(fetcher.fetch_article(body.url, lang=clean_lang(body.lang)), body.script)
    except fetcher.FetchError as e:
        raise HTTPException(400, str(e))


def clean_profile(body: ProfileIn) -> tuple[int, list[str]]:
    lang = clean_lang(body.lang)
    defaults = sources.DEFAULT_TOPICS[lang]
    return max(1, min(body.level, 6)), defaults.get(body.kind, defaults[""])


def verify(article: dict, lang: str = "zh") -> dict | None:
    """Open each suggested link ourselves: drops off-list, invented, dead, private or wrong-language pages."""
    source = sources.source_of(article["url"], lang)
    if not source:
        return None
    article = {**article, "source": source["name"], "script": source["script"]}
    try:
        page = fetcher.fetch_article(article["url"], timeout=5, lang=lang)  # slow sites are dropped, not waited on
    except fetcher.FetchError:
        return None
    article = {**article, "title": article["title"] or page["title"], "passages": page["passages"]}
    if lang == "zh":
        article["measured_hsk"] = levels.measure("".join(page["passages"]))["hsk"]
    return article


def convert_article(a: dict, to: str) -> dict:
    return {**a, "title": script.convert(a.get("title", ""), to), "passages": [script.convert(p, to) for p in a.get("passages", [])]}


@app.post("/api/convert")
def convert(body: ConvertIn):
    return {"text": script.convert(body.text[:200_000], body.script)}


@app.post("/api/find")
def find(body: ProfileIn):
    level, interests = clean_profile(body)
    lang = clean_lang(body.lang)
    kind = body.kind if body.kind in sources.for_lang(lang) else "news"
    exclude, unreachable, articles, rounds = body.exclude[-20:], [], [], []
    for _ in range(agents.FIND_MAX_ROUNDS):  # bounded retry loop: the agent can never search forever
        found = run_agent(agents.find_articles, level, interests, kind, exclude, unreachable, lang)
        with ThreadPoolExecutor(8) as pool:
            checked = list(pool.map(lambda a: verify(a, lang), found["articles"]))
        bad = [a["url"] for a, ok in zip(found["articles"], checked) if not ok]
        for a in checked:  # skip duplicates (same link or same title)
            if a and all(a["url"] != x["url"] and a["title"] != x["title"] for x in articles):
                articles.append(a)
        rounds.append({"suggested": len(checked), "dropped": len(bad), "usage": found["_usage"]})
        if len(articles) >= 2:
            break
        unreachable += bad
        exclude += [a["url"] for a in articles]
    too_hard = False
    if lang == "zh":  # closest measured level first; say so when the sites have nothing near this level
        articles.sort(key=lambda a: abs(a["measured_hsk"] - level))
        too_hard = bool(articles) and all(a["measured_hsk"] > level + 1 for a in articles)
        if body.script:
            articles = [convert_article(a, body.script) for a in articles]
    return {"articles": articles, "rounds": rounds, "too_hard": too_hard}


@app.post("/api/story")
def story(body: ProfileIn):
    level, interests = clean_profile(body)
    lang = clean_lang(body.lang)
    out = run_agent(agents.write_story, level, interests, lang)
    if lang == "zh" and levels.measure(out["story"])["hsk"] > level + 1:  # one retry if it came out too hard
        out = run_agent(agents.write_story, level, interests, lang)
    out["story"] = out["story"][: agents.MAX_TEXT_CHARS]
    if lang == "zh":
        out["measured_hsk"] = levels.measure(out["story"])["hsk"]
    return out


@app.get("/api/define")
def define(text: str, i: int):
    return dictionary.define(text[:600], i) or {"word": text[i:i + 1] if 0 <= i < len(text) else "", "entries": []}


@app.get("/api/categories")
def categories(lang: str = "zh"):
    lang = clean_lang(lang)
    table = sources.for_lang(lang)
    return [{"kind": k, "label": label, "sources": [x["name"] for x in table[k]]}
            for k, label in sources.categories(lang).items()]


@app.get("/api/samples")
def samples(lang: str = "zh"):
    name = "samples_en.json" if clean_lang(lang) == "en" else "samples.json"
    return json.loads((ROOT / "samples" / name).read_text(encoding="utf-8"))


@app.get("/api/usage")
def usage():
    return {"session_tokens": agents.tokens_used, "budget": agents.SESSION_TOKEN_BUDGET}


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

"""MaoMao Read: read Chinese (or English, for testers) aloud and see which characters or words you misread."""

import json
import multiprocessing
import random
from functools import lru_cache
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, wait
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import agents
import dictionary
import feeds
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
# Text-extraction helper processes re-import this module; only the main app does the startup work
MAIN_PROCESS = multiprocessing.parent_process() is None
if MAIN_PROCESS:
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


@lru_cache(maxsize=512)
def open_page(url: str, lang: str) -> dict | None:
    """Download in a thread; pull the article text out in a helper process, so several pages are
    cleaned up truly in parallel (text extraction is CPU work that Python threads can't share)."""
    try:
        html = fetcher.fetch_text(url, timeout=5)  # slow sites are dropped, not waited on
        return extractor().submit(fetcher.article_from_html, html, url, lang).result(timeout=10)
    except Exception:
        return None


@lru_cache(maxsize=1)
def extractor() -> ProcessPoolExecutor:
    return ProcessPoolExecutor(4)


def verify(article: dict, lang: str = "zh") -> dict | None:
    """Open each candidate link ourselves: drops off-list, dead, private or wrong-language pages."""
    source = sources.source_of(article["url"], lang)
    if not source:
        return None
    article = {**article, "source": source["name"], "script": source["script"]}
    page = open_page(article["url"], lang)
    if not page or not page["passages"]:
        return None
    # list pages and short feed titles give poor titles; the page's own title is better there
    title = article["title"] if len(article["title"]) >= 4 and "page" not in source else page["title"] or article["title"]
    article = {**article, "title": title, "passages": page["passages"]}
    if lang == "zh":
        article["measured_hsk"] = levels.measure("".join(page["passages"]))["hsk"]
    return article


def convert_article(a: dict, to: str) -> dict:
    return {**a, "title": script.convert(a.get("title", ""), to), "passages": [script.convert(p, to) for p in a.get("passages", [])]}


@app.post("/api/convert")
def convert(body: ConvertIn):
    return {"text": script.convert(body.text[:200_000], body.script)}


FIND_CANDIDATES = 12  # links opened per search
OPEN_DEADLINE = 8     # seconds to wait for those pages; the rest are skipped this time
POOL = ThreadPoolExecutor(32)
if MAIN_PROCESS:
    POOL.submit(feeds.warm)  # read every site's feed in the background at startup (no AI, no tokens)
    POOL.submit(lambda: extractor().submit(len, "").result())  # start the text-extraction helpers early
SNIPPET_CHARS = 80    # opening characters of each candidate shown to the Finder


@app.post("/api/find")
def find(body: ProfileIn):
    level, interests = clean_profile(body)
    lang = clean_lang(body.lang)
    kind = body.kind if body.kind in sources.for_lang(lang) else "news"
    # 1. Code: newest links from the category's sites (feeds.py), opened and measured. No AI yet.
    links = feeds.candidates(kind, lang, body.exclude[-30:])[:FIND_CANDIDATES]
    jobs = [POOL.submit(verify, a, lang) for a in links]
    wait(jobs, timeout=OPEN_DEADLINE)  # pages still loading are skipped this time (and cached for next time)
    checked = []
    for job in jobs:  # skip failures, late pages and duplicates (same title)
        a = job.result() if job.done() else None
        if a and all(a["title"] != x["title"] for x in checked):
            checked.append(a)
    # Real sites rarely have HSK 1-3 text: then a story written at this level leads the list
    too_hard = lang == "zh" and all(a["measured_hsk"] > level + 1 for a in checked)
    story_job = POOL.submit(written_story, level, interests, lang) if too_hard else None
    # 2. Finder agent: picks the best few for this learner from titles, snippets and measured levels
    articles, rounds = [], [{"suggested": len(links), "dropped": len(links) - len(checked)}]
    if checked:
        menu = [{"id": i, "title": a["title"][:80], "source": a["source"], "snippet": a["passages"][0][:SNIPPET_CHARS],
                 **({"measured_hsk": a["measured_hsk"]} if lang == "zh" else {})} for i, a in enumerate(checked)]
        found = run_agent(agents.find_articles, level, interests, kind, menu, lang)
        rounds[0]["usage"] = found["_usage"]
        for p in found["picks"]:
            if 0 <= p["id"] < len(checked) and checked[p["id"]] not in articles:  # ids outside the list are ignored
                articles.append({**checked[p["id"]], "why": p["why"], "estimated_hsk": p["estimated_level"]})
    if lang == "zh":
        articles.sort(key=lambda a: abs(a["measured_hsk"] - level))  # closest measured level first
        if story_job:
            s = story_job.result()
            articles.insert(0, {"title": f"{s['title']} · {s['english_title']}", "url": "", "source": "Written by Mao",
                                "script": "simplified", "why": "A short story written at your level for this category.",
                                "passages": [s["story"]], "measured_hsk": s["measured_hsk"]})
        if body.script:
            articles = [convert_article(a, body.script) for a in articles]
    return {"articles": articles, "rounds": rounds, "too_hard": too_hard}


STORY_IDEAS = ["a rainy day", "a lost pet", "a birthday", "a trip to the market", "cooking with family", "a new friend",
               "a day at school", "a visit to grandma", "a weekend at the park", "learning something new", "a small mistake",
               "a phone call", "waiting for the bus", "a gift", "a sick day", "a good meal", "the first snow", "helping a neighbour"]
STORY_REVISIONS = 2  # rewrites asked for when a story measures above the level


def written_story(level: int, interests: list[str], lang: str) -> dict:
    """A story at the learner's level. In Chinese the level is checked by code (levels.py): a draft above
    the level goes back to the Writer with the exact words to replace, at most STORY_REVISIONS times."""
    idea = random.choice(STORY_IDEAS)  # also keeps repeat requests from getting the same cached story
    allowed = levels.words_up_to(level) if lang == "zh" and level <= 3 else None
    out = run_agent(agents.write_story, level, interests, lang, idea, allowed)
    for _ in range(STORY_REVISIONS if lang == "zh" else 0):
        if levels.measure(out["story"])["hsk"] <= level:
            break
        hard = levels.hard_words(out["story"], level)[:20]
        draft = run_agent(agents.write_story, level, interests, lang, idea, allowed,
                          {"story": out["story"], "replace_words": hard})
        if levels.measure(draft["story"])["hsk"] <= levels.measure(out["story"])["hsk"]:
            out = draft
    out["story"] = out["story"][: agents.MAX_TEXT_CHARS]
    if lang == "zh":
        out["measured_hsk"] = levels.measure(out["story"])["hsk"]
    return out


@app.post("/api/story")
def story(body: ProfileIn):
    level, interests = clean_profile(body)
    return written_story(level, interests, clean_lang(body.lang))


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


@app.middleware("http")
async def no_stale_pages(request: Request, call_next):
    """The desktop window keeps a persistent cache; never let it keep an old copy of the app itself."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

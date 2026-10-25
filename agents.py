"""LLM agents (gpt-6-luna via Portkey). They explain and coach; they never produce scores."""

import json
import os
import time
from pathlib import Path

from openai import BadRequestError, OpenAI  # noqa: F401  (BadRequestError re-exported for app.py)

ROOT = Path(__file__).parent
MODEL = "gpt-6-luna"
MAX_TEXT_CHARS = 600            # longer passages are rejected before any API call
SESSION_TOKEN_BUDGET = 500_000  # app refuses LLM calls once this many tokens are used
USAGE_LOG = ROOT / "output" / "usage_log.jsonl"


def load_env() -> None:
    """Look for .env in the repo folder first, then one level up."""
    for path in (ROOT / ".env", ROOT.parent / ".env"):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))
            return


load_env()
_client = None
tokens_used = 0


def client() -> OpenAI:
    global _client
    if _client is None:
        if os.environ.get("PORTKEY_API_KEY"):
            _client = OpenAI(api_key=os.environ["PORTKEY_API_KEY"], base_url="https://api.portkey.ai/v1")
        elif os.environ.get("OPENAI_API_KEY"):
            _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        else:
            raise RuntimeError("No PORTKEY_API_KEY or OPENAI_API_KEY found in .env")
    return _client


class BudgetExceeded(Exception):
    pass


def _prompt(name: str, lang: str = "zh") -> str:
    folder = ROOT / "prompts" / ("en" if lang == "en" else "")
    return (folder / f"{name}.md").read_text(encoding="utf-8")


def _call(agent: str, payload: dict, schema: dict, tools: list | None = None, effort: str | None = None, lang: str = "zh") -> dict:
    """One structured call. User content is passed as JSON data, never as instructions."""
    global tokens_used
    if tokens_used >= SESSION_TOKEN_BUDGET:
        raise BudgetExceeded(f"Token budget of {SESSION_TOKEN_BUDGET} reached for this session. Restart the app to reset it.")
    start = time.time()
    resp = client().responses.create(
        model=MODEL,
        instructions=_prompt(agent, lang),
        input=json.dumps(payload, ensure_ascii=False),
        text={"format": {"type": "json_schema", "name": agent, "schema": schema, "strict": True}},
        **({"tools": tools} if tools else {}),
        **({"reasoning": {"effort": effort}} if effort else {}),
    )
    u = resp.usage
    cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
    tokens_used += u.total_tokens
    record = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "agent": agent,
        "lang": lang,
        "input_tokens": u.input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": u.output_tokens,
        "tool_calls": sum(o.type.endswith("_call") for o in resp.output),
        "seconds": round(time.time() - start, 2),
    }
    USAGE_LOG.parent.mkdir(exist_ok=True)
    with USAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    out = json.loads(resp.output_text)
    out["_usage"] = record
    return out


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


STR = {"type": "string"}

PREPARE_SCHEMA = _obj({
    "translation": STR,
    "hsk_level": {"type": "integer"},
    "level_reason": STR,
    "suspicious_instructions": {"type": "boolean"},
})

COACH_SCHEMA = _obj({
    "summary": STR,
    "tips": {"type": "array", "items": _obj({"chars": STR, "tip": STR})},
    "practice_sentences": {"type": "array", "items": _obj({"chinese": STR, "english": STR})},
    "suspicious_instructions": {"type": "boolean"},
})


def prepare(text: str, lang: str = "zh") -> dict:
    """Leveler agent: translate the passage and estimate its level (HSK, or CEFR in English mode)."""
    return _call("leveler", {"passage": text}, PREPARE_SCHEMA, lang=lang)


def coach(text: str, errors: list[dict], stats: dict, lang: str = "zh") -> dict:
    """Coach agent: explain the misread characters (or words) and write targeted practice sentences."""
    return _call("coach", {"passage": text, "errors": errors, "stats": stats}, COACH_SCHEMA, lang=lang)


FIND_SCHEMA = _obj({
    "picks": {"type": "array", "items": _obj({"id": {"type": "integer"}, "why": STR, "estimated_level": {"type": "integer"}})},
})

STORY_SCHEMA = _obj({"title": STR, "story": STR, "english_title": STR})


def find_articles(level: int, interests: list[str], kind: str, candidates: list[dict], lang: str = "zh") -> dict:
    """Finder agent: picks the best few of the candidate articles the app already fetched (feeds.py).

    No web search: the candidates are real, opened pages, so the agent only judges topic and fit,
    from a title, a short opening snippet and (in Chinese) the measured HSK level.
    """
    payload = {"level": level, "interests": interests, "kind": kind, "candidates": candidates}
    return _call("finder", payload, FIND_SCHEMA, effort="low", lang=lang)


def write_story(level: int, interests: list[str], lang: str = "zh") -> dict:
    """Writer agent: a short graded story when real articles would be too hard."""
    return _call("writer", {"hsk_level": level, "interests": interests}, STORY_SCHEMA, lang=lang)

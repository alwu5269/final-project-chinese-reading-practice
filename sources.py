"""Curated sites the Finder may search. Every one was checked to load and give clean article text."""

from urllib.parse import urlparse

CATEGORIES = {  # shown as chips in the app, in this order
    "news": "📰 News",
    "stories": "🧸 Kids' stories",
    "science": "🔬 Science & tech",
    "food": "🍜 Food & recipes",
    "culture": "🎨 Culture & life",
    "sports": "⚽ Sports",
    "encyclopedia": "📚 Encyclopedia",
}

# What the Finder looks for in each category (there is no interests picker; the category is the choice).
DEFAULT_TOPICS = {
    "zh": {"news": ["今日热门新闻"], "stories": ["动物", "家庭", "友谊"], "science": ["动物与自然", "日常科学"], "food": ["家常菜"],
           "culture": ["生活", "文化"], "sports": ["热门体育新闻"], "encyclopedia": ["动物", "美食", "城市"], "": ["日常生活"]},
    "en": {"news": ["today's top stories"], "stories": ["animals", "family", "friendship"], "science": ["animals and nature", "everyday science"],
           "food": ["easy everyday recipes"], "sports": ["major sports news"], "encyclopedia": ["animals", "food", "cities"], "": ["everyday life"]},
}

SOURCES = {
    "news": [
        {"domain": "bbc.com", "name": "BBC 中文", "script": "simplified", "note": "use bbc.com/zhongwen/simp articles"},
        {"domain": "voachinese.com", "name": "美国之音", "script": "simplified", "note": ""},
        {"domain": "dw.com", "name": "德国之声", "script": "simplified", "note": "use dw.com/zh articles"},
        {"domain": "zaobao.com.sg", "name": "联合早报", "script": "simplified", "note": "Singapore"},
        {"domain": "cn.chinadaily.com.cn", "name": "中国日报", "script": "simplified", "note": ""},
        {"domain": "cna.com.tw", "name": "中央社", "script": "traditional", "note": "Taiwan"},
    ],
    "stories": [
        {"domain": "mdnkids.com", "name": "国语日报", "script": "traditional", "note": "Taiwan children's newspaper: stories, fables, kids' news"},
    ],
    "science": [
        {"domain": "pansci.asia", "name": "泛科学", "script": "traditional", "note": "popular science"},
        {"domain": "natgeomedia.com", "name": "国家地理", "script": "traditional", "note": "nature, animals, science"},
        {"domain": "ifanr.com", "name": "爱范儿", "script": "simplified", "note": "consumer tech"},
        {"domain": "technews.tw", "name": "科技新报", "script": "traditional", "note": "tech news"},
    ],
    "food": [
        {"domain": "xiachufang.com", "name": "下厨房", "script": "simplified", "note": "single recipe pages (xiachufang.com/recipe/...)"},
        {"domain": "icook.tw", "name": "爱料理", "script": "traditional", "note": "single recipe pages (icook.tw/recipes/...)"},
    ],
    "culture": [
        {"domain": "thenewslens.com", "name": "关键评论网", "script": "traditional", "note": "society, culture, lifestyle"},
        {"domain": "cw.com.tw", "name": "天下", "script": "traditional", "note": "features"},
        {"domain": "theinitium.com", "name": "端传媒", "script": "simplified", "note": "some articles are paywalled"},
        {"domain": "businessweekly.com.tw", "name": "商业周刊", "script": "traditional", "note": "lifestyle and business features"},
    ],
    "sports": [
        {"domain": "sports.ltn.com.tw", "name": "自由时报体育", "script": "traditional", "note": ""},
    ],
    "encyclopedia": [
        {"domain": "zh.wikipedia.org", "name": "维基百科", "script": "mixed", "note": "article pages only (/wiki/...); better for HSK 5+"},
    ],
}


# English practice mode (for testers who don't read Chinese)
CATEGORIES_EN = {
    "news": "📰 News",
    "stories": "🧸 Kids' stories",
    "science": "🔬 Science",
    "food": "🍜 Food & recipes",
    "encyclopedia": "📚 Encyclopedia",
}

SOURCES_EN = {
    "news": [
        {"domain": "bbc.com", "name": "BBC News", "script": "english", "note": "bbc.com/news articles"},
        {"domain": "npr.org", "name": "NPR", "script": "english", "note": ""},
    ],
    "stories": [
        {"domain": "storynory.com", "name": "Storynory", "script": "english", "note": "children's stories and fables"},
    ],
    "science": [
        {"domain": "smithsonianmag.com", "name": "Smithsonian", "script": "english", "note": ""},
        {"domain": "science.nasa.gov", "name": "NASA Science", "script": "english", "note": ""},
        {"domain": "snexplores.org", "name": "Science News Explores", "script": "english", "note": "written for students"},
    ],
    "food": [
        {"domain": "bbcgoodfood.com", "name": "BBC Good Food", "script": "english", "note": "single recipe pages"},
    ],
    "encyclopedia": [
        {"domain": "simple.wikipedia.org", "name": "Simple English Wikipedia", "script": "english", "note": "best for lower levels"},
        {"domain": "en.wikipedia.org", "name": "Wikipedia", "script": "english", "note": "article pages only"},
    ],
}


def for_lang(lang: str) -> dict:
    return SOURCES_EN if lang == "en" else SOURCES


def categories(lang: str) -> dict:
    return CATEGORIES_EN if lang == "en" else CATEGORIES


def domains(kind: str, lang: str = "zh") -> list[str]:
    table = for_lang(lang)
    return [s["domain"] for s in table.get(kind, table["news"])]


def source_of(url: str, lang: str = "zh") -> dict | None:
    host = (urlparse(url).hostname or "").lower()
    for group in for_lang(lang).values():
        for s in group:
            if host == s["domain"] or host.endswith("." + s["domain"]):
                return s
    return None

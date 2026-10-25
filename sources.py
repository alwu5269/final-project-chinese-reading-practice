"""Curated sites the Finder picks from. Every one was checked to load and give clean article text.

Each site says where the app reads its newest article links (no AI, no web search):
- rss: the site's RSS/Atom feed
- page + links: a "latest" page, and a pattern that matches article links on it
- wiki + category: a random handful of Wikipedia's best articles (its featured-article category)
"""

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
    "en": {"news": ["today's top stories"], "science": ["animals and nature", "everyday science"],
           "food": ["easy everyday recipes"], "sports": ["major sports news"], "encyclopedia": ["animals", "food", "cities"], "": ["everyday life"]},
}

SOURCES = {
    "news": [
        {"domain": "bbc.com", "name": "BBC 中文", "script": "simplified", "rss": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"},
        {"domain": "voachinese.com", "name": "美国之音", "script": "simplified", "rss": "https://www.voachinese.com/api/"},
        {"domain": "dw.com", "name": "德国之声", "script": "simplified", "rss": "https://rss.dw.com/rdf/rss-chi-all"},
        {"domain": "zaobao.com.sg", "name": "联合早报", "script": "simplified", "page": "https://www.zaobao.com.sg/realtime/china", "links": r"/(?:realtime|news)/[a-z-]+/story\d+-\d+"},
        {"domain": "cn.chinadaily.com.cn", "name": "中国日报", "script": "simplified", "page": "https://cn.chinadaily.com.cn/", "links": r"//cn\.chinadaily\.com\.cn/a/\d{6}/\d+/\w+\.html"},
        {"domain": "cna.com.tw", "name": "中央社", "script": "traditional", "rss": "https://feeds.feedburner.com/rsscna/intworld"},
    ],
    "stories": [
        {"domain": "mdnkids.com", "name": "国语日报", "script": "traditional", "rss": "https://www.mdnkids.com/rss"},
    ],
    "science": [
        {"domain": "pansci.asia", "name": "泛科学", "script": "traditional", "rss": "https://pansci.asia/feed"},
        {"domain": "natgeomedia.com", "name": "国家地理", "script": "traditional", "page": "https://www.natgeomedia.com/", "links": r"/[a-z-]+/article/content-\d+\.html"},
        {"domain": "ifanr.com", "name": "爱范儿", "script": "simplified", "rss": "https://www.ifanr.com/feed"},
        {"domain": "technews.tw", "name": "科技新报", "script": "traditional", "rss": "https://technews.tw/feed/"},
    ],
    "food": [
        {"domain": "xiachufang.com", "name": "下厨房", "script": "simplified", "page": "https://www.xiachufang.com/explore/", "links": r"/recipe/\d+/"},
        {"domain": "icook.tw", "name": "爱料理", "script": "traditional", "rss": "https://icook.tw/feeds/latest.rss"},
    ],
    "culture": [
        {"domain": "thenewslens.com", "name": "关键评论网", "script": "traditional", "rss": "https://feeds.feedburner.com/TheNewsLens"},
        {"domain": "cw.com.tw", "name": "天下", "script": "traditional", "rss": "https://www.cw.com.tw/RSS/cw_content.xml"},
        {"domain": "theinitium.com", "name": "端传媒", "script": "simplified", "rss": "https://theinitium.com/feed/"},
    ],
    "sports": [
        {"domain": "sports.ltn.com.tw", "name": "自由时报体育", "script": "traditional", "rss": "https://news.ltn.com.tw/rss/sports.xml"},
    ],
    "encyclopedia": [
        {"domain": "zh.wikipedia.org", "name": "维基百科", "script": "mixed", "wiki": "zh.wikipedia.org", "category": "典范条目"},
    ],
}


# English practice mode (for testers who don't read Chinese)
CATEGORIES_EN = {
    "news": "📰 News",
    "science": "🔬 Science",
    "food": "🍜 Food & recipes",
    "encyclopedia": "📚 Encyclopedia",
}

SOURCES_EN = {
    "news": [
        {"domain": "bbc.com", "name": "BBC News", "script": "english", "rss": "https://feeds.bbci.co.uk/news/rss.xml"},
        {"domain": "npr.org", "name": "NPR", "script": "english", "rss": "https://feeds.npr.org/1001/rss.xml"},
    ],
    "science": [
        {"domain": "smithsonianmag.com", "name": "Smithsonian", "script": "english", "rss": "https://www.smithsonianmag.com/rss/latest_articles/"},
        {"domain": "nasa.gov", "name": "NASA", "script": "english", "rss": "https://www.nasa.gov/feed/"},
        {"domain": "snexplores.org", "name": "Science News Explores", "script": "english", "rss": "https://www.snexplores.org/feed"},
    ],
    "food": [
        {"domain": "bbcgoodfood.com", "name": "BBC Good Food", "script": "english", "rss": "https://www.bbcgoodfood.com/feed"},
    ],
    "encyclopedia": [
        {"domain": "simple.wikipedia.org", "name": "Simple English Wikipedia", "script": "english", "wiki": "simple.wikipedia.org", "category": "Very good articles"},
        {"domain": "en.wikipedia.org", "name": "Wikipedia", "script": "english", "wiki": "en.wikipedia.org", "category": "Featured articles"},
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

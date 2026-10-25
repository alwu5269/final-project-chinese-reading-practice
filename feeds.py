"""Newest article links from the curated sites (sources.py), read straight from each site: no AI, no web search.

Feeds and list pages are cached for 15 minutes, so clicking around the app doesn't re-download them.
"""

import html
import json
import random
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin

import fetcher
import sources

CACHE_SECONDS = 15 * 60
_cache: dict[str, tuple[float, list[dict]]] = {}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _from_rss(xml: str) -> list[dict]:
    """Title and link of each <item> (RSS) or <entry> (Atom)."""
    out = []
    for el in ET.fromstring(xml.encode("utf-8")).iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        title = link = ""
        for c in el:
            if _local(c.tag) == "title":
                title = (c.text or "").strip()
            elif _local(c.tag) == "link" and not link:
                link = (c.text or c.get("href") or "").strip()
        if link:
            out.append({"title": html.unescape(title), "url": link})
    return out


def _from_page(page: str, base: str, pattern: str) -> list[dict]:
    """Article links on a list page: <a href> values matching the site's pattern, with the link text as title."""
    out = []
    for href, inner in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        if re.search(pattern, href):
            title = html.unescape(re.sub(r"<[^>]+>|\s+", " ", inner)).strip()
            out.append({"title": title, "url": urljoin(base, href)})
    return out


def _from_wiki(host: str, category: str) -> list[dict]:
    """A random handful of the encyclopedia's best articles (its featured-article category)."""
    api = (f"https://{host}/w/api.php?action=query&format=json&list=categorymembers&cmnamespace=0&cmlimit=500"
           f"&cmtitle={quote('Category:' + category)}")
    titles = [m["title"] for m in json.loads(fetcher.fetch_text(api, timeout=6)).get("query", {}).get("categorymembers", [])]
    return [{"title": t, "url": f"https://{host}/wiki/{quote(t.replace(' ', '_'))}"} for t in random.sample(titles, min(30, len(titles)))]


def _clean(link: str, source: dict) -> str:
    link = link.replace("://www.bbc.co.uk/", "://www.bbc.com/").split("?at_medium=")[0].split("?utm_")[0].split("&utm_")[0]
    if source["domain"] == "bbc.com" and source["script"] == "simplified":
        link = re.sub(r"/trad$", "/simp", link)
    return link


def site_links(source: dict) -> list[dict]:
    key = source["domain"] + source.get("rss", source.get("page", source.get("wiki", "")))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        if "rss" in source:
            found = _from_rss(fetcher.fetch_text(source["rss"], timeout=6))
        elif "page" in source:
            found = _from_page(fetcher.fetch_text(source["page"], timeout=6), source["page"], source["links"])
        else:
            found = _from_wiki(source["wiki"], source["category"])
    except (fetcher.FetchError, ET.ParseError, ValueError):
        found = []
    seen, links = set(), []
    for item in found:
        url = _clean(item["url"], source)
        if url not in seen and sources.source_of(url, "en" if source["script"] == "english" else "zh"):
            seen.add(url)
            links.append({**item, "url": url, "source": source["name"]})
    _cache[key] = (time.time(), links)
    return links


def candidates(kind: str, lang: str, exclude: list[str], per_site: int = 6) -> list[dict]:
    """Newest links from every site in the category, interleaved so no single site crowds out the rest."""
    group = sources.for_lang(lang).get(kind, [])
    with ThreadPoolExecutor(8) as pool:
        lists = list(pool.map(site_links, group))
    lists = [[a for a in links if a["url"] not in exclude][:per_site] for links in lists]
    return [a for row in zip(*[l + [None] * (per_site - len(l)) for l in lists]) for a in row if a]


def warm() -> None:
    """Read every site's links once (called in the background at startup)."""
    group = [s for lang in ("zh", "en") for g in sources.for_lang(lang).values() for s in g]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(site_links, group))

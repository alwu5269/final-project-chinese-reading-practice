"""Article import: fetch a web page safely and split its Chinese text into readable passages."""

import ipaddress
import re
import socket
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import trafilatura

from scoring import WORD, han_only

MAX_BYTES = 3_000_000
PASSAGE_CHARS = 160   # target size of one read-aloud chunk
MAX_PASSAGES = 40


class FetchError(Exception):
    pass


def check_url(url: str) -> str:
    """Only public http(s) pages: blocks localhost and private networks (SSRF)."""
    parts = urlparse(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("Enter a full web address starting with http:// or https://")
    try:
        infos = socket.getaddrinfo(parts.hostname, None)
    except socket.gaierror:
        raise FetchError("Could not find that website.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise FetchError("That address points to a private or local network, so it is blocked.")
    return url.strip()


def fetch_article(url: str, timeout: float = 10, lang: str = "zh") -> dict:
    url = check_url(url)
    safe_url = quote(url, safe=":/?#[]@!$&'()*+,;=%~")  # percent-encode Chinese characters in the path
    req = Request(safe_url, headers={"User-Agent": "Mozilla/5.0 (ReadAloud study app)"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            check_url(resp.geturl())  # re-check after redirects
            html = resp.read(MAX_BYTES + 1)
    except FetchError:
        raise
    except Exception:
        raise FetchError("Could not download that page.")
    if len(html) > MAX_BYTES:
        raise FetchError("That page is too large.")
    return article_from_html(html.decode("utf-8", errors="replace"), url, lang)


def article_from_html(html: str, url: str, lang: str = "zh") -> dict:
    """Main article text of a page as read-aloud passages (also used by the desktop browser)."""
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    meta = trafilatura.extract_metadata(html)
    passages = split_passages(text) if lang == "zh" else split_passages_en(text)
    if not passages:
        raise FetchError("No Chinese article text found on that page." if lang == "zh" else "No English article text found on that page.")
    return {"title": (meta.title if meta and meta.title else url), "url": url, "passages": passages}


def split_passages(text: str) -> list[str]:
    """Keep paragraphs that are mostly Chinese, then pack whole sentences into ~160-character passages."""
    sentences = []
    for para in text.splitlines():
        para = re.sub(r"\[(\d+|注 ?\d+|來源請求|来源请求)\]", "", para).strip()  # drop citation marks
        if len(han_only(para)) < max(4, len(para) * 0.4):
            continue  # skip menus, English, bylines
        sentences += [s for s in re.findall(r"[^。！？!?]+[。！？!?”」]*", para) if s.strip()]
    passages, current = [], ""
    for s in sentences:
        if current and len(current) + len(s) > PASSAGE_CHARS:
            passages.append(current)
            current = ""
        current += s.strip()
    if current:
        passages.append(current)
    return [p[:600] for p in passages[:MAX_PASSAGES]]


def split_passages_en(text: str) -> list[str]:
    """English: keep real paragraphs (8+ words), pack whole sentences into ~60-word passages."""
    sentences = []
    for para in text.splitlines():
        para = re.sub(r"\[\d+\]", "", para).strip()
        if len(WORD.findall(para)) < 8 or han_only(para):
            continue
        sentences += [s for s in re.split(r"(?<=[.!?])\s+|(?<=[.!?][\"”’)])\s+", para) if s.strip()]
    passages, current = [], ""
    for s in sentences:
        if current and len((current + " " + s).split()) > 60:
            passages.append(current)
            current = ""
        current = (current + " " + s).strip()
    if current:
        passages.append(current)
    return [p[:600] for p in passages[:MAX_PASSAGES]]

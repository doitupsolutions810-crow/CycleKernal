"""
Web Scraping module for Research agent.
"""

from __future__ import annotations
import httpx
import logging
import re
from typing import Dict, List
from urllib.parse import urlparse

logger = logging.getLogger("ck.scraper")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

USER_AGENT = "CycleKernelResearchBot/4.1 (+https://github.com/doitupsolutions810-crow/CycleKernal)"


async def fetch_url(url: str, timeout: float = 12.0) -> Dict:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"url": url, "ok": False, "error": "only http/https allowed"}
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            content_type = r.headers.get("content-type", "")
            text = r.text
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)}
    title, clean, links = _extract(text, content_type)
    return {
        "url": url, "ok": True, "status_code": r.status_code,
        "title": title, "text": clean[:12000], "text_length": len(clean),
        "links": links[:20], "content_type": content_type,
    }


def _extract(html: str, content_type: str):
    if not HAS_BS4 or "html" not in content_type.lower():
        text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return "", text, []
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title else ""
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(separator=" ", strip=True) if main else ""
    text = re.sub(r"\s+", " ", text).strip()
    links = []
    for a in soup.find_all("a", href=True)[:40]:
        href = a["href"]
        if href.startswith("http"):
            links.append({"text": a.get_text(strip=True)[:80], "href": href})
    return title, text, links


async def scrape_and_analyze(urls: List[str], query: str = "") -> Dict:
    results = []
    for url in urls[:5]:
        results.append(await fetch_url(url))
    ok_results = [r for r in results if r.get("ok")]
    combined = " ".join(r.get("text", "")[:3000] for r in ok_results)
    terms = [t.lower() for t in re.findall(r"[a-zA-Z]{3,}", query)]
    scores = {}
    lower = combined.lower()
    for t in terms:
        scores[t] = lower.count(t)
    return {
        "query": query,
        "pages_fetched": len(ok_results),
        "pages_failed": len(results) - len(ok_results),
        "results": results,
        "term_salience": dict(sorted(scores.items(), key=lambda x: -x[1])[:15]),
        "summary_excerpt": combined[:2000],
    }

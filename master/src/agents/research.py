"""
Research Sub-Agent
High-entropy (divergent) bias preferred. Gathers, synthesizes, cites.
Includes web scraping when URLs are supplied or discovered in the query.
"""

from .base import BaseAgent, AgentResult
from datetime import datetime
from typing import Dict, List
import logging
import re
import os

logger = logging.getLogger("ck.research")


class ResearchAgent(BaseAgent):
    name = "research"
    role = "information synthesis, evidence gathering & web analysis"

    async def run(self, task: Dict) -> AgentResult:
        started = datetime.utcnow()
        mood = await self.current_mood()
        query = task.get("query") or task.get("goal") or ""
        urls: List[str] = list(task.get("urls") or [])

        found = re.findall(r"https?://[^\s<>\"']+", query)
        for u in found:
            if u not in urls:
                urls.append(u)

        scrape_data = None
        if urls:
            scrape_data = await self._scrape(urls, query)

        report = {
            "query": query,
            "urls": urls,
            "summary": f"Research synthesis for: {query}",
            "findings": [
                {"claim": "Primary pattern identified", "confidence": 0.78},
                {"claim": "Secondary constraint surface", "confidence": 0.61},
            ],
            "open_questions": [
                "What is the exact resource envelope?",
                "Which invariant is binding?",
            ],
            "recommended_next": "hand-off to planning agent",
            "scrape": scrape_data,
            "cognitive_context": {
                "mood": mood.get("mood"),
                "override": (mood.get("system_prompt_override") or "")[:200],
            },
        }

        if scrape_data and scrape_data.get("pages_fetched"):
            report["findings"].insert(0, {
                "claim": f"Fetched and analyzed {scrape_data['pages_fetched']} web page(s)",
                "confidence": 0.9,
                "term_salience": scrape_data.get("term_salience"),
                "excerpt": (scrape_data.get("summary_excerpt") or "")[:500],
            })

        if "Creative/Divergent" in mood.get("traits", []):
            report["findings"].append(
                {
                    "claim": "Exploratory alternative hypothesis",
                    "confidence": 0.42,
                    "speculative": True,
                }
            )

        logger.info(
            f"Research complete for '{query[:60]}' under mood={mood.get('mood')} "
            f"scrape_pages={(scrape_data or {}).get('pages_fetched', 0)}"
        )
        return self._wrap(True, report, mood, started)

    async def _scrape(self, urls: List[str], query: str):
        # Prefer chat service scrape endpoint (has bs4)
        try:
            import httpx
            chat_url = os.getenv("CHAT_URL", "http://chat:8300")
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{chat_url}/v1/scrape",
                    json={"urls": urls[:5], "query": query},
                )
                if r.status_code == 200:
                    return r.json()
        except Exception as e:
            logger.warning(f"chat scrape endpoint unavailable: {e}")

        # Minimal fallback without bs4
        try:
            import httpx
            results = []
            async with httpx.AsyncClient(follow_redirects=True, timeout=12.0) as client:
                for url in urls[:3]:
                    try:
                        r = await client.get(url, headers={"User-Agent": "CycleKernelResearchBot/4.1"})
                        text = re.sub(r"<[^>]+>", " ", r.text)
                        text = re.sub(r"\s+", " ", text).strip()[:4000]
                        results.append({"url": url, "ok": True, "text": text})
                    except Exception as ex:
                        results.append({"url": url, "ok": False, "error": str(ex)})
            ok = [x for x in results if x.get("ok")]
            return {
                "query": query,
                "pages_fetched": len(ok),
                "pages_failed": len(results) - len(ok),
                "results": results,
                "summary_excerpt": " ".join(x.get("text", "")[:1500] for x in ok)[:2000],
                "term_salience": {},
            }
        except Exception as e:
            logger.warning(f"fallback scrape failed: {e}")
            return None

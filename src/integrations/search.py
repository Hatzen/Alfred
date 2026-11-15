"""Wikipedia and web knowledge search connector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import quote

import httpx


@dataclass
class SearchHit:
    """Normalized summary hit from Wikipedia or web search."""

    title: str
    summary: str
    url: str
    source: str


class KnowledgeSearchConnector:
    """Searches Wikipedia REST API (de/en) and DuckDuckGo Instant Answers."""

    def __init__(
        self,
        timeout_seconds: float = 3.5,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    def search_wikipedia(self, query: str, language: str = "de") -> Optional[SearchHit]:
        """Fetch concise Wikipedia summary for query in the target language."""
        lang = "de" if language.lower().startswith("de") else "en"
        topic = quote(query.strip().replace(" ", "_"))
        if not topic:
            return None

        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{topic}"
        client = self._http_client or httpx.Client(timeout=self.timeout_seconds)
        should_close = self._http_client is None
        try:
            resp = client.get(url, headers={"User-Agent": "AlfredAssistant/1.0"})
            if resp.status_code != 200:
                return None
            data = resp.json()
            extract = str(data.get("extract", "")).strip()
            if not extract:
                return None
            page_url = (
                data.get("content_urls", {}).get("desktop", {}).get("page")
                or f"https://{lang}.wikipedia.org/wiki/{topic}"
            )
            return SearchHit(
                title=str(data.get("title", query)),
                summary=extract,
                url=str(page_url),
                source=f"wikipedia-{lang}",
            )
        except Exception:
            return None
        finally:
            if should_close:
                client.close()

    def search_web(self, query: str) -> List[SearchHit]:
        """Query DuckDuckGo Instant Answer JSON API for factual web results."""
        cleaned = query.strip()
        if not cleaned:
            return []

        client = self._http_client or httpx.Client(timeout=self.timeout_seconds)
        should_close = self._http_client is None
        try:
            resp = client.get(
                "https://api.duckduckgo.com/",
                params={"q": cleaned, "format": "json", "no_html": 1, "skip_disambig": 1},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            hits: List[SearchHit] = []
            abstract = str(data.get("AbstractText", "")).strip()
            if abstract:
                hits.append(
                    SearchHit(
                        title=str(data.get("Heading", cleaned)),
                        summary=abstract,
                        url=str(data.get("AbstractURL", "")),
                        source="duckduckgo",
                    )
                )
            for topic in data.get("RelatedTopics", [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    hits.append(
                        SearchHit(
                            title=cleaned,
                            summary=str(topic["Text"]),
                            url=str(topic.get("FirstURL", "")),
                            source="duckduckgo",
                        )
                    )
            return hits
        except Exception:
            return []
        finally:
            if should_close:
                client.close()

    def search(self, query: str, language: str = "de") -> Optional[SearchHit]:
        """Try Wikipedia first for clean encyclopedic summaries, then fall back to web search."""
        wiki = self.search_wikipedia(query, language=language)
        if wiki is not None:
            return wiki
        web_hits = self.search_web(query)
        return web_hits[0] if web_hits else None


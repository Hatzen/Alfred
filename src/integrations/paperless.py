"""Paperless-ngx document management REST connector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import httpx

_SENSITIVE_DOC_TERMS = ("steuer", "tax", "gehalt", "salary", "lohn", "iban", "bank", "vertrag")


@dataclass
class DocumentHit:
    """Represents a document found in Paperless-ngx."""

    doc_id: int
    title: str
    correspondent: str
    created: str
    snippet: str
    is_sensitive: bool = False


class PaperlessConnector:
    """Queries a local Paperless-ngx instance for archived documents."""

    def __init__(
        self,
        base_url: str = "http://localhost:8010",
        api_token: str = "",
        timeout_seconds: float = 3.0,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    def search_documents(self, query: str, limit: int = 5) -> List[DocumentHit]:
        """Search Paperless-ngx documents matching query."""
        headers = {"Authorization": f"Token {self.api_token}"} if self.api_token else {}
        client = self._http_client or httpx.Client(timeout=self.timeout_seconds)
        should_close = self._http_client is None
        try:
            resp = client.get(
                f"{self.base_url}/api/documents/",
                params={"query": query, "page_size": limit},
                headers=headers,
            )
            resp.raise_for_status()
            payload = resp.json()
            hits: List[DocumentHit] = []
            for item in payload.get("results", [])[:limit]:
                title = str(item.get("title", "Untitled"))
                content = str(item.get("content", ""))
                combined = f"{title} {content}".lower()
                is_sens = any(term in combined for term in _SENSITIVE_DOC_TERMS)
                hits.append(
                    DocumentHit(
                        doc_id=int(item.get("id", 0)),
                        title=title,
                        correspondent=str(item.get("correspondent_name") or item.get("correspondent") or "Unknown"),
                        created=str(item.get("created", "")),
                        snippet=content[:180].strip(),
                        is_sensitive=is_sens,
                    )
                )
            return hits
        except Exception:
            return []
        finally:
            if should_close:
                client.close()


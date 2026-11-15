"""Runtime REST API learner and dynamic Alexa-like skill executor."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from src.memory.store import MemoryStore, SkillDefinition

_LEARN_PATTERN = re.compile(
    r"(?:lerne\s+(?:api|skill)|learn\s+(?:api|skill))\s+"
    r"(?P<name>[a-zA-Z0-9_-]+)\s+"
    r"(?:(?:unter|at|via)\s+)?"
    r"(?:(?P<method>GET|POST|PUT|DELETE)\s+)?"
    r"(?P<url>https?://\S+)"
    r"(?:\s+(?:trigger|bei|wenn|on)\s+(?P<trigger>.+))?",
    re.IGNORECASE,
)


@dataclass
class SkillExecutionResult:
    """Result of executing a learned REST skill."""

    skill_name: str
    ok: bool
    status_code: int
    response_text: str
    data: Any = None


class RESTSkillLearner:
    """Teaches Alfred how to call external REST APIs and persists them as skills (INV-04)."""

    def __init__(
        self,
        memory_store: MemoryStore,
        timeout_seconds: float = 4.0,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.memory_store = memory_store
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    def parse_and_learn_from_text(self, text: str) -> Optional[SkillDefinition]:
        """Parse a natural-language API teaching instruction and save the skill."""
        match = _LEARN_PATTERN.search(text.strip())
        if not match:
            return None

        name = match.group("name").lower()
        method = (match.group("method") or "GET").upper()
        url = match.group("url").rstrip(".,;")
        raw_trigger = (match.group("trigger") or "").strip().strip("\"'")
        triggers = [raw_trigger.lower()] if raw_trigger else [name]

        skill = SkillDefinition(
            name=name,
            description=f"Learned REST skill calling {method} {url}",
            trigger_phrases=triggers,
            endpoint_url=url,
            http_method=method,
        )
        return self.memory_store.save_skill(skill)

    def learn_skill(
        self,
        *,
        name: str,
        endpoint_url: str,
        http_method: str = "GET",
        description: str = "",
        trigger_phrases: Optional[List[str]] = None,
        headers: Optional[Dict[str, str]] = None,
        payload_template: Optional[Dict[str, Any]] = None,
        requires_passphrase: bool = False,
    ) -> SkillDefinition:
        """Explicitly register and persist a new REST API skill."""
        skill = SkillDefinition(
            name=name,
            description=description or f"REST integration for {name}",
            trigger_phrases=trigger_phrases or [name],
            endpoint_url=endpoint_url,
            http_method=http_method.upper(),
            headers=headers or {},
            payload_template=payload_template or {},
            requires_passphrase=requires_passphrase,
        )
        return self.memory_store.save_skill(skill)

    def execute_skill(
        self,
        skill: SkillDefinition,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> SkillExecutionResult:
        """Invoke a learned REST skill endpoint with optional argument substitution."""
        args = arguments or {}
        url = skill.endpoint_url
        for key, value in args.items():
            url = url.replace(f"{{{key}}}", str(value))

        payload = dict(skill.payload_template)
        payload.update(args)

        client = self._http_client or httpx.Client(timeout=self.timeout_seconds)
        should_close = self._http_client is None
        try:
            kwargs: Dict[str, Any] = {"headers": skill.headers}
            if skill.http_method in {"POST", "PUT", "PATCH"}:
                kwargs["json"] = payload
            elif args:
                kwargs["params"] = args

            resp = client.request(skill.http_method, url, **kwargs)
            parsed_data: Any = None
            try:
                parsed_data = resp.json()
                summary = json.dumps(parsed_data, ensure_ascii=False)
            except Exception:
                summary = resp.text.strip()

            return SkillExecutionResult(
                skill_name=skill.name,
                ok=200 <= resp.status_code < 300,
                status_code=resp.status_code,
                response_text=summary or f"HTTP {resp.status_code}",
                data=parsed_data,
            )
        except Exception as exc:
            return SkillExecutionResult(
                skill_name=skill.name,
                ok=False,
                status_code=0,
                response_text=f"REST request error: {exc}",
            )
        finally:
            if should_close:
                client.close()


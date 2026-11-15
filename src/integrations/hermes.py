"""Dual Hermes bridge: Rhasspy/Snips Hermes MQTT voice protocol & Nous Hermes <tool_call>."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


@dataclass
class HermesToolCall:
    """Parsed Nous Hermes XML/JSON tool invocation."""

    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HermesIntentMessage:
    """Normalized incoming message from the Hermes voice MQTT protocol."""

    topic: str
    text: str
    site_id: str = "default"
    session_id: Optional[str] = None
    wakeword_id: Optional[str] = None
    intent_name: Optional[str] = None
    slots: Dict[str, Any] = field(default_factory=dict)


class HermesBridge:
    """Integrates Alfred with local Hermes voice pipelines and Nous Hermes LLM tool-calling."""

    def __init__(
        self,
        enabled: bool = True,
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
    ) -> None:
        self.enabled = enabled
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.outgoing_messages: List[Dict[str, Any]] = []

    def parse_protocol_message(self, topic: str, payload: Dict[str, Any]) -> HermesIntentMessage:
        """Parse Hermes MQTT payloads (asr/textCaptured, hotword/detected, nlu/intentParsed)."""
        site_id = str(payload.get("siteId", "default"))
        session_id = payload.get("sessionId")
        wakeword_id = None
        if "hotword" in topic:
            parts = topic.split("/")
            wakeword_id = parts[2] if len(parts) > 2 else payload.get("modelId")

        intent_name = None
        slots: Dict[str, Any] = {}
        if isinstance(payload.get("intent"), dict):
            intent_name = payload["intent"].get("intentName")
        for slot in payload.get("slots", []) or []:
            if isinstance(slot, dict) and slot.get("slotName"):
                val = slot.get("value", {})
                slots[slot["slotName"]] = val.get("value") if isinstance(val, dict) else val

        text = str(payload.get("text") or payload.get("input") or "").strip()
        if not text and wakeword_id:
            text = wakeword_id

        return HermesIntentMessage(
            topic=topic,
            text=text,
            site_id=site_id,
            session_id=session_id,
            wakeword_id=wakeword_id,
            intent_name=intent_name,
            slots=slots,
        )

    def build_tts_say_payload(
        self,
        text: str,
        site_id: str = "default",
        lang: str = "de-DE",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create and record a standard hermes/tts/say payload for local Hermes playback."""
        message = {
            "topic": "hermes/tts/say",
            "payload": {
                "text": text,
                "siteId": site_id,
                "lang": lang,
                "sessionId": session_id or "",
            },
        }
        self.outgoing_messages.append(message)
        return message

    @staticmethod
    def parse_tool_calls(llm_output: str) -> List[HermesToolCall]:
        """Extract <tool_call>{...}</tool_call> blocks emitted by Nous Hermes models."""
        calls: List[HermesToolCall] = []
        for raw_json in _TOOL_CALL_RE.findall(llm_output or ""):
            try:
                parsed = json.loads(raw_json)
            except json.JSONDecodeError:
                continue
            name = str(parsed.get("name", "")).strip()
            args = parsed.get("arguments", {})
            if name and isinstance(args, dict):
                calls.append(HermesToolCall(name=name, arguments=args))
        return calls

    @staticmethod
    def format_tool_schema(skills: List[Any]) -> List[Dict[str, Any]]:
        """Export Alfred skills as OpenAI/Nous Hermes compatible function definitions."""
        tools: List[Dict[str, Any]] = []
        for skill in skills:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": skill.name,
                        "description": skill.description,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Optional query or argument"}
                            },
                        },
                    },
                }
            )
        return tools


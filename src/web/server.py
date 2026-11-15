"""FastAPI daemon server, REST API, WebSocket event stream, and dashboard UI."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.brain.assistant import AlfredAssistant, AssistantResponse
from src.config import AlfredConfig


class CommandRequest(BaseModel):
    """Payload for sending text or transcribed voice commands to Alfred."""

    text: str
    require_wake_word: bool = True
    passphrase: Optional[str] = None
    language: Optional[str] = None


class InterruptRequest(BaseModel):
    """Payload for triggering immediate answer/speech cancellation."""

    reason: str = "api_interrupt"


class MemoryCreateRequest(BaseModel):
    """Payload for creating or updating a persistent memory."""

    key: str
    value: str
    category: str = "general"
    sensitive: Optional[bool] = None


class PersonalityUpdateRequest(BaseModel):
    """Payload for adapting Alfred's persisted personality traits."""

    name: Optional[str] = None
    role: Optional[str] = None
    tone: Optional[str] = None
    humor_level: Optional[int] = Field(default=None, ge=0, le=10)
    formality: Optional[str] = None
    language: Optional[str] = None
    add_rule: Optional[str] = None


class SkillLearnRequest(BaseModel):
    """Payload for teaching Alfred a new Alexa-like REST API skill."""

    name: str
    endpoint_url: str
    http_method: str = "GET"
    description: str = ""
    trigger_phrases: Optional[List[str]] = None
    headers: Optional[Dict[str, str]] = None
    payload_template: Optional[Dict[str, Any]] = None
    requires_passphrase: bool = False


class DeviceSelectRequest(BaseModel):
    """Payload for manually pinning input or output audio devices."""

    input_device_id: Optional[str] = None
    output_device_id: Optional[str] = None


class HermesWebhookRequest(BaseModel):
    """Incoming Hermes MQTT-over-HTTP message payload."""

    topic: str = "hermes/asr/textCaptured"
    payload: Dict[str, Any] = Field(default_factory=dict)
    require_wake_word: bool = False


class ConnectionHub:
    """Tracks active WebSocket dashboard subscribers cleanly."""

    def __init__(self) -> None:
        self._connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, event: Dict[str, Any]) -> None:
        stale: List[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(event)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


def _serialize_response(resp: AssistantResponse) -> Dict[str, Any]:
    return {
        "accepted": resp.accepted,
        "reply": resp.reply,
        "language": resp.language,
        "interrupted": resp.interrupted,
        "requires_passphrase": resp.requires_passphrase,
        "blocked_by_security": resp.blocked_by_security,
        "matched_wake_word": resp.matched_wake_word,
        "route": resp.route,
        "provider": resp.provider,
        "tts_chunks": resp.tts_chunks,
        "beeps_played": resp.beeps_played,
        "metadata": resp.metadata,
    }


def create_app(assistant: Optional[AlfredAssistant] = None) -> FastAPI:
    """Create and configure the Alfred FastAPI application."""
    bot = assistant or AlfredAssistant(AlfredConfig())
    hub = ConnectionHub()

    app = FastAPI(
        title="Alfred Privacy-First AI Assistant",
        version="1.0.0",
        description="Local daemon for smart audio, low-CPU wake filtering, instant barge-in, weekday security, persistent memory/skills, and LocalAI/Hermes integration.",
    )
    app.state.assistant = bot
    app.state.hub = hub

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        index_path = static_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="Dashboard UI not installed")
        return FileResponse(str(index_path))

    @app.get("/api/status")
    async def get_status() -> Dict[str, Any]:
        personality = bot.memory_store.get_personality()
        return {
            "assistant_name": personality.name,
            "state": bot.interrupt_controller.state.value,
            "language": personality.language,
            "wake_words": bot.command_filter.wake_words,
            "interrupt_phrases": bot.command_filter.interrupt_phrases,
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
            "idle_poll_interval_ms": bot.config.idle_poll_interval_ms,
            "hermes_enabled": bot.config.hermes_enabled,
            "devices": bot.device_manager.snapshot(),
            "counts": {
                "memories": len(bot.memory_store.list_memories(include_sensitive_values=False)),
                "skills": len(bot.memory_store.list_skills()),
                "interrupts": len(bot.interrupt_controller.interrupt_history),
                "beeps": len(bot.sound_engine.history),
            },
        }

    @app.post("/api/command")
    async def post_command(req: CommandRequest) -> Dict[str, Any]:
        res = bot.process_input(
            req.text,
            require_wake_word=req.require_wake_word,
            explicit_passphrase=req.passphrase,
            language_override=req.language,
        )
        payload = _serialize_response(res)
        await hub.broadcast({"type": "command_result", "data": payload})
        return payload

    @app.post("/api/interrupt")
    async def post_interrupt(req: InterruptRequest = InterruptRequest()) -> Dict[str, Any]:
        event = bot.interrupt_controller.trigger_interrupt(reason=req.reason)
        payload = {
            "interrupted": True,
            "reason": event.reason,
            "previous_state": event.previous_state.value,
            "dropped_chunks": event.dropped_chunks,
            "state": bot.interrupt_controller.state.value,
            "beeps_played": ["cancel"],
        }
        await hub.broadcast({"type": "interrupt", "data": payload})
        return payload

    @app.get("/api/devices")
    async def get_devices() -> Dict[str, Any]:
        return bot.device_manager.snapshot()

    @app.post("/api/devices/smart-select")
    async def smart_select_devices() -> Dict[str, Any]:
        mic = bot.device_manager.select_smart_microphone()
        soundcheck = bot.device_manager.select_smart_output_device()
        return {
            "selected_input": mic.device_id if mic else None,
            "selected_input_name": mic.name if mic else None,
            "soundcheck": {
                "passed": soundcheck.passed,
                "selected_output": soundcheck.selected_device_id,
                "selected_output_name": soundcheck.selected_device_name,
                "score": soundcheck.score,
                "tested_devices": soundcheck.tested_devices,
            },
            "snapshot": bot.device_manager.snapshot(),
        }

    @app.post("/api/devices/soundcheck")
    async def run_soundcheck() -> Dict[str, Any]:
        res = bot.device_manager.run_soundcheck()
        return {
            "passed": res.passed,
            "selected_device_id": res.selected_device_id,
            "selected_device_name": res.selected_device_name,
            "score": res.score,
            "tested_devices": res.tested_devices,
            "cue_played": res.cue_played,
        }

    @app.post("/api/devices/select")
    async def manual_select_devices(req: DeviceSelectRequest) -> Dict[str, Any]:
        try:
            if req.input_device_id:
                bot.device_manager.set_input_device(req.input_device_id)
            if req.output_device_id:
                bot.device_manager.set_output_device(req.output_device_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return bot.device_manager.snapshot()

    @app.get("/api/memories")
    async def list_memories(passphrase: Optional[str] = Query(default=None)) -> Dict[str, Any]:
        unlocked = bool(passphrase and bot.passphrase_validator.verify(passphrase))
        entries = bot.memory_store.list_memories(include_sensitive_values=unlocked)
        return {
            "unlocked": unlocked,
            "memories": [
                {
                    "key": m.key,
                    "value": m.value,
                    "category": m.category,
                    "sensitive": m.sensitive,
                    "updated_at": m.updated_at,
                }
                for m in entries
            ],
        }

    @app.post("/api/memories")
    async def save_memory(req: MemoryCreateRequest) -> Dict[str, Any]:
        entry = bot.memory_store.save_memory(
            key=req.key,
            value=req.value,
            category=req.category,
            sensitive=req.sensitive,
        )
        return {
            "key": entry.key,
            "value": "[LOCKED - PASSPHRASE REQUIRED]" if entry.sensitive else entry.value,
            "category": entry.category,
            "sensitive": entry.sensitive,
            "updated_at": entry.updated_at,
        }

    @app.delete("/api/memories/{key}")
    async def delete_memory(key: str) -> Dict[str, Any]:
        deleted = bot.memory_store.delete_memory(key)
        if not deleted:
            raise HTTPException(status_code=404, detail="Memory not found")
        return {"deleted": True, "key": key}

    @app.get("/api/personality")
    async def get_personality() -> Dict[str, Any]:
        p = bot.memory_store.get_personality()
        return {
            "name": p.name,
            "role": p.role,
            "tone": p.tone,
            "humor_level": p.humor_level,
            "formality": p.formality,
            "language": p.language,
            "custom_rules": p.custom_rules,
            "updated_at": p.updated_at,
        }

    @app.post("/api/personality")
    async def update_personality(req: PersonalityUpdateRequest) -> Dict[str, Any]:
        p = bot.memory_store.update_personality(
            name=req.name,
            role=req.role,
            tone=req.tone,
            humor_level=req.humor_level,
            formality=req.formality,
            language=req.language,
            add_rule=req.add_rule,
        )
        return {
            "name": p.name,
            "role": p.role,
            "tone": p.tone,
            "humor_level": p.humor_level,
            "formality": p.formality,
            "language": p.language,
            "custom_rules": p.custom_rules,
            "updated_at": p.updated_at,
        }

    @app.get("/api/skills")
    async def list_skills() -> Dict[str, Any]:
        skills = bot.memory_store.list_skills()
        return {
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "trigger_phrases": s.trigger_phrases,
                    "endpoint_url": s.endpoint_url,
                    "http_method": s.http_method,
                    "requires_passphrase": s.requires_passphrase,
                }
                for s in skills
            ]
        }

    @app.post("/api/skills/learn")
    async def learn_skill(req: SkillLearnRequest) -> Dict[str, Any]:
        skill = bot.rest_learner.learn_skill(
            name=req.name,
            endpoint_url=req.endpoint_url,
            http_method=req.http_method,
            description=req.description,
            trigger_phrases=req.trigger_phrases,
            headers=req.headers,
            payload_template=req.payload_template,
            requires_passphrase=req.requires_passphrase,
        )
        return {
            "learned": True,
            "skill": {
                "name": skill.name,
                "description": skill.description,
                "trigger_phrases": skill.trigger_phrases,
                "endpoint_url": skill.endpoint_url,
                "http_method": skill.http_method,
                "requires_passphrase": skill.requires_passphrase,
            },
        }

    @app.post("/api/hermes/webhook")
    async def hermes_webhook(req: HermesWebhookRequest) -> Dict[str, Any]:
        parsed = bot.hermes_bridge.parse_protocol_message(req.topic, req.payload)
        res = bot.process_input(parsed.text, require_wake_word=req.require_wake_word)
        tts_msg = bot.hermes_bridge.build_tts_say_payload(
            res.reply,
            site_id=parsed.site_id,
            lang="de-DE" if res.language == "de" else "en-US",
            session_id=parsed.session_id,
        )
        return {
            "topic": parsed.topic,
            "site_id": parsed.site_id,
            "assistant_response": _serialize_response(res),
            "hermes_tts": tts_msg,
        }

    @app.get("/api/security/passphrase-hint")
    async def get_passphrase_hint() -> Dict[str, Any]:
        return {
            "base_word": bot.passphrase_validator.base_word,
            "iso_weekday": bot.passphrase_validator.current_weekday(),
            "rule": "Combine base_word with today's ISO weekday number (1=Monday .. 7=Sunday, digit or DE/EN word).",
        }

    @app.websocket("/api/stream")
    async def stream_telemetry(ws: WebSocket) -> None:
        await hub.connect(ws)
        try:
            while True:
                await ws.send_json(
                    {
                        "type": "heartbeat",
                        "state": bot.interrupt_controller.state.value,
                        "cpu_percent": psutil.cpu_percent(interval=None),
                        "active_input": bot.device_manager.active_input_id,
                        "active_output": bot.device_manager.active_output_id,
                        "beeps_total": len(bot.sound_engine.history),
                    }
                )
                await asyncio.sleep(1.5)
        except WebSocketDisconnect:
            hub.disconnect(ws)
        except Exception:
            hub.disconnect(ws)

    return app


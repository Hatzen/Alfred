"""FastAPI endpoint integration tests for the Alfred daemon."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from src.brain.assistant import AlfredAssistant
from src.config import AlfredConfig
from src.security.passphrase import DynamicPassphraseValidator, SensitiveTopicGuard
from src.web.server import create_app


def _make_test_client() -> TestClient:
    monday = datetime(2026, 11, 16, 10, 0)
    validator = DynamicPassphraseValidator(base_word="Nilpferd", now_fn=lambda: monday)
    guard = SensitiveTopicGuard(validator=validator)
    config = AlfredConfig(
        db_path=":memory:",
        default_language="de",
        passphrase_base="Nilpferd",
        simulation_mode=True,
    )
    bot = AlfredAssistant(
        config=config,
        passphrase_validator=validator,
        security_guard=guard,
    )
    app = create_app(assistant=bot)
    return TestClient(app)


def test_web_api_status_command_interrupt_devices_memories_skills_and_hermes() -> None:
    client = _make_test_client()

    # 1. Dashboard index & status
    assert client.get("/").status_code == 200
    status = client.get("/api/status").json()
    assert status["assistant_name"] == "Alfred"
    assert "hey alfred" in status["wake_words"]

    # 2. Smart audio selection & soundcheck
    smart = client.post("/api/devices/smart-select").json()
    assert smart["selected_input"] == "mic-desk-usb"
    assert smart["soundcheck"]["passed"] is True
    assert smart["soundcheck"]["selected_output"] == "spk-desk-main"

    # 3. Memories API masks sensitive entries unless valid weekday passphrase supplied
    client.post("/api/memories", json={"key": "steuernummer", "value": "987/654/321"})
    client.post("/api/memories", json={"key": "stadt", "value": "Berlin"})

    locked = client.get("/api/memories").json()
    locked_map = {m["key"]: m for m in locked["memories"]}
    assert locked["unlocked"] is False
    assert locked_map["stadt"]["value"] == "Berlin"
    assert locked_map["steuernummer"]["value"] == "[LOCKED - PASSPHRASE REQUIRED]"

    unlocked = client.get("/api/memories", params={"passphrase": "NilpferdOne"}).json()
    unlocked_map = {m["key"]: m for m in unlocked["memories"]}
    assert unlocked["unlocked"] is True
    assert unlocked_map["steuernummer"]["value"] == "987/654/321"

    # 4. Personality API
    pers = client.post("/api/personality", json={"humor_level": 9, "tone": "playful"}).json()
    assert pers["humor_level"] == 9
    assert pers["tone"] == "playful"

    # 5. Teach REST skill API
    learned = client.post(
        "/api/skills/learn",
        json={
            "name": "kaffeemaschine",
            "endpoint_url": "http://coffee.local/brew",
            "http_method": "POST",
            "trigger_phrases": ["mach kaffee"],
        },
    ).json()
    assert learned["learned"] is True
    skills = client.get("/api/skills").json()["skills"]
    assert any(s["name"] == "kaffeemaschine" for s in skills)

    # 6. Command & security gate via HTTP
    blocked_cmd = client.post(
        "/api/command",
        json={"text": "Hey Alfred, was ist meine Steuernummer?", "require_wake_word": True},
    ).json()
    assert blocked_cmd["blocked_by_security"] is True

    allowed_cmd = client.post(
        "/api/command",
        json={
            "text": "Hey Alfred, was ist meine Steuernummer?",
            "require_wake_word": True,
            "passphrase": "Nilpfer1",
        },
    ).json()
    assert allowed_cmd["blocked_by_security"] is False
    assert "987/654/321" in allowed_cmd["reply"]

    # 7. Instant interrupt API
    intr = client.post("/api/interrupt", json={"reason": "test_stop"}).json()
    assert intr["interrupted"] is True
    assert intr["beeps_played"] == ["cancel"]

    # 8. Hermes webhook integration
    hermes_res = client.post(
        "/api/hermes/webhook",
        json={
            "topic": "hermes/asr/textCaptured",
            "payload": {"text": "Merke dir: Projekt = Alfred", "siteId": "buero"},
        },
    ).json()
    assert hermes_res["site_id"] == "buero"
    assert hermes_res["hermes_tts"]["topic"] == "hermes/tts/say"
    assert "alfred" in hermes_res["hermes_tts"]["payload"]["text"].lower()

    # 9. WebSocket live heartbeat stream
    with client.websocket_connect("/api/stream") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "heartbeat"
        assert msg["state"] == "idle"

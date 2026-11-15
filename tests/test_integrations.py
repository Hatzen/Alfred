"""Tests for LocalAI, FancyTanky, Paperless, Search, Hermes, and RESTSkillLearner."""

from __future__ import annotations

import httpx

from src.integrations.fancytanky import FancyTankyConnector
from src.integrations.hermes import HermesBridge
from src.integrations.paperless import PaperlessConnector
from src.integrations.rest_learner import RESTSkillLearner
from src.integrations.search import KnowledgeSearchConnector
from src.memory.store import MemoryStore
from src.providers.localai import LocalAIClient


def test_localai_client_chat_stt_tts_and_vad_with_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={"model": "hermes-local", "choices": [{"message": {"content": "Hallo Meister!"}}]},
            )
        if request.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": "Hey Alfred wie spät ist es"})
        if request.url.path.endswith("/audio/speech"):
            return httpx.Response(200, content=b"RIFFmockwav")
        if request.url.path.endswith("/vad"):
            return httpx.Response(200, json={"is_speech": True})
        return httpx.Response(404)

    mock_http = httpx.Client(transport=httpx.MockTransport(handler))
    client = LocalAIClient(localai_base_url="http://localai.test/v1", http_client=mock_http)

    chat = client.chat_completion([{"role": "user", "content": "Hallo"}], language="de")
    assert chat.provider == "localai"
    assert chat.content == "Hallo Meister!"

    stt = client.transcribe_audio(b"RIFF...", language="de")
    assert stt.provider == "localai-stt"
    assert "Alfred" in stt.text

    tts = client.synthesize_speech("Hallo")
    assert tts.provider == "localai-tts"
    assert tts.audio_bytes == b"RIFFmockwav"

    vad = client.detect_voice_activity(b"\x01\x00" * 100)
    assert vad.provider == "localai-vad"
    assert vad.is_speech is True


def test_fancytanky_paperless_and_knowledge_search_connectors() -> None:
    def tank_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/move":
            return httpx.Response(200, json={"status": "moving", "direction": "forward"})
        if request.url.path == "/api/action/yes":
            return httpx.Response(200, json={"status": "nodding"})
        return httpx.Response(200, json={"battery_pct": 92, "distance_cm": 35.0})

    tank = FancyTankyConnector(
        base_url="http://tank.test",
        http_client=httpx.Client(transport=httpx.MockTransport(tank_handler)),
    )
    reply_move = tank.execute_natural_command("Fahre vorwärts", language="de")
    assert "move:forward" in reply_move
    assert "fancytanky-live" in reply_move

    def paperless_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 42,
                        "title": "Einkommensteuerbescheid 2025",
                        "correspondent_name": "Finanzamt",
                        "created": "2026-04-12",
                        "content": "Steuernummer 123/456",
                    }
                ]
            },
        )

    paperless = PaperlessConnector(
        base_url="http://paperless.test",
        api_token="secret-tok",
        http_client=httpx.Client(transport=httpx.MockTransport(paperless_handler)),
    )
    docs = paperless.search_documents("Steuer")
    assert len(docs) == 1
    assert docs[0].title == "Einkommensteuerbescheid 2025"
    assert docs[0].is_sensitive is True

    def search_handler(request: httpx.Request) -> httpx.Response:
        if "wikipedia.org" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "title": "Python (Programmiersprache)",
                    "extract": "Python ist eine universelle Programmiersprache.",
                    "content_urls": {"desktop": {"page": "https://de.wikipedia.org/wiki/Python"}},
                },
            )
        return httpx.Response(404)

    search = KnowledgeSearchConnector(http_client=httpx.Client(transport=httpx.MockTransport(search_handler)))
    hit = search.search("Python", language="de")
    assert hit is not None
    assert hit.source == "wikipedia-de"
    assert "Programmiersprache" in hit.summary


def test_hermes_protocol_and_nous_tool_calling_plus_rest_skill_learner() -> None:
    bridge = HermesBridge()
    msg = bridge.parse_protocol_message(
        "hermes/asr/textCaptured",
        {"text": "Hey Alfred starte Licht", "siteId": "wohnzimmer", "sessionId": "abc-1"},
    )
    assert msg.site_id == "wohnzimmer"
    assert msg.session_id == "abc-1"
    assert "Licht" in msg.text

    calls = bridge.parse_tool_calls(
        '<tool_call>{"name": "wetter", "arguments": {"city": "Berlin"}}</tool_call>'
    )
    assert len(calls) == 1
    assert calls[0].name == "wetter"
    assert calls[0].arguments["city"] == "Berlin"

    def skill_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"temp_c": 18, "city": "Berlin"})

    store = MemoryStore(db_path=":memory:")
    learner = RESTSkillLearner(
        memory_store=store,
        http_client=httpx.Client(transport=httpx.MockTransport(skill_handler)),
    )
    skill = learner.parse_and_learn_from_text(
        "Lerne API wetter unter GET http://weather.local/api wenn wetter"
    )
    assert skill is not None
    assert skill.name == "wetter"
    assert skill.trigger_phrases == ["wetter"]

    exec_res = learner.execute_skill(skill, {"city": "Berlin"})
    assert exec_res.ok is True
    assert "18" in exec_res.response_text
    store.close()


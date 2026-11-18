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


def test_localai_falls_back_to_ollama_with_tag_auto_discovery() -> None:
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})
        if request.url.path.endswith("/api/chat"):
            body = json.loads(request.content.decode("utf-8"))
            if body.get("model") == "qwen3.5:4b":
                return httpx.Response(200, json={"message": {"content": "Antwort von qwen3.5:4b"}})
            return httpx.Response(404, json={"error": "model not found"})
        return httpx.Response(503)

    mock_http = httpx.Client(transport=httpx.MockTransport(handler))
    client = LocalAIClient(
        localai_base_url="http://localai.offline/v1",
        ollama_base_url="http://ollama.test",
        ollama_model="missing-model",
        http_client=mock_http,
    )
    res = client.chat_completion([{"role": "user", "content": "Hallo"}], language="de")
    assert res.provider == "ollama"
    assert res.model == "qwen3.5:4b"
    assert "qwen3.5:4b" in res.content


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


def test_dotenv_loader_and_nvidia_spark_localai_model_config(tmp_path) -> None:
    import json
    import os
    from src.config import AlfredConfig

    env_file = tmp_path / ".env.spark"
    env_file.write_text(
        'ALFRED_SIMULATION=false\n'
        'ALFRED_LOCALAI_URL="http://spark.local:8080/v1"\n'
        'ALFRED_CHAT_MODEL=hermes-3-llama-3.1-8b\n'
        'ALFRED_STT_MODEL=whisper-large-v3-turbo\n'
        'ALFRED_TTS_MODEL=piper-de-thorsten\n'
        'ALFRED_VAD_MODEL=silero-vad\n',
        encoding="utf-8",
    )
    tracked_vars = (
        "ALFRED_SIMULATION",
        "ALFRED_LOCALAI_URL",
        "ALFRED_CHAT_MODEL",
        "ALFRED_STT_MODEL",
        "ALFRED_TTS_MODEL",
        "ALFRED_VAD_MODEL",
    )
    saved_env = {var: os.environ.get(var) for var in tracked_vars}
    try:
        for var in tracked_vars:
            os.environ.pop(var, None)

        cfg = AlfredConfig.from_env(str(env_file), override=True)
        assert cfg.simulation_mode is False
        assert cfg.localai_base_url == "http://spark.local:8080/v1"
        assert cfg.localai_chat_model == "hermes-3-llama-3.1-8b"
        assert cfg.localai_stt_model == "whisper-large-v3-turbo"
        assert cfg.localai_tts_model == "piper-de-thorsten"
        assert cfg.localai_vad_model == "silero-vad"
    finally:
        for var, old_val in saved_env.items():
            if old_val is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = old_val

    seen_models = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/audio/speech"):
            seen_models["tts"] = json.loads(request.content.decode("utf-8"))["model"]
            return httpx.Response(200, content=b"RIFF")
        if request.url.path.endswith("/vad"):
            seen_models["vad"] = json.loads(request.content.decode("utf-8"))["model"]
            return httpx.Response(200, json={"is_speech": False})
        return httpx.Response(404)

    client = LocalAIClient(
        localai_base_url=cfg.localai_base_url,
        tts_model=cfg.localai_tts_model,
        vad_model=cfg.localai_vad_model,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.synthesize_speech("Hallo")
    client.detect_voice_activity(b"\x00\x00" * 50)
    assert seen_models == {"tts": "piper-de-thorsten", "vad": "silero-vad"}


def test_localai_url_normalization_model_discovery_and_stdout_error_logging(capsys) -> None:
    import json

    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if request.url.path == "/v1/models":
            return httpx.Response(
                200,
                json={"data": [{"id": "loaded-hermes-chat"}, {"id": "whisper-1"}, {"id": "piper-de"}]},
            )
        if request.url.path == "/v1/chat/completions":
            body = json.loads(request.content.decode("utf-8"))
            if body.get("model") == "loaded-hermes-chat":
                return httpx.Response(
                    200,
                    json={"model": "loaded-hermes-chat", "choices": [{"message": {"content": "Servus!"}}]},
                )
            return httpx.Response(404, json={"error": {"message": "model not found"}})
        if request.url.path == "/v1/audio/speech":
            return httpx.Response(404, text="speech route unavailable")
        if request.url.path == "/tts":
            return httpx.Response(200, content=b"RIFFnative-tts")
        if request.url.path == "/vad":
            return httpx.Response(200, json={"is_speech": True})
        return httpx.Response(404, text="not found")

    # Pass base URL WITHOUT '/v1' to verify automatic normalization
    client = LocalAIClient(
        localai_base_url="http://spark.local:8080",
        chat_model="missing-model-name",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.root_url == "http://spark.local:8080"
    assert client.v1_url == "http://spark.local:8080/v1"

    chat = client.chat_completion([{"role": "user", "content": "Hallo"}], language="de")
    assert chat.provider == "localai"
    assert chat.model == "loaded-hermes-chat"
    assert chat.content == "Servus!"

    tts = client.synthesize_speech("Hallo")
    assert tts.provider == "localai-tts"
    assert tts.audio_bytes == b"RIFFnative-tts"

    vad = client.detect_voice_activity(b"\x01\x00" * 40)
    assert vad.provider == "localai-vad"
    assert vad.is_speech is True
    assert "http://spark.local:8080/vad" in seen_urls

    captured = capsys.readouterr().out
    assert "[Alfred][API-ERROR]" in captured
    assert "HTTP 404" in captured
    assert "http://spark.local:8080/v1/chat/completions" in captured


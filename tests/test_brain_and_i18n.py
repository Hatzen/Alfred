"""End-to-end tests for AlfredAssistant orchestration, i18n (de/en), and security flow."""

from __future__ import annotations

from datetime import datetime

import httpx

from src.brain.assistant import AlfredAssistant
from src.config import AlfredConfig
from src.integrations.fancytanky import FancyTankyConnector
from src.memory.store import MemoryStore


def test_end_to_end_german_memory_personality_passphrase_and_interrupt() -> None:
    monday = datetime(2026, 11, 16, 10, 0)
    config = AlfredConfig(
        db_path=":memory:",
        default_language="de",
        passphrase_base="Nilpferd",
        simulation_mode=True,
    )
    bot = AlfredAssistant(config=config)

    # 1. Non-addressed chatter is ignored
    ignored = bot.process_input("Hallo wie geht es dir heute?", require_wake_word=True, when=monday)
    assert not ignored.accepted

    # 2. Save normal memory in German via wake phrase "Hey Alfred"
    saved = bot.process_input("Hey Alfred, merke dir: Lieblingsfarbe ist Dunkelblau", when=monday)
    assert saved.accepted
    assert saved.language == "de"
    assert "dunkelblau" in saved.reply.lower()
    assert "wake" in saved.beeps_played
    assert "thinking" in saved.beeps_played
    assert "success" in saved.beeps_played

    # 3. Recall memory
    recalled = bot.process_input("Hey Alexa, was ist meine Lieblingsfarbe?", when=monday)
    assert recalled.accepted
    assert "Dunkelblau" in recalled.reply

    # 4. Save sensitive memory using Monday passphrase ("NilpferdOne") and verify protection
    bot.memory_store.save_memory("steuernummer", "DE-99-887766", sensitive=True)

    blocked = bot.process_input("Hey Google, was ist meine Steuernummer?", when=monday)
    assert blocked.blocked_by_security is True
    assert blocked.requires_passphrase is True
    assert "security" in blocked.beeps_played
    assert "DE-99-887766" not in blocked.reply

    # Follow-up wrong weekday passphrase fails
    wrong = bot.process_input("NilpferdTwo", when=monday)
    assert wrong.blocked_by_security is True
    assert "DE-99-887766" not in wrong.reply

    # Re-ask and unlock with valid Monday variant ("Nilpfer1")
    _ = bot.process_input("Hey Alfred, was ist meine Steuernummer?", when=monday)
    unlocked = bot.process_input("Nilpfer1", when=monday)
    assert unlocked.blocked_by_security is False
    assert "DE-99-887766" in unlocked.reply

    # 5. Update personality and switch to English
    pers = bot.process_input("Hey Alfred, ändere deine Persönlichkeit auf: witzig", when=monday)
    assert pers.accepted
    assert bot.memory_store.get_personality().humor_level == 8

    # 6. Priority-0 interrupt works even without wake word
    stopped = bot.process_input("stop", when=monday)
    assert stopped.interrupted is True
    assert "cancel" in stopped.beeps_played


def test_assistant_routes_fancytanky_and_english_prompts() -> None:
    def tank_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "direction": "left"})

    config = AlfredConfig(db_path=":memory:", default_language="en", simulation_mode=True)
    tank = FancyTankyConnector(
        base_url="http://tank.test",
        http_client=httpx.Client(transport=httpx.MockTransport(tank_handler)),
    )
    bot = AlfredAssistant(config=config, fancytanky=tank)

    res = bot.process_input("Hey Alfred drive the FancyTanky robot left", language_override="en")
    assert res.accepted
    assert res.language == "en"
    assert res.route == "fancytanky"
    assert "move:left" in res.reply


def test_assistant_audio_frame_throttling_and_hermes_tool_call_dispatch() -> None:
    from src.audio.vad import IdleLoopThrottle, generate_pcm_tone
    from src.integrations.rest_learner import RESTSkillLearner
    from src.providers.localai import LocalAIClient

    slept = []
    config = AlfredConfig(db_path=":memory:", default_language="de", simulation_mode=True)

    def llm_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "model": "nous-hermes",
                    "choices": [
                        {
                            "message": {
                                "content": '<tool_call>{"name": "statuscheck", "arguments": {"unit": "c"}}</tool_call>'
                            }
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"status": "healthy", "temp": 21})

    shared_client = httpx.Client(transport=httpx.MockTransport(llm_handler))
    store = MemoryStore(db_path=":memory:")
    learner = RESTSkillLearner(memory_store=store, http_client=shared_client)
    learner.learn_skill(name="statuscheck", endpoint_url="http://sensor.local/health")

    bot = AlfredAssistant(
        config=config,
        memory_store=store,
        rest_learner=learner,
        localai_client=LocalAIClient(http_client=shared_client),
        idle_throttle=IdleLoopThrottle(idle_interval_ms=50, active_interval_ms=10, sleep_fn=slept.append),
    )

    quiet_vad = bot.process_audio_frame(bytes(640), pace_loop=True)
    speech_vad = bot.process_audio_frame(generate_pcm_tone(260.0, 20, amplitude=0.4), pace_loop=True)
    assert not quiet_vad.is_speech
    assert speech_vad.is_speech
    assert slept == [0.05, 0.01]

    reply = bot.process_input("Hey Alfred prüfe den Sensor", require_wake_word=True)
    assert reply.route == "hermes_tool_call"
    assert "healthy" in reply.reply
    store.close()

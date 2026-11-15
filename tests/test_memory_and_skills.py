"""Tests for SQLite persistent learning memory, personality adaptation, and Alexa-like skills."""

from __future__ import annotations

from pathlib import Path

from src.memory.store import MemoryStore, SkillDefinition


def test_memory_and_personality_persist_across_restarts(tmp_path: Path) -> None:
    db_file = str(tmp_path / "alfred_test.db")

    store1 = MemoryStore(db_path=db_file)
    store1.save_memory("lieblingsgetränk", "Schwarzer Kaffee")
    store1.save_memory("steuernummer", "123/456/7890")
    store1.update_personality(tone="charming butler", humor_level=7, add_rule="Sprich höflich")
    store1.save_skill(
        SkillDefinition(
            name="wohnzimmerlicht",
            description="Toggle living room lights",
            trigger_phrases=["licht an", "wohnzimmer licht"],
            endpoint_url="http://localhost:8123/api/lights",
            http_method="POST",
        )
    )
    store1.close()

    # Reopen from disk to prove durability across daemon restarts
    store2 = MemoryStore(db_path=db_file)
    masked = {m.key: m for m in store2.list_memories(include_sensitive_values=False)}
    assert masked["lieblingsgetränk"].value == "Schwarzer Kaffee"
    assert masked["lieblingsgetränk"].sensitive is False
    assert masked["steuernummer"].sensitive is True
    assert masked["steuernummer"].value == "[LOCKED - PASSPHRASE REQUIRED]"

    unlocked = {m.key: m for m in store2.list_memories(include_sensitive_values=True)}
    assert unlocked["steuernummer"].value == "123/456/7890"

    personality = store2.get_personality()
    assert personality.tone == "charming butler"
    assert personality.humor_level == 7
    assert "Sprich höflich" in personality.custom_rules

    prompt = store2.build_system_prompt(language="de", include_sensitive=False)
    assert "Schwarzer Kaffee" in prompt
    assert "123/456/7890" not in prompt

    matched_skill = store2.match_skill("Bitte mach das Wohnzimmer Licht an")
    assert matched_skill is not None
    assert matched_skill.name == "wohnzimmerlicht"
    store2.close()


"""System diagnostics script verifying audio, security, memory, and core invariants."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.brain.assistant import AlfredAssistant
from src.config import AlfredConfig


def run_diagnostics() -> int:
    """Execute smoke diagnostics across all Alfred subsystems using an in-memory DB."""
    config = AlfredConfig(db_path=":memory:", simulation_mode=True)
    bot = AlfredAssistant(config=config)

    # 1. Audio smart selection + soundcheck
    mic = bot.device_manager.select_smart_microphone()
    soundcheck = bot.device_manager.run_soundcheck()
    assert mic is not None, "Smart microphone selection failed"
    assert soundcheck.passed, "Output soundcheck failed"

    # 2. Wake-word gate
    ignored = bot.process_input("random background noise", require_wake_word=True)
    assert not ignored.accepted, "Non-wake utterance should be ignored"

    # 3. Dynamic weekday passphrase check (Monday = 1 -> NilpferdOne / Nilpfer1)
    monday = datetime(2026, 11, 16, 10, 0)  # Monday
    blocked = bot.process_input(
        "Hey Alfred, was ist meine Steuernummer?",
        when=monday,
    )
    assert blocked.blocked_by_security and blocked.requires_passphrase

    unlocked = bot.process_input(
        "Nilpfer1",
        when=monday,
    )
    assert not unlocked.blocked_by_security

    # 4. Priority-0 interrupt check
    stopped = bot.process_input("forget it")
    assert stopped.interrupted

    print(
        f"[OK] Alfred diagnostics passed | mic={mic.device_id} | speaker={soundcheck.selected_device_id} | beeps={len(bot.sound_engine.history)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_diagnostics())


# AGENTS.md — Repository Architecture & Agent Constraints

> **CRITICAL**: Before modifying or running code in this repository, you MUST read and follow [INVARIANTS.md](INVARIANTS.md).

## Repository Overview

**Alfred** is a privacy-first, locally running AI Assistant daemon with German-first (`de`) and English (`en`) bilingual support, designed to exceed traditional smart assistants:
- **LocalAI & Ollama Compatible**: Supports local APIs for STT, TTS, VAD, and Chat Completions with graceful offline simulation fallback.
- **Low-CPU Wake-Word & VAD Gate**: Filters commands for configurable names (`"Hey Alfred"`, `"Hey Alexa"`, `"Hey Google"`) while avoiding 100% CPU polling.
- **Instant Barge-In Interruption**: `"stop"`, `"forget it"`, `"stopp"`, `"vergiss es"` instantly drop generation and TTS output.
- **Dynamic Weekday Passphrase Guard**: Protects sensitive personal info (tax numbers, passwords), pornography/adult blocks, and harmful operations using a configurable word + current weekday (e.g., `"NilpferdOne"` / `"Nilpfer1"` on Monday).
- **Persistent Learning Memory & Alexa-Like Skills**: SQLite-backed memories, dynamic personality adaptation, and runtime REST API learning (including `FancyTanky`, `Paperless-ngx`, Wikipedia/web search, and local `Hermes`).
- **Smart Audio & Feedback Beeps**: Auto-selects active microphones and best working output devices via soundcheck sweeps, plus synthesized WAV feedback beeps.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full architecture specifications.

---

## Module Context

- [src/audio/AGENTS.md](src/audio/AGENTS.md) — Low-CPU VAD, synthesized feedback beeps, smart mic/speaker device selection & soundcheck.
- [src/wakeword/AGENTS.md](src/wakeword/AGENTS.md) — Configurable wake-name filter and follow-up window gating.
- [src/interrupt/AGENTS.md](src/interrupt/AGENTS.md) — Daemon state machine, generation preemption, and chunked TTS cancellation.
- [src/security/AGENTS.md](src/security/AGENTS.md) — Dynamic weekday passphrase validation and sensitive/harmful topic guard.
- [src/memory/AGENTS.md](src/memory/AGENTS.md) — SQLite persistent memories, adaptive personality, and dynamic skills.
- [src/providers/AGENTS.md](src/providers/AGENTS.md) — LocalAI / Ollama client for Chat, STT, TTS, and VAD.
- [src/integrations/AGENTS.md](src/integrations/AGENTS.md) — FancyTanky robot, Paperless-ngx, Wikipedia/web search, Hermes protocol/tool bridge, and REST API learner.
- [src/brain/AGENTS.md](src/brain/AGENTS.md) — Core assistant orchestration, German/English intent routing, and security flow.
- [src/web/AGENTS.md](src/web/AGENTS.md) — FastAPI REST daemon, WebSocket telemetry stream, and dark glassmorphic dashboard UI.

---

## Agent Authorization

### CodeReviewer
- **Authority**: Review diffs, verify invariant compliance (`INVARIANTS.md`), verify Python 3.9+ compatibility, and check test coverage.
- **Escalation**: Any relaxation of `INV-01` (instant interrupt) or `INV-03` (dynamic passphrase guard) requires explicit human approval.

### FeatureImplementer
- **Authority**: Implement/extend modules under `src/`, add tests in `tests/`, and update documentation in `docs/`.
- **Verification**: Must run `python -m pytest -v` and `python scripts/diagnose_system.py` with zero failures before completion.

---

## Known Footguns

1. **Python 3.9 Compatibility**: Host environment runs Python 3.9. Always include `from __future__ import annotations` and use `typing.Optional`, `typing.List`, `typing.Dict` on Pydantic `BaseModel` and `dataclass` fields.
2. **CPU Spin in Audio Loop**: Never run an unthrottled `while True` loop over audio buffers. Always pace idle loops via `IdleLoopThrottle` (`INV-02`).
3. **Passphrase Stem Edge Case**: Weekday passphrases must accept both full word (`Nilpferd1`, `NilpferdOne`, `NilpferdEins`) and dropped-final-letter stem (`Nilpfer1`) matching user expectation (`INV-03`).
4. **Blocking TTS Buffers**: Never emit a full response as a single blocking audio write; always iterate via `InterruptController.stream_tts_chunks` so `"stop"`/`"forget it"` cancels remaining speech immediately (`INV-01`).


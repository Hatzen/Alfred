# INVARIANTS.md — Non-Negotiable System Invariants

This file defines the non-negotiable architectural, privacy, security, performance, and testing invariants for the **Alfred** AI Assistant daemon. All agents, developers, and automated changes MUST adhere to these invariants without exception.

---

## INV-01: Instant Barge-In / Interrupt Preemption
- **Invariant**: Saying an interrupt phrase (`"stop"`, `"forget it"`, `"stopp"`, `"vergiss es"`, `"cancel"`, `"abbrechen"`) MUST immediately drop the current LLM generation and halt any ongoing TTS audio output.
- **Enforcement**: Interrupt checking takes highest priority before wake-word gating and before every streamed TTS chunk so audio output stops within `< 20ms` without waiting for full synthesis or LLM completion.

## INV-02: Low-CPU Wake-Word & Acoustic VAD Gate
- **Invariant**: Idle listening MUST NOT busy-wait or consume excessive CPU (never spinning at 100% CPU while waiting for commands).
- **Enforcement**:
  1. `LowCpuVAD` gates audio frames with lightweight stdlib RMS/ZCR calculations and adaptive noise-floor tracking.
  2. `IdleLoopThrottle` enforces adaptive sleep intervals (`idle_poll_interval_ms`) between audio frames.
  3. Heavy LLM/API/integration execution requires a configured wake name (e.g., `"Hey Alfred"`, `"Hey Alexa"`, `"Hey Google"`) unless inside an explicit follow-up window (such as answering a passphrase prompt).

## INV-03: Dynamic Weekday Passphrase Guard for Sensitive & Harmful Content
- **Invariant**: Sensitive personal data (e.g., tax numbers / `Steuernummer`, passwords, IBANs), adult/pornography requests, and potentially harmful/destructive actions MUST NOT be disclosed or executed without a valid dynamic weekday passphrase.
- **Enforcement**:
  - Configurable base word (default `"Nilpferd"`) combined with the ISO weekday (`1=Monday` .. `7=Sunday`), supporting full word + digit (`Nilpferd1`), stemmed base word + digit (`Nilpfer1`), English word (`NilpferdOne`), and German word (`NilpferdEins`).
  - Passphrases for wrong weekdays (e.g. `"Nilpferd2"` on Monday) MUST be rejected.

## INV-04: Persistent Learning Memory, Personality & Dynamic Skills
- **Invariant**: Learned facts, adaptive personality settings, and user-created Alexa-like REST skills MUST persist across daemon restarts in SQLite (`data/alfred_memory.db`).
- **Enforcement**: Sensitive memories are automatically flagged (`sensitive=True`) and masked unless unlocked with today's dynamic passphrase.

## INV-05: Hardware-Abstracted Smart Audio Selection & Feedback Beeps
- **Invariant**: Alfred MUST run reliably on headless servers, Windows/macOS developer laptops, and Linux/Raspberry Pi hardware with seamless simulation fallback when audio drivers are absent.
- **Enforcement**:
  1. Smart Microphone Selection measures active signal/SNR across available inputs to select the active mic.
  2. Smart Output Selection runs a specific `soundcheck` frequency sweep (`440Hz -> 880Hz -> 1320Hz`) to verify working playback devices.
  3. Feedback beeps (`wake`, `thinking`, `cancel`, `security`, `success`, `soundcheck`) give immediate non-verbal status cues.

## INV-06: Privacy-First LocalAI, Hermes & German-First Bilingual Support
- **Invariant**: All speech (STT, TTS, VAD), chat completions, Hermes integrations (Rhasspy/Snips MQTT protocol + Nous Hermes `<tool_call>` dispatch), and REST connectors run locally by default with full German (`de`) primary support and English (`en`) fallback.

## INV-07: Automated Verification Coverage
- **Invariant**: Every subsystem (audio/devices, wakeword/VAD, interrupt, security passphrase, memory/skills, integrations, assistant brain, and FastAPI web API) MUST be covered by automated `pytest` tests passing 100% via `python -m pytest -v`.


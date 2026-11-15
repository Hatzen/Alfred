# Brain Module — AGENTS.md

> Cross-reference: [INVARIANTS.md](../../INVARIANTS.md) (INV-01, INV-02, INV-03, INV-04, INV-06)

## Responsibilities
- `assistant.py`: Core `AlfredAssistant` orchestrator coordinating VAD/idle-loop throttling, Priority-0 interrupt checking, wake-word filtering, dynamic weekday passphrase authorization, memory & personality updates, skill learning/execution, LocalAI/Hermes chat, and chunked TTS streaming.


# Interrupt Module — AGENTS.md

> Cross-reference: [INVARIANTS.md](../../INVARIANTS.md) (INV-01)

## Responsibilities
- `controller.py`: Manages assistant execution states (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`), preemptive cancellation tokens, TTS speech chunk streaming, and instant `"stop"` / `"forget it"` cancellation.


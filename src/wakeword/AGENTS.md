# Wake-Word Module — AGENTS.md

> Cross-reference: [INVARIANTS.md](../../INVARIANTS.md) (INV-01, INV-02)

## Responsibilities
- `detector.py`: Filters incoming commands for configurable wake names (`"Hey Alfred"`, `"Hey Alexa"`, `"Hey Google"`) while always passing interrupt phrases (`"stop"`, `"forget it"`) at Priority 0.
- Supports follow-up windows so answering a follow-up prompt (like a dynamic passphrase) does not require repeating the wake word.


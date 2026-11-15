# Web API & Dashboard Module — AGENTS.md

> Cross-reference: [INVARIANTS.md](../../INVARIANTS.md) (INV-01, INV-03, INV-04, INV-05)

## Responsibilities
- `server.py`: FastAPI REST daemon endpoints (`/api/status`, `/api/command`, `/api/interrupt`, `/api/devices/*`, `/api/memories`, `/api/personality`, `/api/skills`, `/api/hermes/webhook`, `/api/security/passphrase-hint`) and WebSocket `/api/stream`.
- `static/`: Modern dark-mode glassmorphic dashboard supporting German/English switching, instant "STOP / FORGET IT" barge-in button, smart audio soundcheck controls, and memory/personality/skill management.


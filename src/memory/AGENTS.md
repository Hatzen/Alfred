# Memory Module — AGENTS.md

> Cross-reference: [INVARIANTS.md](../../INVARIANTS.md) (INV-03, INV-04)

## Responsibilities
- `store.py`: SQLite-backed durable store for learned memories, customizable personality traits, Alexa-like dynamic REST skills, and conversation episodes.
- Automatically flags sensitive facts (`Steuernummer`, `IBAN`, `Passwort`, etc.) so they remain masked unless unlocked with today's dynamic weekday passphrase.


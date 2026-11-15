# Integrations Module — AGENTS.md

> Cross-reference: [INVARIANTS.md](../../INVARIANTS.md) (INV-03, INV-04, INV-06)

## Responsibilities
- `fancytanky.py`: Controls and queries the FancyTanky robot tank REST API.
- `paperless.py`: Queries local Paperless-ngx document management APIs.
- `search.py`: Queries Wikipedia REST API (`de`/`en`) and web search endpoints.
- `hermes.py`: Supports Rhasspy/Snips Hermes MQTT voice payloads AND Nous Hermes `<tool_call>` parsing.
- `rest_learner.py`: Learns and invokes dynamic Alexa-like REST API skills stored in `MemoryStore`.


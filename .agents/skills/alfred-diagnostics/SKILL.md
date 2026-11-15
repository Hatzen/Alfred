---
name: alfred-diagnostics
description: Run Alfred diagnostic checks across audio smart-selection, wake-word filter, weekday passphrase guard, SQLite memory store, LocalAI/Hermes bridges, and pytest verification.
---

# Alfred Diagnostics Skill

When verifying or troubleshooting Alfred:

1. Run the built-in system diagnostic script:
   ```bash
   python scripts/diagnose_system.py
   ```
2. Run the full automated test suite:
   ```bash
   python -m pytest -v
   ```
3. Inspect [INVARIANTS.md](../../../INVARIANTS.md) to verify all safety, privacy, and low-CPU constraints remain intact.


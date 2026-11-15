# Audio Module — AGENTS.md

> Cross-reference: [INVARIANTS.md](../../INVARIANTS.md) (INV-02, INV-05)

## Responsibilities
- `vad.py`: Low-CPU RMS + Zero-Crossing Rate acoustic Voice Activity Detection (`LowCpuVAD`) and adaptive `IdleLoopThrottle` so idle listening never hits 100% CPU.
- `beeps.py`: Pure-Python 16-bit PCM WAV feedback sound synthesizer (`wake`, `thinking`, `cancel`, `security`, `success`, `soundcheck`).
- `devices.py`: Smart microphone selection (picking the active mic with strongest SNR/RMS) and smart output selection via `soundcheck` sweeps.

## Rules
1. Keep DSP loops dependency-free (stdlib `struct`, `math`, `wave`) so headless/Windows/Linux deployments never fail on missing C audio packages.
2. Always respect `idle_poll_interval_ms` in continuous listener loops.


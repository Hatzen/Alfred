# Architecture Decision Records (ADRs)

## ADR-001: Stdlib DSP & Pure-Python WAV Synthesis for Audio Core
- **Context**: Requiring heavy C extensions (`numpy`, `pyaudio`, `webrtcvad`) can break portability on headless servers or Python environments without build tools.
- **Decision**: Implement `LowCpuVAD` (RMS/ZCR) and `FeedbackSoundEngine` (16-bit PCM WAV synthesizer) using Python's standard library (`struct`, `math`, `wave`, `io`) with optional hardware hooks.
- **Consequence**: Audio gating, soundcheck sweeps, and feedback beeps work out of the box everywhere and execute in sub-millisecond time.

## ADR-002: Priority-0 Barge-In Before Wake-Word & Chunked TTS
- **Context**: Users must be able to say `"stop"` or `"forget it"` while Alfred is generating or speaking without having to say `"Hey Alfred, stop"`.
- **Decision**: `AlfredAssistant` evaluates interrupt phrases at Priority 0, and `InterruptController` streams TTS in sentence/clause chunks checking `is_cancelled()` before each chunk.
- **Consequence**: Stopping mid-sentence takes effect immediately before the next chunk is emitted.

## ADR-003: Weekday-Bound Dynamic Passphrase Algorithm
- **Context**: Static PINs or keywords can be overheard; the user specified e.g. `"Nilpferd"` + weekday number (`Monday=1` -> `NilpferdOne` / `Nilpferd1` / `Nilpfer1`).
- **Decision**: Use ISO weekday (`1..7`) mapped to digits, English words, German words, full base word, and optional dropped-final-letter stem (`base[:-1]`).
- **Consequence**: Natural spoken/typed passphrases work reliably in both German and English while blocking stale weekday tokens.

## ADR-004: Dual Hermes Integration (Voice MQTT Protocol + Nous Hermes Tool Calling)
- **Context**: "local running hermes" in self-hosted stacks typically refers either to the Rhasspy/Snips **Hermes MQTT protocol** (`hermes/asr/textCaptured`, `hermes/tts/say`) or local **Nous Hermes** models emitting `<tool_call>` tags.
- **Decision**: Support both transparently in `src/integrations/hermes.py` and expose `/api/hermes/webhook`.
- **Consequence**: Alfred integrates seamlessly whether the user runs Rhasspy/Wyoming/MQTT Hermes or a Nous Hermes LLM.


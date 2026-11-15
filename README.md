# Alfred

Privacy-first local AI Assistant daemon like Alexa — built for local execution, German-first bilingual interaction, low CPU wake-word gating, instant interruption, dynamic weekday security passphrases, persistent memory/skills, and seamless integration with **LocalAI**, **Hermes**, **FancyTanky**, and **Paperless-ngx**.

---

## AI Repo Harness & Standards

- **Core Invariants**: [INVARIANTS.md](INVARIANTS.md)
- **Agent Guide**: [AGENTS.md](AGENTS.md)
- **Architecture & Design**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Architecture Decisions**: [docs/DECISIONS.md](docs/DECISIONS.md)
- **Setup Guide**: [docs/SETUP.md](docs/SETUP.md)
- **Diagnostics Skill**: [.agents/skills/alfred-diagnostics/SKILL.md](.agents/skills/alfred-diagnostics/SKILL.md)
- **Standardized Makefile**: [Makefile](Makefile)

---

## Implemented Project Features

- **Local Daemon & Configurable APIs**: Runs locally via FastAPI/Uvicorn (`src/main.py`, `systemd/alfred.service`, `scripts/autostart.sh`) with environment/runtime configuration (`src/config.py`).
- **LocalAI Integration (TTS, STT, VAD, Chat)**: Unified `LocalAIClient` (`src/providers/localai.py`) supporting OpenAI-compatible LocalAI endpoints (`/chat/completions`, `/audio/transcriptions`, `/audio/speech`, `/vad`) plus Ollama and offline deterministic fallbacks.
- **Configurable Wake Names ("Hey Alfred", "Hey Alexa", "Hey Google")**: `CommandFilter` (`src/wakeword/detector.py`) requires a configured wake phrase for heavy tasks while leaving follow-up replies smooth.
- **Low-CPU Performance**: `LowCpuVAD` and `IdleLoopThrottle` (`src/audio/vad.py`) use lightweight stdlib RMS/ZCR gating and adaptive sleep pacing instead of spinning at 100% CPU.
- **Learning, Persistent Memory, Personality & Alexa-Like Skills**: SQLite-backed `MemoryStore` (`src/memory/store.py`) remembers facts across restarts, adapts tone/humor/formality/language dynamically, and learns custom REST skills via `RESTSkillLearner` (`src/integrations/rest_learner.py`).
- **REST & Knowledge Connectors**:
  - **FancyTanky Robot** (`src/integrations/fancytanky.py`)
  - **Paperless-ngx** (`src/integrations/paperless.py`)
  - **Wikipedia & Web Search** (`src/integrations/search.py`)
- **Dynamic Weekday Passphrase Security**: `DynamicPassphraseValidator` and `SensitiveTopicGuard` (`src/security/passphrase.py`) guard sensitive personal info (tax numbers / `Steuernummer`, passwords, IBANs), adult/pornography queries, and harmful actions using a configurable base word + current weekday (e.g., `NilpferdOne`, `Nilpferd1`, `Nilpfer1`, `NilpferdEins` on Monday).
- **Instant Barge-In Interrupt ("stop" / "forget it")**: `InterruptController` (`src/interrupt/controller.py`) checks `"stop"`, `"forget it"`, `"stopp"`, `"vergiss es"` at Priority 0, dropping pending generation and cutting off mid-sentence TTS output immediately.
- **Smart Audio Selection & Soundcheck**: `AudioDeviceManager` (`src/audio/devices.py`) probes active microphones by RMS/SNR and validates output devices using a `soundcheck` frequency sweep.
- **Synthesized Feedback Beeps**: `FeedbackSoundEngine` (`src/audio/beeps.py`) generates 16-bit PCM WAV tones for `wake`, `thinking`, `success`, `cancel`, `security`, and `soundcheck`.
- **Local Hermes Integration**: `HermesBridge` (`src/integrations/hermes.py`) supports both Rhasspy/Snips Hermes MQTT payloads (`hermes/asr/textCaptured`, `hermes/tts/say`, `/api/hermes/webhook`) and Nous Hermes `<tool_call>` parsing.
- **German-First Bilingual Support (`de` / `en`)**: Automatic language detection and localized responses prioritizing **Deutsch** alongside **English** (`src/i18n/locales.py`).

---

## Quickstart

### 1. Run Automated Tests & Diagnostics
```bash
python -m pytest -v
python scripts/diagnose_system.py
```

### 2. Start the Alfred Daemon & Web Dashboard
```bash
python -m src.main --simulation --host 0.0.0.0 --port 8020 --lang de
```
Open `http://localhost:8020` in your browser.

# Architecture — Alfred AI Assistant Daemon

## 1. High-Level Pipeline

```text
  [Mic / Text / Hermes MQTT]
             |
             v
  [LowCpuVAD + IdleLoopThrottle]  <-- INV-02 (<1% idle CPU)
             |
             v
  [Interrupt Check ("stop", "forget it", "stopp", "vergiss es")] <-- INV-01 (Priority 0)
             | (if interrupt -> cancel generation, clear TTS chunks, play cancel beep)
             v
  [CommandFilter (Wake Names: "Hey Alfred", "Hey Alexa", "Hey Google")]
             |
             v
  [SensitiveTopicGuard + DynamicPassphraseValidator] <-- INV-03 (BaseWord + Weekday)
             |
             v
  [AlfredAssistant Brain (de / en)]
      ├── MemoryStore (SQLite: memories, personality, dynamic skills, episodes)
      ├── Integrations (FancyTanky, Paperless, Wikipedia/Search, Hermes, REST Learner)
      └── LocalAIClient (Chat, STT, TTS, VAD + offline fallback)
             |
             v
  [InterruptController.stream_tts_chunks] --> [AudioDeviceManager + FeedbackSoundEngine]
```

## 2. Subsystems

1. **`src/audio/`**:
   - `LowCpuVAD`: Stdlib PCM RMS + Zero-Crossing Rate energy gate with adaptive noise floor.
   - `FeedbackSoundEngine`: Pure-Python 16-bit PCM WAV synthesizer for `wake`, `thinking`, `cancel`, `security`, `success`, and `soundcheck` cues.
   - `AudioDeviceManager`: Smart microphone selection (SNR/RMS probing) and speaker selection via `soundcheck` frequency sweep.
2. **`src/wakeword/` & `src/interrupt/`**:
   - `CommandFilter`: Extracts commands addressed to configured wake names while letting interrupts bypass wake-word checks.
   - `InterruptController`: Thread/async-safe session token and chunked TTS stream preemption.
3. **`src/security/`**:
   - `DynamicPassphraseValidator`: Validates weekday-dependent passphrases (`Nilpferd1`, `Nilpfer1`, `NilpferdOne`, `NilpferdEins`, etc.).
   - `SensitiveTopicGuard`: Detects financial/personal secrets, adult/pornography queries, harmful requests, and sensitive memory lookups.
4. **`src/memory/`**:
   - `MemoryStore`: Durable SQLite storage for learned facts, customizable personality traits, Alexa-like REST skills, and conversation episodes.
5. **`src/providers/` & `src/integrations/`**:
   - `LocalAIClient`: OpenAI-compatible LocalAI + Ollama client with deterministic offline fallback.
   - `FancyTankyConnector`, `PaperlessConnector`, `KnowledgeSearchConnector`, `HermesBridge`, `RESTSkillLearner`.
6. **`src/web/`**:
   - FastAPI daemon REST API, WebSocket live event stream, and dark glassmorphic dashboard UI.


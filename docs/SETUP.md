# Setup & Usage Guide

## 1. Prerequisites
- Python **3.9+** (tested on Python 3.9.13)
- On Linux / NVIDIA Spark for host audio playback & capture: `alsa-utils` (`aplay`, `arecord`)
- Local backends:
  - **LocalAI** (`http://localhost:8080/v1`) — recommended on NVIDIA Spark for Chat, Whisper STT, Piper TTS, and Silero VAD
  - **Ollama** (`http://localhost:11434`) — automatic fallback LLM backend
  - **FancyTanky** robot API (`http://localhost:8000`)
  - **Paperless-ngx** (`http://localhost:8010`)
  - **Hermes / MQTT broker** (`localhost:1883`)

## 2. Installation
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## 3. Running Tests & Diagnostics
```bash
python -m pytest -v
python scripts/diagnose_system.py
```

## 4. Starting Alfred in Production (NVIDIA Spark + LocalAI)
Copy `.env.nvidia-spark` to `.env` (or pass `--env-file` directly) and launch:
```bash
cp .env.nvidia-spark .env
python -m src.main --production
```
- **Production mode** (`ALFRED_SIMULATION=false` / `--production`) discovers real host microphones & speakers (ALSA on Linux/Spark, WinMM on Windows), plays real WAV feedback beeps, and connects to your live LocalAI/Ollama/REST endpoints.
- **Simulation mode** (`--simulation`) uses deterministic mock audio devices and silent sound cues for CI or headless development without audio hardware.

Open `http://localhost:8020` in your browser for the dashboard UI.

## 5. Configuration via `.env` & Environment Variables
| Variable | Default | Description |
| :--- | :--- | :--- |
| `ALFRED_SIMULATION` | `true` (`false` in `.env.nvidia-spark`) | `false` enables real host audio devices & audible WAV beeps |
| `ALFRED_DEFAULT_LANGUAGE` | `de` | Primary language (`de` or `en`) |
| `ALFRED_PASSPHRASE_BASE` | `Nilpferd` | Base secret word combined with weekday (`1..7`) |
| `ALFRED_WAKE_WORDS` | `hey alfred,alfred,hey alexa,hey google,hallo alfred` | Comma-separated wake names |
| `ALFRED_LOCALAI_URL` | `http://localhost:8080/v1` | LocalAI OpenAI-compatible base URL |
| `ALFRED_CHAT_MODEL` | `hermes-local` | LocalAI chat model (`hermes-3-llama-3.1-8b` in `.env.nvidia-spark`) |
| `ALFRED_STT_MODEL` | `whisper-1` | LocalAI STT model (`whisper-large-v3-turbo` in `.env.nvidia-spark`) |
| `ALFRED_TTS_MODEL` | `tts-1` | LocalAI TTS model (`piper-de-thorsten` in `.env.nvidia-spark`) |
| `ALFRED_TTS_VOICE` | `de-DE-thorsten-high` | LocalAI TTS voice |
| `ALFRED_VAD_MODEL` | `silero-vad` | LocalAI VAD model |
| `ALFRED_OLLAMA_URL` | `http://localhost:11434` | Ollama fallback URL |
| `ALFRED_OLLAMA_MODEL` | `qwen3.5:4b` | Ollama fallback model |
| `ALFRED_FANCYTANKY_URL` | `http://localhost:8000` | FancyTanky robot endpoint |
| `ALFRED_PAPERLESS_URL` | `http://localhost:8010` | Paperless-ngx base URL |
| `ALFRED_PAPERLESS_TOKEN` | `""` | Paperless API token |
| `ALFRED_DB_PATH` | `data/alfred_memory.db` | SQLite database path |

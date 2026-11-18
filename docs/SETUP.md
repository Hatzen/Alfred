# Setup & Usage Guide

## 1. Prerequisites
- **Python 3.9+** (tested on Python 3.9.13)
- **Linux / NVIDIA Spark host audio tools** (`arecord`, `aplay`):
  ```bash
  sudo apt-get update && sudo apt-get install -y alsa-utils
  ```
- **Local AI & Integration Backends**:
  - **LocalAI** (`http://localhost:8080/v1`) — recommended on NVIDIA Spark for Chat, Whisper STT, Piper TTS, and Silero VAD
  - **Ollama** (`http://localhost:11434`) — automatic fallback LLM backend
  - **FancyTanky** robot API (`http://localhost:8000`)
  - **Paperless-ngx** (`http://localhost:8010`)
  - **Hermes / MQTT broker** (`localhost:1883`)

---

## 2. Installation

```bash
git clone https://github.com/Hatzen/Alfred.git
cd Alfred

# Create and activate virtual environment (Linux / macOS)
python3 -m venv .venv
source .venv/bin/activate

# Or on Windows PowerShell:
# python -m venv .venv
# .\.venv\Scripts\Activate.ps1

# Install runtime dependencies
pip install -r requirements.txt

# Optional: install test dependencies (pytest, pytest-asyncio)
pip install -r requirements-dev.txt

# Optional: install package metadata in editable mode
pip install -e .
```
*(Shortcut via `Makefile`: `make install` or `make dev-install`.)*

---

## 3. Running LocalAI or Ollama on NVIDIA Spark

Start a GPU-accelerated **LocalAI** container on the Spark (port `8080`):
```bash
docker run -d --name localai --gpus all \
  -p 8080:8080 \
  -v localai-models:/models \
  localai/localai:latest-aio-gpu-nvidia-cuda-12
```
Or run **Ollama** on port `11434`:
```bash
ollama pull qwen3.5:4b
ollama serve
```
Update `ALFRED_CHAT_MODEL`, `ALFRED_STT_MODEL`, `ALFRED_TTS_MODEL`, or `ALFRED_OLLAMA_MODEL` in `.env` to match the models loaded on your server.

---

## 4. Running Tests & Diagnostics

```bash
python -m pytest -v
python scripts/diagnose_system.py
```

---

## 5. Starting Alfred in Production (NVIDIA Spark + LocalAI)

Copy `.env.nvidia-spark` to `.env`, set a private `ALFRED_PASSPHRASE_BASE` (do not keep `"Nilpferd"` in production), and launch:
```bash
cp .env.nvidia-spark .env
python -m src.main --production
```
- **Production mode** (`ALFRED_SIMULATION=false` / `--production`) discovers real host microphones & speakers (ALSA on Linux/Spark, WinMM on Windows), plays real WAV feedback beeps, and connects to your live LocalAI/Ollama/REST endpoints.
- **Simulation mode** (`--simulation`) uses deterministic mock audio devices and silent sound cues for CI or headless development without audio hardware.

Open `http://<spark-ip>:8020` (or `http://localhost:8020`) in your browser for the dashboard UI.

### Autostart with systemd (Linux / NVIDIA Spark)
1. Copy the repository to `/opt/alfred` and place your configured `.env` inside `/opt/alfred/.env`.
2. Install and enable [systemd/alfred.service](../systemd/alfred.service):
   ```bash
   sudo cp systemd/alfred.service /etc/systemd/system/alfred.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now alfred
   ```

---

## 6. Configuration via `.env` & Environment Variables
| Variable | Default | Description |
| :--- | :--- | :--- |
| `ALFRED_SIMULATION` | `true` (`false` in `.env.nvidia-spark`) | `false` enables real host audio devices & audible WAV beeps |
| `ALFRED_DEFAULT_LANGUAGE` | `de` | Primary language (`de` or `en`) |
| `ALFRED_PASSPHRASE_BASE` | `Nilpferd` | Base secret word combined with weekday (`1..7`) — change in `.env`! |
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

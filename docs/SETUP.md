# Setup & Usage Guide

## 1. Prerequisites
- Python **3.9+** (tested on Python 3.9.13)
- Optional local services:
  - **LocalAI** (`http://localhost:8080/v1`) or **Ollama** (`http://localhost:11434`)
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

## 4. Starting the Alfred Daemon
```bash
python -m src.main --simulation --host 0.0.0.0 --port 8020 --lang de
```
Open `http://localhost:8020` in your browser for the dashboard UI.

## 5. Configuration via Environment Variables
| Variable | Default | Description |
| :--- | :--- | :--- |
| `ALFRED_DEFAULT_LANGUAGE` | `de` | Primary language (`de` or `en`) |
| `ALFRED_PASSPHRASE_BASE` | `Nilpferd` | Base secret word combined with weekday (`1..7`) |
| `ALFRED_WAKE_WORDS` | `hey alfred,alfred,hey alexa,hey google,hallo alfred` | Comma-separated wake names |
| `ALFRED_LOCALAI_URL` | `http://localhost:8080/v1` | LocalAI OpenAI-compatible base URL |
| `ALFRED_OLLAMA_URL` | `http://localhost:11434` | Ollama fallback URL |
| `ALFRED_FANCYTANKY_URL` | `http://localhost:8000` | FancyTanky robot endpoint |
| `ALFRED_PAPERLESS_URL` | `http://localhost:8010` | Paperless-ngx base URL |
| `ALFRED_PAPERLESS_TOKEN` | `""` | Paperless API token |
| `ALFRED_DB_PATH` | `data/alfred_memory.db` | SQLite database path |


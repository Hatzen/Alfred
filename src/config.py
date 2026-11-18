"""Central configuration for the Alfred AI Assistant daemon."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

DEFAULT_WAKE_WORDS = [
    "hey alfred",
    "alfred",
    "hey alexa",
    "hey google",
    "hallo alfred",
]

DEFAULT_INTERRUPT_PHRASES = [
    "stop",
    "forget it",
    "cancel",
    "nevermind",
    "never mind",
    "stopp",
    "vergiss es",
    "abbrechen",
    "ruhe",
    "halt",
]

DEFAULT_SENSITIVE_KEYWORDS = [
    "steuernummer",
    "taxnumber",
    "tax number",
    "tax id",
    "steuer-id",
    "iban",
    "kreditkarte",
    "credit card",
    "passwort",
    "password",
    "pin",
    "geheim",
    "secret",
    "porn",
    "pornography",
    "pornografie",
    "porno",
    "nsfw",
    "erotik",
    "hack",
    "exploit",
    "malware",
    "ransomware",
    "delete all",
    "alles löschen",
    "rm -rf",
    "format c:",
    "waffe",
    "weapon",
    "bomb",
    "bombe",
    "selbstmord",
    "suicide",
]


def _split_env_list(env_name: str, default: List[str]) -> List[str]:
    """Parse a comma-separated environment variable into normalized lowercase strings."""
    raw = os.getenv(env_name)
    if not raw:
        return list(default)
    items = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return items or list(default)


def _env_bool(env_name: str, default: bool) -> bool:
    """Parse boolean environment flags safely."""
    raw = os.getenv(env_name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "ja"}


def load_dotenv_file(env_path: Optional[str] = ".env", *, override: bool = False) -> Dict[str, str]:
    """Load key=value pairs from a .env file into os.environ without external deps."""
    loaded: Dict[str, str] = {}
    if not env_path:
        return loaded

    path = Path(env_path)
    if not path.is_file():
        return loaded

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()

        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value

    return loaded


class AlfredConfig(BaseModel):
    """Runtime configuration for Alfred with environment variable overrides."""

    assistant_name: str = Field(default_factory=lambda: os.getenv("ALFRED_NAME", "Alfred"))
    wake_words: List[str] = Field(
        default_factory=lambda: _split_env_list("ALFRED_WAKE_WORDS", DEFAULT_WAKE_WORDS)
    )
    interrupt_phrases: List[str] = Field(
        default_factory=lambda: _split_env_list("ALFRED_INTERRUPT_PHRASES", DEFAULT_INTERRUPT_PHRASES)
    )
    default_language: str = Field(
        default_factory=lambda: os.getenv("ALFRED_DEFAULT_LANGUAGE", "de").lower()
    )
    passphrase_base: str = Field(
        default_factory=lambda: os.getenv("ALFRED_PASSPHRASE_BASE", "Nilpferd")
    )
    sensitive_keywords: List[str] = Field(
        default_factory=lambda: _split_env_list("ALFRED_SENSITIVE_KEYWORDS", DEFAULT_SENSITIVE_KEYWORDS)
    )
    localai_base_url: str = Field(
        default_factory=lambda: os.getenv("ALFRED_LOCALAI_URL", "http://localhost:8080/v1")
    )
    localai_api_key: str = Field(
        default_factory=lambda: os.getenv("ALFRED_LOCALAI_API_KEY", "local-no-key-required")
    )
    localai_chat_model: str = Field(
        default_factory=lambda: os.getenv("ALFRED_CHAT_MODEL", "hermes-local")
    )
    localai_stt_model: str = Field(
        default_factory=lambda: os.getenv("ALFRED_STT_MODEL", "whisper-1")
    )
    localai_tts_model: str = Field(
        default_factory=lambda: os.getenv("ALFRED_TTS_MODEL", "tts-1")
    )
    localai_tts_voice: str = Field(
        default_factory=lambda: os.getenv("ALFRED_TTS_VOICE", "de-DE-thorsten-high")
    )
    localai_vad_model: str = Field(
        default_factory=lambda: os.getenv("ALFRED_VAD_MODEL", "silero-vad")
    )
    ollama_base_url: str = Field(
        default_factory=lambda: os.getenv("ALFRED_OLLAMA_URL", "http://localhost:11434")
    )
    ollama_model: str = Field(
        default_factory=lambda: os.getenv("ALFRED_OLLAMA_MODEL", "qwen3.5:4b")
    )
    fancytanky_url: str = Field(
        default_factory=lambda: os.getenv("ALFRED_FANCYTANKY_URL", "http://localhost:8000")
    )
    paperless_url: str = Field(
        default_factory=lambda: os.getenv("ALFRED_PAPERLESS_URL", "http://localhost:8010")
    )
    paperless_token: str = Field(
        default_factory=lambda: os.getenv("ALFRED_PAPERLESS_TOKEN", "")
    )
    hermes_enabled: bool = Field(
        default_factory=lambda: _env_bool("ALFRED_HERMES_ENABLED", True)
    )
    hermes_mqtt_host: str = Field(
        default_factory=lambda: os.getenv("ALFRED_HERMES_MQTT_HOST", "localhost")
    )
    hermes_mqtt_port: int = Field(
        default_factory=lambda: int(os.getenv("ALFRED_HERMES_MQTT_PORT", "1883"))
    )
    smart_audio_enabled: bool = Field(
        default_factory=lambda: _env_bool("ALFRED_SMART_AUDIO", True)
    )
    input_device_id: Optional[str] = Field(
        default_factory=lambda: os.getenv("ALFRED_INPUT_DEVICE")
    )
    output_device_id: Optional[str] = Field(
        default_factory=lambda: os.getenv("ALFRED_OUTPUT_DEVICE")
    )
    idle_poll_interval_ms: int = Field(
        default_factory=lambda: int(os.getenv("ALFRED_IDLE_POLL_MS", "40"))
    )
    follow_up_window_seconds: float = Field(
        default_factory=lambda: float(os.getenv("ALFRED_FOLLOW_UP_SECONDS", "15.0"))
    )
    simulation_mode: bool = Field(
        default_factory=lambda: _env_bool("ALFRED_SIMULATION", True)
    )
    db_path: str = Field(
        default_factory=lambda: os.getenv("ALFRED_DB_PATH", str(Path("data") / "alfred_memory.db"))
    )
    host: str = Field(default_factory=lambda: os.getenv("ALFRED_HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("ALFRED_PORT", "8020")))

    @classmethod
    def from_env(
        cls,
        env_file: Optional[str] = ".env",
        *,
        override: bool = False,
        **overrides: Any,
    ) -> "AlfredConfig":
        """Load an optional .env file first, then instantiate AlfredConfig."""
        load_dotenv_file(env_file, override=override)
        filtered = {k: v for k, v in overrides.items() if v is not None}
        return cls(**filtered)


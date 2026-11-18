"""LocalAI and Ollama provider client package."""

from src.providers.localai import (
    ChatResult,
    LocalAIClient,
    SpeechResult,
    TranscriptionResult,
    VADEndpointResult,
    log_api_error,
    log_api_info,
)

__all__ = [
    "ChatResult",
    "LocalAIClient",
    "SpeechResult",
    "TranscriptionResult",
    "VADEndpointResult",
    "log_api_error",
    "log_api_info",
]


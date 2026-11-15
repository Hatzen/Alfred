"""LocalAI and Ollama provider client package."""

from src.providers.localai import (
    ChatResult,
    LocalAIClient,
    SpeechResult,
    TranscriptionResult,
    VADEndpointResult,
)

__all__ = [
    "ChatResult",
    "LocalAIClient",
    "SpeechResult",
    "TranscriptionResult",
    "VADEndpointResult",
]


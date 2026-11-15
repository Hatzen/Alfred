"""Unified LocalAI + Ollama client for local Chat, STT, TTS, and VAD APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import httpx

from src.audio.beeps import synthesize_wav_bytes
from src.audio.vad import LowCpuVAD


@dataclass
class ChatResult:
    """Response returned by the local LLM chat API."""

    content: str
    provider: str
    model: str
    cancelled: bool = False
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TranscriptionResult:
    """Speech-to-text result from LocalAI STT or fallback."""

    text: str
    language: str
    provider: str


@dataclass
class SpeechResult:
    """Text-to-speech WAV audio result from LocalAI TTS or fallback synthesizer."""

    audio_bytes: bytes
    voice: str
    provider: str


@dataclass
class VADEndpointResult:
    """Voice Activity Detection result from LocalAI VAD endpoint or local LowCpuVAD."""

    is_speech: bool
    provider: str
    rms: float = 0.0


class LocalAIClient:
    """Connects to LocalAI (TTS, STT, VAD, Chat) and Ollama with graceful offline fallback."""

    def __init__(
        self,
        localai_base_url: str = "http://localhost:8080/v1",
        api_key: str = "local-no-key-required",
        chat_model: str = "hermes-local",
        tts_voice: str = "de-DE-thorsten-high",
        ollama_base_url: str = "http://localhost:11434",
        timeout_seconds: float = 4.0,
        http_client: Optional[httpx.Client] = None,
        local_vad: Optional[LowCpuVAD] = None,
    ) -> None:
        self.localai_base_url = localai_base_url.rstrip("/")
        self.api_key = api_key
        self.chat_model = chat_model
        self.tts_voice = tts_voice
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._local_vad = local_vad or LowCpuVAD()

    def _get_client(self) -> tuple:
        if self._http_client is not None:
            return self._http_client, False
        return httpx.Client(timeout=self.timeout_seconds), True

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        language: str = "de",
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> ChatResult:
        """Request a chat completion from LocalAI, falling back to Ollama or offline mode."""
        if cancel_check is not None and cancel_check():
            return ChatResult(content="", provider="cancelled", model=self.chat_model, cancelled=True)

        client, should_close = self._get_client()
        try:
            # 1. Try LocalAI OpenAI-compatible Chat API
            try:
                resp = client.post(
                    f"{self.localai_base_url}/chat/completions",
                    headers=self._headers(),
                    json={
                        "model": self.chat_model,
                        "messages": messages,
                        "temperature": 0.4,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    if cancel_check is not None and cancel_check():
                        return ChatResult(content="", provider="cancelled", model=self.chat_model, cancelled=True)
                    return ChatResult(
                        content=content,
                        provider="localai",
                        model=data.get("model", self.chat_model),
                    )
            except Exception:
                pass

            if cancel_check is not None and cancel_check():
                return ChatResult(content="", provider="cancelled", model=self.chat_model, cancelled=True)

            # 2. Try local Ollama Chat API
            try:
                resp = client.post(
                    f"{self.ollama_base_url}/api/chat",
                    json={"model": "gemma2:9b", "messages": messages, "stream": False},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("message", {}).get("content", "").strip()
                    if content:
                        return ChatResult(content=content, provider="ollama", model="gemma2:9b")
            except Exception:
                pass
        finally:
            if should_close:
                client.close()

        if cancel_check is not None and cancel_check():
            return ChatResult(content="", provider="cancelled", model=self.chat_model, cancelled=True)

        # 3. Deterministic offline fallback
        user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        if language == "de":
            fallback = (
                f"Ich habe deine Anfrage '{user_msg}' lokal empfangen. "
                "Aktuell läuft kein externer LocalAI/Ollama-Endpunkt, daher antworte ich im lokalen Offline-Modus."
            )
        else:
            fallback = (
                f"I received your request '{user_msg}' locally. "
                "No external LocalAI/Ollama server responded, so I am replying in offline fallback mode."
            )
        return ChatResult(content=fallback, provider="offline-fallback", model="alfred-local")

    def transcribe_audio(
        self,
        wav_bytes: bytes,
        language: str = "de",
        filename: str = "audio.wav",
    ) -> TranscriptionResult:
        """Transcribe audio via LocalAI STT (/audio/transcriptions), with graceful fallback."""
        client, should_close = self._get_client()
        try:
            resp = client.post(
                f"{self.localai_base_url}/audio/transcriptions",
                headers=self._headers(),
                data={"model": "whisper-1", "language": language},
                files={"file": (filename, wav_bytes, "audio/wav")},
            )
            if resp.status_code == 200:
                text = resp.json().get("text", "").strip()
                return TranscriptionResult(text=text, language=language, provider="localai-stt")
        except Exception:
            pass
        finally:
            if should_close:
                client.close()

        return TranscriptionResult(text="", language=language, provider="offline-fallback")

    def synthesize_speech(
        self,
        text: str,
        voice: Optional[str] = None,
    ) -> SpeechResult:
        """Synthesize spoken audio via LocalAI TTS (/audio/speech), with tone WAV fallback."""
        chosen_voice = voice or self.tts_voice
        client, should_close = self._get_client()
        try:
            resp = client.post(
                f"{self.localai_base_url}/audio/speech",
                headers=self._headers(),
                json={"model": "tts-1", "input": text, "voice": chosen_voice},
            )
            if resp.status_code == 200 and resp.content:
                return SpeechResult(audio_bytes=resp.content, voice=chosen_voice, provider="localai-tts")
        except Exception:
            pass
        finally:
            if should_close:
                client.close()

        fallback_wav = synthesize_wav_bytes([(523.25, 60), (659.25, 80)])
        return SpeechResult(audio_bytes=fallback_wav, voice=chosen_voice, provider="offline-synth")

    def detect_voice_activity(self, pcm_bytes: bytes) -> VADEndpointResult:
        """Check voice activity via LocalAI VAD endpoint or fall back to local LowCpuVAD."""
        client, should_close = self._get_client()
        try:
            resp = client.post(
                f"{self.localai_base_url}/vad",
                headers=self._headers(),
                json={"sample_rate": 16000, "pcm_length": len(pcm_bytes)},
            )
            if resp.status_code == 200:
                data = resp.json()
                segments = data.get("segments") or []
                active = bool(data.get("is_speech", bool(segments)))
                return VADEndpointResult(is_speech=active, provider="localai-vad", rms=0.0)
        except Exception:
            pass
        finally:
            if should_close:
                client.close()

        local_res = self._local_vad.process_frame(pcm_bytes)
        return VADEndpointResult(is_speech=local_res.is_speech, provider="local-lowcpu-vad", rms=local_res.rms)


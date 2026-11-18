"""Unified LocalAI + Ollama client for local Chat, STT, TTS, and VAD APIs."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from src.audio.beeps import synthesize_wav_bytes
from src.audio.vad import LowCpuVAD

_LOGGER = logging.getLogger("alfred.api")


def log_api_error(
    component: str,
    method: str,
    url: str,
    *,
    status_code: Optional[int] = None,
    detail: str = "",
) -> None:
    """Print API errors directly to stdout so backend/endpoint issues are visible immediately."""
    snippet = " ".join(detail.strip().split())[:260]
    if status_code is not None:
        msg = f"[Alfred][API-ERROR] {component} {method} {url} -> HTTP {status_code}: {snippet or 'request failed'}"
    else:
        msg = f"[Alfred][API-ERROR] {component} {method} {url} -> {snippet or 'connection failed'}"
    print(msg, file=sys.stdout, flush=True)
    _LOGGER.warning(msg)


def log_api_info(component: str, message: str) -> None:
    """Print API discovery/fallback diagnostics to stdout."""
    msg = f"[Alfred][API-INFO] {component}: {message}"
    print(msg, file=sys.stdout, flush=True)
    _LOGGER.info(msg)


def _normalize_localai_urls(base_url: str) -> Tuple[str, str]:
    """Return (root_url, v1_url) regardless of whether caller included '/v1'."""
    cleaned = (base_url or "http://localhost:8080/v1").strip().rstrip("/")
    if cleaned.lower().endswith("/v1"):
        root_url = cleaned[:-3].rstrip("/")
        v1_url = cleaned
    else:
        root_url = cleaned
        v1_url = f"{cleaned}/v1"
    return root_url, v1_url


def _pick_fallback_model(models: List[str], kind: str) -> Optional[str]:
    """Select the best matching LocalAI model ID for chat, stt, or tts."""
    if not models:
        return None
    if kind == "stt":
        for m in models:
            if any(tok in m.lower() for tok in ("whisper", "stt", "asr", "transcri")):
                return m
        return None
    if kind == "tts":
        for m in models:
            if any(tok in m.lower() for tok in ("piper", "tts", "kokoro", "voice", "bark", "coqui", "parler")):
                return m
        return None
    # chat
    non_audio = [
        m
        for m in models
        if not any(tok in m.lower() for tok in ("whisper", "piper", "tts", "silero", "vad", "embed"))
    ]
    return non_audio[0] if non_audio else models[0]


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
        stt_model: str = "whisper-1",
        tts_model: str = "tts-1",
        tts_voice: str = "de-DE-thorsten-high",
        vad_model: str = "silero-vad",
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "qwen3.5:4b",
        timeout_seconds: float = 30.0,
        http_client: Optional[httpx.Client] = None,
        local_vad: Optional[LowCpuVAD] = None,
    ) -> None:
        self.root_url, self.v1_url = _normalize_localai_urls(localai_base_url)
        self.localai_base_url = self.v1_url
        self.api_key = api_key
        self.chat_model = chat_model
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.tts_voice = tts_voice
        self.vad_model = vad_model
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.ollama_model = ollama_model
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._local_vad = local_vad or LowCpuVAD()

    def _get_client(self) -> tuple:
        if self._http_client is not None:
            return self._http_client, False
        return httpx.Client(timeout=self.timeout_seconds), True

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def list_models(self, client: Optional[httpx.Client] = None) -> List[str]:
        """Query LocalAI /v1/models (with /models fallback) to inspect loaded model IDs."""
        owned_client = client is None
        active_client, should_close = self._get_client() if owned_client else (client, False)
        try:
            for url in (f"{self.v1_url}/models", f"{self.root_url}/models"):
                try:
                    resp = active_client.get(url, headers=self._headers())
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("data", data if isinstance(data, list) else [])
                        ids = [
                            str(item["id"])
                            for item in items
                            if isinstance(item, dict) and item.get("id")
                        ]
                        return ids
                    log_api_error("LocalAI", "GET", url, status_code=resp.status_code, detail=resp.text)
                except Exception as exc:
                    log_api_error("LocalAI", "GET", url, detail=str(exc))
            return []
        finally:
            if should_close:
                active_client.close()

    def health_report(self) -> Dict[str, Any]:
        """Return endpoint URLs and live model availability for LocalAI & Ollama."""
        localai_models = self.list_models()
        ollama_models: List[str] = []
        client, should_close = self._get_client()
        tags_url = f"{self.ollama_base_url}/api/tags"
        try:
            resp = client.get(tags_url)
            if resp.status_code == 200:
                ollama_models = [
                    str(m["name"])
                    for m in resp.json().get("models", [])
                    if isinstance(m, dict) and m.get("name")
                ]
            else:
                log_api_error("Ollama", "GET", tags_url, status_code=resp.status_code, detail=resp.text)
        except Exception as exc:
            log_api_error("Ollama", "GET", tags_url, detail=str(exc))
        finally:
            if should_close:
                client.close()

        return {
            "localai": {
                "root_url": self.root_url,
                "v1_url": self.v1_url,
                "reachable": len(localai_models) > 0,
                "configured_models": {
                    "chat": self.chat_model,
                    "stt": self.stt_model,
                    "tts": self.tts_model,
                    "vad": self.vad_model,
                },
                "available_models": localai_models,
            },
            "ollama": {
                "base_url": self.ollama_base_url,
                "reachable": len(ollama_models) > 0,
                "configured_model": self.ollama_model,
                "available_models": ollama_models,
            },
        }

    def _post_localai_chat(
        self, client: httpx.Client, model: str, messages: List[Dict[str, str]]
    ) -> Optional[ChatResult]:
        url = f"{self.v1_url}/chat/completions"
        try:
            resp = client.post(
                url,
                headers=self._headers(),
                json={"model": model, "messages": messages, "temperature": 0.4},
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                return ChatResult(
                    content=content,
                    provider="localai",
                    model=data.get("model", model),
                )
            log_api_error("LocalAI", "POST", url, status_code=resp.status_code, detail=resp.text)
        except Exception as exc:
            log_api_error("LocalAI", "POST", url, detail=str(exc))
        return None

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
            # 1. Try LocalAI OpenAI-compatible Chat API (with automatic /v1/models fallback)
            result = self._post_localai_chat(client, self.chat_model, messages)
            if result is None:
                available = self.list_models(client=client)
                fallback_model = _pick_fallback_model(available, "chat")
                if fallback_model and fallback_model != self.chat_model:
                    log_api_info(
                        "LocalAI",
                        f"Retrying chat with discovered model '{fallback_model}' (available: {available})",
                    )
                    result = self._post_localai_chat(client, fallback_model, messages)

            if result is not None:
                if cancel_check is not None and cancel_check():
                    return ChatResult(content="", provider="cancelled", model=result.model, cancelled=True)
                return result

            if cancel_check is not None and cancel_check():
                return ChatResult(content="", provider="cancelled", model=self.chat_model, cancelled=True)

            # 2. Try local Ollama Chat API (configured model, then first available tag)
            ollama_url = f"{self.ollama_base_url}/api/chat"
            try:
                chosen_model = self.ollama_model
                resp = client.post(
                    ollama_url,
                    json={"model": chosen_model, "messages": messages, "stream": False},
                )
                if resp.status_code != 200:
                    log_api_error("Ollama", "POST", ollama_url, status_code=resp.status_code, detail=resp.text)
                    tags_url = f"{self.ollama_base_url}/api/tags"
                    tags_resp = client.get(tags_url)
                    if tags_resp.status_code == 200:
                        models = tags_resp.json().get("models", [])
                        if models and models[0].get("name"):
                            chosen_model = models[0]["name"]
                            log_api_info("Ollama", f"Retrying chat with discovered tag '{chosen_model}'")
                            resp = client.post(
                                ollama_url,
                                json={"model": chosen_model, "messages": messages, "stream": False},
                            )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("message", {}).get("content", "").strip()
                    if content:
                        return ChatResult(content=content, provider="ollama", model=chosen_model)
                else:
                    log_api_error("Ollama", "POST", ollama_url, status_code=resp.status_code, detail=resp.text)
            except Exception as exc:
                log_api_error("Ollama", "POST", ollama_url, detail=str(exc))
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

    def _post_stt(
        self,
        client: httpx.Client,
        url: str,
        model: str,
        wav_bytes: bytes,
        language: str,
        filename: str,
    ) -> Optional[str]:
        try:
            resp = client.post(
                url,
                headers=self._headers(),
                data={"model": model, "language": language},
                files={"file": (filename, wav_bytes, "audio/wav")},
            )
            if resp.status_code == 200:
                return resp.json().get("text", "").strip()
            log_api_error("LocalAI-STT", "POST", url, status_code=resp.status_code, detail=resp.text)
        except Exception as exc:
            log_api_error("LocalAI-STT", "POST", url, detail=str(exc))
        return None

    def transcribe_audio(
        self,
        wav_bytes: bytes,
        language: str = "de",
        filename: str = "audio.wav",
    ) -> TranscriptionResult:
        """Transcribe audio via LocalAI STT (/v1/audio/transcriptions or root fallback)."""
        client, should_close = self._get_client()
        try:
            v1_stt = f"{self.v1_url}/audio/transcriptions"
            text = self._post_stt(client, v1_stt, self.stt_model, wav_bytes, language, filename)
            if text is not None:
                return TranscriptionResult(text=text, language=language, provider="localai-stt")

            available = self.list_models(client=client)
            discovered = _pick_fallback_model(available, "stt")
            if discovered and discovered != self.stt_model:
                log_api_info("LocalAI-STT", f"Retrying STT with discovered model '{discovered}'")
                text = self._post_stt(client, v1_stt, discovered, wav_bytes, language, filename)
                if text is not None:
                    return TranscriptionResult(text=text, language=language, provider="localai-stt")

            root_stt = f"{self.root_url}/audio/transcriptions"
            if root_stt != v1_stt:
                text = self._post_stt(client, root_stt, discovered or self.stt_model, wav_bytes, language, filename)
                if text is not None:
                    return TranscriptionResult(text=text, language=language, provider="localai-stt")
        finally:
            if should_close:
                client.close()

        return TranscriptionResult(text="", language=language, provider="offline-fallback")

    def _post_tts(self, client: httpx.Client, url: str, payload: Dict[str, Any]) -> Optional[bytes]:
        try:
            resp = client.post(url, headers=self._headers(), json=payload)
            if resp.status_code == 200 and resp.content:
                return resp.content
            log_api_error("LocalAI-TTS", "POST", url, status_code=resp.status_code, detail=resp.text)
        except Exception as exc:
            log_api_error("LocalAI-TTS", "POST", url, detail=str(exc))
        return None

    def synthesize_speech(
        self,
        text: str,
        voice: Optional[str] = None,
    ) -> SpeechResult:
        """Synthesize spoken audio via OpenAI /v1/audio/speech or LocalAI native /tts."""
        chosen_voice = voice or self.tts_voice
        client, should_close = self._get_client()
        try:
            v1_tts = f"{self.v1_url}/audio/speech"
            audio = self._post_tts(
                client,
                v1_tts,
                {"model": self.tts_model, "input": text, "voice": chosen_voice},
            )
            if audio is not None:
                return SpeechResult(audio_bytes=audio, voice=chosen_voice, provider="localai-tts")

            available = self.list_models(client=client)
            discovered = _pick_fallback_model(available, "tts")
            if discovered and discovered != self.tts_model:
                log_api_info("LocalAI-TTS", f"Retrying TTS with discovered model '{discovered}'")
                audio = self._post_tts(
                    client,
                    v1_tts,
                    {"model": discovered, "input": text, "voice": chosen_voice},
                )
                if audio is not None:
                    return SpeechResult(audio_bytes=audio, voice=chosen_voice, provider="localai-tts")

            native_tts = f"{self.root_url}/tts"
            audio = self._post_tts(
                client,
                native_tts,
                {"model": discovered or self.tts_model, "input": text, "backend": chosen_voice},
            )
            if audio is not None:
                return SpeechResult(audio_bytes=audio, voice=chosen_voice, provider="localai-tts")
        finally:
            if should_close:
                client.close()

        fallback_wav = synthesize_wav_bytes([(523.25, 60), (659.25, 80)])
        return SpeechResult(audio_bytes=fallback_wav, voice=chosen_voice, provider="offline-synth")

    def detect_voice_activity(self, pcm_bytes: bytes) -> VADEndpointResult:
        """Check voice activity via LocalAI /vad or /v1/vad before local LowCpuVAD fallback."""
        client, should_close = self._get_client()
        payload = {"model": self.vad_model, "sample_rate": 16000, "pcm_length": len(pcm_bytes)}
        try:
            for url in (f"{self.root_url}/vad", f"{self.v1_url}/vad"):
                try:
                    resp = client.post(url, headers=self._headers(), json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        segments = data.get("segments") or []
                        active = bool(data.get("is_speech", bool(segments)))
                        return VADEndpointResult(is_speech=active, provider="localai-vad", rms=0.0)
                    log_api_error("LocalAI-VAD", "POST", url, status_code=resp.status_code, detail=resp.text)
                except Exception as exc:
                    log_api_error("LocalAI-VAD", "POST", url, detail=str(exc))
        finally:
            if should_close:
                client.close()

        local_res = self._local_vad.process_frame(pcm_bytes)
        return VADEndpointResult(is_speech=local_res.is_speech, provider="local-lowcpu-vad", rms=local_res.rms)

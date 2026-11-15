"""Synthesized feedback beep engine for non-verbal user status cues."""

from __future__ import annotations

import io
import math
import struct
import time
import wave
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

ToneStep = Tuple[float, int]

BEEP_PROFILES: Dict[str, List[ToneStep]] = {
    "wake": [(523.25, 70), (659.25, 90)],
    "thinking": [(440.0, 60), (493.88, 60)],
    "success": [(523.25, 65), (659.25, 65), (783.99, 100)],
    "cancel": [(600.0, 65), (350.0, 95)],
    "security": [(300.0, 110), (0.0, 50), (300.0, 110)],
    "soundcheck": [(440.0, 80), (880.0, 80), (1320.0, 100)],
}


@dataclass
class SoundCueEvent:
    """Recorded feedback beep event for observability and UI streaming."""

    cue_name: str
    duration_ms: int
    frequencies_hz: List[float]
    timestamp: float = field(default_factory=time.time)
    byte_length: int = 0


def synthesize_wav_bytes(
    steps: List[ToneStep],
    sample_rate: int = 16000,
    amplitude: float = 0.35,
) -> bytes:
    """Synthesize a clean mono 16-bit PCM WAV buffer with soft attack/decay envelopes."""
    pcm_chunks: List[bytes] = []
    clamped_amp = max(0.0, min(1.0, amplitude))
    max_val = int(32767 * clamped_amp)

    for freq_hz, duration_ms in steps:
        n_samples = max(1, int(sample_rate * (duration_ms / 1000.0)))
        fade_samples = min(n_samples // 4, int(sample_rate * 0.008))
        samples: List[int] = []
        for idx in range(n_samples):
            if freq_hz <= 0.0:
                samples.append(0)
                continue
            envelope = 1.0
            if fade_samples > 0:
                if idx < fade_samples:
                    envelope = idx / fade_samples
                elif idx >= n_samples - fade_samples:
                    envelope = (n_samples - idx) / fade_samples
            val = math.sin(2.0 * math.pi * freq_hz * idx / sample_rate)
            samples.append(int(max_val * envelope * val))
        pcm_chunks.append(struct.pack(f"<{n_samples}h", *samples))

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"".join(pcm_chunks))
    return buf.getvalue()


class FeedbackSoundEngine:
    """Generates and plays audio cues for wake, thinking, cancel, security, and soundcheck."""

    def __init__(
        self,
        enabled: bool = True,
        hardware_playback: bool = False,
        playback_hook: Optional[Callable[[bytes, str], None]] = None,
    ) -> None:
        self.enabled = enabled
        self.hardware_playback = hardware_playback
        self._playback_hook = playback_hook
        self.history: List[SoundCueEvent] = []
        self._wav_cache: Dict[str, bytes] = {
            name: synthesize_wav_bytes(steps) for name, steps in BEEP_PROFILES.items()
        }

    def get_wav(self, cue_name: str) -> bytes:
        """Return synthesized WAV bytes for a configured cue name."""
        if cue_name not in self._wav_cache:
            steps = BEEP_PROFILES.get(cue_name, BEEP_PROFILES["wake"])
            self._wav_cache[cue_name] = synthesize_wav_bytes(steps)
        return self._wav_cache[cue_name]

    def play(self, cue_name: str) -> Optional[SoundCueEvent]:
        """Trigger a feedback cue, invoke optional playback hook, and record the event."""
        if not self.enabled:
            return None

        steps = BEEP_PROFILES.get(cue_name, BEEP_PROFILES["wake"])
        wav_bytes = self.get_wav(cue_name)
        event = SoundCueEvent(
            cue_name=cue_name,
            duration_ms=sum(dur for _, dur in steps),
            frequencies_hz=[freq for freq, _ in steps if freq > 0],
            byte_length=len(wav_bytes),
        )
        self.history.append(event)

        if self._playback_hook is not None:
            self._playback_hook(wav_bytes, cue_name)
        elif self.hardware_playback:
            self._play_windows_fallback(wav_bytes)

        return event

    @staticmethod
    def _play_windows_fallback(wav_bytes: bytes) -> None:
        """Play WAV bytes asynchronously via Windows winsound when enabled on Windows."""
        try:
            import winsound  # type: ignore

            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:
            pass


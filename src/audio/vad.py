"""Low-CPU Voice Activity Detection (VAD) and adaptive loop throttling."""

from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Tuple


class VADState(str, Enum):
    """Speech activity states tracked by LowCpuVAD."""

    SILENCE = "silence"
    SPEECH_START = "speech_start"
    SPEECH = "speech"
    SPEECH_END = "speech_end"


@dataclass
class VADFrameResult:
    """Result returned for each evaluated 16-bit PCM frame."""

    is_speech: bool
    state: VADState
    rms: float
    zcr: float
    noise_floor: float
    threshold: float


def compute_pcm_features(pcm_bytes: bytes) -> Tuple[float, float]:
    """Compute normalized RMS energy [0..1] and Zero-Crossing Rate [0..1] for 16-bit PCM."""
    sample_count = len(pcm_bytes) // 2
    if sample_count == 0:
        return 0.0, 0.0

    samples = struct.unpack(f"<{sample_count}h", pcm_bytes[: sample_count * 2])
    sum_squares = 0.0
    zero_crossings = 0
    prev = samples[0]

    for sample in samples:
        norm = sample / 32768.0
        sum_squares += norm * norm
        if (sample >= 0 > prev) or (sample < 0 <= prev):
            zero_crossings += 1
        prev = sample

    rms = math.sqrt(sum_squares / sample_count)
    zcr = zero_crossings / max(1, sample_count - 1)
    return rms, zcr


def generate_pcm_tone(
    frequency_hz: float,
    duration_ms: int,
    amplitude: float = 0.4,
    sample_rate: int = 16000,
) -> bytes:
    """Generate a mono 16-bit signed PCM sine wave frame for testing or calibration."""
    total_samples = max(1, int(sample_rate * (duration_ms / 1000.0)))
    clamped_amp = max(0.0, min(1.0, amplitude))
    scale = int(32767 * clamped_amp)
    step = 2.0 * math.pi * frequency_hz / sample_rate
    frames = [int(scale * math.sin(step * idx)) for idx in range(total_samples)]
    return struct.pack(f"<{total_samples}h", *frames)


class LowCpuVAD:
    """Lightweight adaptive energy + ZCR Voice Activity Detector (INV-02)."""

    def __init__(
        self,
        base_threshold: float = 0.025,
        noise_alpha: float = 0.08,
        hangover_frames: int = 4,
        min_speech_zcr: float = 0.005,
        max_speech_zcr: float = 0.45,
    ) -> None:
        self.base_threshold = base_threshold
        self.noise_alpha = noise_alpha
        self.hangover_frames = hangover_frames
        self.min_speech_zcr = min_speech_zcr
        self.max_speech_zcr = max_speech_zcr
        self._noise_floor = base_threshold * 0.5
        self._in_speech = False
        self._hangover_remaining = 0

    def reset(self) -> None:
        """Reset adaptive noise floor and active speech state."""
        self._noise_floor = self.base_threshold * 0.5
        self._in_speech = False
        self._hangover_remaining = 0

    def process_frame(self, pcm_bytes: bytes) -> VADFrameResult:
        """Evaluate one PCM frame and return speech classification without heavy DSP overhead."""
        rms, zcr = compute_pcm_features(pcm_bytes)
        adaptive_threshold = max(self.base_threshold, self._noise_floor * 2.2)

        energy_active = rms >= adaptive_threshold
        zcr_voice_like = self.min_speech_zcr <= zcr <= self.max_speech_zcr
        frame_speech = energy_active and (zcr_voice_like or rms >= adaptive_threshold * 1.8)

        if not frame_speech:
            self._noise_floor = (1.0 - self.noise_alpha) * self._noise_floor + self.noise_alpha * rms

        if frame_speech:
            self._hangover_remaining = self.hangover_frames
            if not self._in_speech:
                self._in_speech = True
                state = VADState.SPEECH_START
            else:
                state = VADState.SPEECH
        elif self._in_speech:
            if self._hangover_remaining > 0:
                self._hangover_remaining -= 1
                state = VADState.SPEECH
                frame_speech = True
            else:
                self._in_speech = False
                state = VADState.SPEECH_END
        else:
            state = VADState.SILENCE

        return VADFrameResult(
            is_speech=frame_speech,
            state=state,
            rms=round(rms, 5),
            zcr=round(zcr, 5),
            noise_floor=round(self._noise_floor, 5),
            threshold=round(adaptive_threshold, 5),
        )


class IdleLoopThrottle:
    """Enforces low-CPU sleep pacing during idle listening loops (INV-02)."""

    def __init__(
        self,
        idle_interval_ms: int = 40,
        active_interval_ms: int = 10,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.idle_interval_s = max(0.005, idle_interval_ms / 1000.0)
        self.active_interval_s = max(0.001, active_interval_ms / 1000.0)
        self._sleep_fn = sleep_fn
        self.total_sleeps = 0
        self.total_slept_seconds = 0.0

    def pace(self, speech_active: bool) -> float:
        """Yield CPU for an adaptive interval based on whether speech is currently active."""
        delay = self.active_interval_s if speech_active else self.idle_interval_s
        self._sleep_fn(delay)
        self.total_sleeps += 1
        self.total_slept_seconds += delay
        return delay


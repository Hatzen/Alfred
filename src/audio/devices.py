"""Smart microphone and output device selection with soundcheck probing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from src.audio.beeps import FeedbackSoundEngine
from src.audio.vad import compute_pcm_features, generate_pcm_tone


@dataclass
class AudioInputDevice:
    """Represents a microphone / audio capture endpoint."""

    device_id: str
    name: str
    is_available: bool = True
    is_muted: bool = False
    sample_rate: int = 16000
    noise_rms: float = 0.005
    probe_pcm: Optional[bytes] = None
    last_signal_rms: float = 0.0
    last_snr_db: float = 0.0


@dataclass
class AudioOutputDevice:
    """Represents a speaker / audio playback endpoint."""

    device_id: str
    name: str
    is_available: bool = True
    sample_rate: int = 16000
    can_open_stream: bool = True
    loopback_quality: float = 0.9
    last_soundcheck_score: float = 0.0


@dataclass
class SoundcheckResult:
    """Outcome of testing output speakers with the specific soundcheck tone."""

    selected_device_id: Optional[str]
    selected_device_name: Optional[str]
    score: float
    tested_devices: List[str] = field(default_factory=list)
    cue_played: str = "soundcheck"
    passed: bool = False


def _default_input_devices() -> List[AudioInputDevice]:
    """Provide default virtual/hardware probe candidates for smart mic selection."""
    return [
        AudioInputDevice(
            device_id="mic-desk-usb",
            name="USB Conference Microphone",
            is_available=True,
            is_muted=False,
            noise_rms=0.004,
            probe_pcm=generate_pcm_tone(240.0, 80, amplitude=0.28),
        ),
        AudioInputDevice(
            device_id="mic-webcam-idle",
            name="Webcam Built-in Mic (Idle)",
            is_available=True,
            is_muted=False,
            noise_rms=0.005,
            probe_pcm=generate_pcm_tone(60.0, 80, amplitude=0.003),
        ),
    ]


def _default_output_devices() -> List[AudioOutputDevice]:
    """Provide default speaker candidates for soundcheck calibration."""
    return [
        AudioOutputDevice(
            device_id="spk-hdmi-muted",
            name="Monitor HDMI Audio (Unplugged)",
            is_available=True,
            can_open_stream=False,
            loopback_quality=0.0,
        ),
        AudioOutputDevice(
            device_id="spk-desk-main",
            name="Desktop Main Speakers",
            is_available=True,
            can_open_stream=True,
            loopback_quality=0.95,
        ),
    ]


class AudioDeviceManager:
    """Configures and smart-selects active microphones and working output devices (INV-05)."""

    def __init__(
        self,
        sound_engine: Optional[FeedbackSoundEngine] = None,
        input_devices: Optional[List[AudioInputDevice]] = None,
        output_devices: Optional[List[AudioOutputDevice]] = None,
        smart_choice_enabled: bool = True,
        configured_input_id: Optional[str] = None,
        configured_output_id: Optional[str] = None,
        output_probe_fn: Optional[Callable[[AudioOutputDevice, bytes], float]] = None,
    ) -> None:
        self.sound_engine = sound_engine or FeedbackSoundEngine(enabled=True)
        self.input_devices: List[AudioInputDevice] = (
            list(input_devices) if input_devices is not None else _default_input_devices()
        )
        self.output_devices: List[AudioOutputDevice] = (
            list(output_devices) if output_devices is not None else _default_output_devices()
        )
        self.smart_choice_enabled = smart_choice_enabled
        self.active_input_id: Optional[str] = configured_input_id
        self.active_output_id: Optional[str] = configured_output_id
        self._output_probe_fn = output_probe_fn

    def set_input_device(self, device_id: str) -> AudioInputDevice:
        """Manually pin a specific microphone device by ID."""
        for dev in self.input_devices:
            if dev.device_id == device_id:
                self.active_input_id = device_id
                return dev
        raise ValueError(f"Unknown input device id: {device_id}")

    def set_output_device(self, device_id: str) -> AudioOutputDevice:
        """Manually pin a specific output device by ID."""
        for dev in self.output_devices:
            if dev.device_id == device_id:
                self.active_output_id = device_id
                return dev
        raise ValueError(f"Unknown output device id: {device_id}")

    def select_smart_microphone(self, min_active_rms: float = 0.02) -> Optional[AudioInputDevice]:
        """Select the available, unmuted microphone with the strongest active input signal."""
        candidates = [d for d in self.input_devices if d.is_available and not d.is_muted]
        if not candidates:
            self.active_input_id = None
            return None

        best_device: Optional[AudioInputDevice] = None
        best_score = -1.0

        for dev in candidates:
            rms = dev.last_signal_rms
            if dev.probe_pcm:
                rms, _ = compute_pcm_features(dev.probe_pcm)
            dev.last_signal_rms = round(rms, 5)
            noise = max(dev.noise_rms, 1e-5)
            snr = rms / noise
            dev.last_snr_db = round(snr, 2)

            active_bonus = 10.0 if rms >= min_active_rms else 0.0
            score = active_bonus + snr
            if score > best_score:
                best_score = score
                best_device = dev

        if best_device is not None:
            self.active_input_id = best_device.device_id
        return best_device

    def run_soundcheck(self) -> SoundcheckResult:
        """Send the specific soundcheck tone to candidate outputs and pick the best working one."""
        soundcheck_wav = self.sound_engine.get_wav("soundcheck")
        self.sound_engine.play("soundcheck")

        tested: List[str] = []
        best_dev: Optional[AudioOutputDevice] = None
        best_score = 0.0

        for dev in self.output_devices:
            if not dev.is_available:
                continue
            tested.append(dev.device_id)
            if self._output_probe_fn is not None:
                score = self._output_probe_fn(dev, soundcheck_wav)
            else:
                score = dev.loopback_quality if dev.can_open_stream else 0.0

            dev.last_soundcheck_score = round(score, 3)
            if score > best_score:
                best_score = score
                best_dev = dev

        if best_dev is not None:
            self.active_output_id = best_dev.device_id
            return SoundcheckResult(
                selected_device_id=best_dev.device_id,
                selected_device_name=best_dev.name,
                score=best_dev.last_soundcheck_score,
                tested_devices=tested,
                passed=True,
            )

        return SoundcheckResult(
            selected_device_id=self.active_output_id,
            selected_device_name=None,
            score=0.0,
            tested_devices=tested,
            passed=False,
        )

    def select_smart_output_device(self) -> SoundcheckResult:
        """Smart-select the best working output device via soundcheck."""
        return self.run_soundcheck()

    def snapshot(self) -> dict:
        """Return serializable device status for API telemetry."""
        return {
            "smart_choice_enabled": self.smart_choice_enabled,
            "active_input_id": self.active_input_id,
            "active_output_id": self.active_output_id,
            "inputs": [
                {
                    "device_id": d.device_id,
                    "name": d.name,
                    "is_available": d.is_available,
                    "is_muted": d.is_muted,
                    "last_signal_rms": d.last_signal_rms,
                    "last_snr_db": d.last_snr_db,
                }
                for d in self.input_devices
            ],
            "outputs": [
                {
                    "device_id": d.device_id,
                    "name": d.name,
                    "is_available": d.is_available,
                    "can_open_stream": d.can_open_stream,
                    "last_soundcheck_score": d.last_soundcheck_score,
                }
                for d in self.output_devices
            ],
        }


"""Smart microphone and output device selection with soundcheck probing."""

from __future__ import annotations

import ctypes
import io
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
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
    winmm_index: Optional[int] = None
    alsa_device: Optional[str] = None
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
    winmm_index: Optional[int] = None
    alsa_device: Optional[str] = None
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


class _WAVEINCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.c_uint16),
        ("wPid", ctypes.c_uint16),
        ("vDriverVersion", ctypes.c_uint32),
        ("szPname", ctypes.c_wchar * 32),
        ("dwFormats", ctypes.c_uint32),
        ("wChannels", ctypes.c_uint16),
        ("wReserved1", ctypes.c_uint16),
    ]


class _WAVEOUTCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.c_uint16),
        ("wPid", ctypes.c_uint16),
        ("vDriverVersion", ctypes.c_uint32),
        ("szPname", ctypes.c_wchar * 32),
        ("dwFormats", ctypes.c_uint32),
        ("wChannels", ctypes.c_uint16),
        ("wReserved1", ctypes.c_uint16),
        ("dwSupport", ctypes.c_uint32),
    ]


class _WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", ctypes.c_uint16),
        ("nChannels", ctypes.c_uint16),
        ("nSamplesPerSec", ctypes.c_uint32),
        ("nAvgBytesPerSec", ctypes.c_uint32),
        ("nBlockAlign", ctypes.c_uint16),
        ("wBitsPerSample", ctypes.c_uint16),
        ("cbSize", ctypes.c_uint16),
    ]


class _WAVEHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_char_p),
        ("dwBufferLength", ctypes.c_uint32),
        ("dwBytesRecorded", ctypes.c_uint32),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", ctypes.c_uint32),
        ("dwLoops", ctypes.c_uint32),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


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


_ALSA_LINE_RE = re.compile(
    r"(?:card|karte)\s+(?P<card>\d+):\s*[^\[]*\[(?P<card_name>[^\]]+)\],\s*(?:device|gerät|geraet)\s+(?P<dev>\d+):\s*[^\[]*\[(?P<dev_name>[^\]]+)\]",
    re.IGNORECASE,
)

_PREFERRED_INPUT_KEYWORDS = (
    "konftel",
    "ego",
    "conference",
    "speakerphone",
    "jabra",
    "poly",
    "yealink",
    "headset",
    "usb",
)

_PREFERRED_OUTPUT_KEYWORDS = (
    "konftel",
    "ego",
    "conference",
    "speakerphone",
    "jabra",
)


def _matches_keywords(name: str, keywords: tuple) -> bool:
    lowered = (name or "").lower()
    return any(kw in lowered for kw in keywords)


def pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap raw mono 16-bit little-endian PCM frames in a standard RIFF WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def _parse_alsa_list(output: str) -> List[tuple]:
    """Parse `arecord -l` / `aplay -l` output into (alsa_hw_id, friendly_name) tuples."""
    results: List[tuple] = []
    for line in output.splitlines():
        match = _ALSA_LINE_RE.search(line)
        if match:
            hw_id = f"plughw:{match.group('card')},{match.group('dev')}"
            name = f"{match.group('card_name').strip()} - {match.group('dev_name').strip()}"
            results.append((hw_id, name))
    return results


def _read_proc_asound_cards() -> List[tuple]:
    """Read /proc/asound/cards on Linux as an ALSA fallback when arecord/aplay are absent."""
    cards_path = Path("/proc/asound/cards")
    if not cards_path.is_file():
        return []
    results: List[tuple] = []
    for line in cards_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"^\s*(\d+)\s+\[[^\]]+\]:\s*(.+)$", line)
        if match:
            results.append((f"plughw:{match.group(1)},0", match.group(2).strip()))
    return results


def _discover_linux_input_devices() -> List[AudioInputDevice]:
    """Discover ALSA capture devices on Linux hosts (e.g. NVIDIA Spark)."""
    entries: List[tuple] = []
    if shutil.which("arecord"):
        try:
            env = {**os.environ, "LC_ALL": "C"}
            proc = subprocess.run(
                ["arecord", "-l"], capture_output=True, text=True, timeout=2.0, check=False, env=env
            )
            entries = _parse_alsa_list(proc.stdout)
        except Exception:
            entries = []
    if not entries:
        entries = _read_proc_asound_cards()
    return [
        AudioInputDevice(
            device_id=f"alsa-in-{idx}",
            name=name,
            is_available=True,
            is_muted=False,
            alsa_device=hw_id,
        )
        for idx, (hw_id, name) in enumerate(entries)
    ]


def _discover_linux_output_devices() -> List[AudioOutputDevice]:
    """Discover ALSA playback devices on Linux hosts (e.g. NVIDIA Spark)."""
    entries: List[tuple] = []
    if shutil.which("aplay"):
        try:
            env = {**os.environ, "LC_ALL": "C"}
            proc = subprocess.run(
                ["aplay", "-l"], capture_output=True, text=True, timeout=2.0, check=False, env=env
            )
            entries = _parse_alsa_list(proc.stdout)
        except Exception:
            entries = []
    if not entries:
        entries = _read_proc_asound_cards()
    return [
        AudioOutputDevice(
            device_id=f"alsa-out-{idx}",
            name=name,
            is_available=True,
            can_open_stream=True,
            loopback_quality=round(max(0.1, 0.95 - idx * 0.02), 3),
            alsa_device=hw_id,
        )
        for idx, (hw_id, name) in enumerate(entries)
    ]


def capture_alsa_pcm(
    alsa_device: str,
    duration_ms: int = 80,
    sample_rate: int = 16000,
) -> Optional[bytes]:
    """Capture a short mono 16-bit PCM snippet from an ALSA microphone via arecord."""
    if not sys.platform.startswith("linux") or not shutil.which("arecord"):
        return None
    seconds = max(1, int(round(duration_ms / 1000.0)))
    try:
        proc = subprocess.run(
            [
                "arecord",
                "-q",
                "-D",
                alsa_device,
                "-f",
                "S16_LE",
                "-r",
                str(sample_rate),
                "-c",
                "1",
                "-d",
                str(seconds),
                "-t",
                "raw",
            ],
            capture_output=True,
            timeout=seconds + 1.5,
            check=False,
        )
        return proc.stdout if proc.returncode == 0 and proc.stdout else None
    except Exception:
        return None


def discover_host_input_devices() -> List[AudioInputDevice]:
    """Discover physical microphones on Windows (winmm) or Linux (ALSA), falling back safely."""
    if sys.platform.startswith("linux"):
        return _discover_linux_input_devices() or _default_input_devices()
    if sys.platform != "win32":
        return _default_input_devices()
    try:
        winmm = ctypes.windll.winmm
        count = int(winmm.waveInGetNumDevs())
        devices: List[AudioInputDevice] = []
        for idx in range(count):
            caps = _WAVEINCAPSW()
            if winmm.waveInGetDevCapsW(idx, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                devices.append(
                    AudioInputDevice(
                        device_id=f"winmm-in-{idx}",
                        name=caps.szPname.strip() or f"Windows Input {idx}",
                        is_available=True,
                        is_muted=False,
                        winmm_index=idx,
                    )
                )
        return devices or _default_input_devices()
    except Exception:
        return _default_input_devices()


def discover_host_output_devices() -> List[AudioOutputDevice]:
    """Discover physical output speakers on Windows (winmm) or Linux (ALSA)."""
    if sys.platform.startswith("linux"):
        return _discover_linux_output_devices() or _default_output_devices()
    if sys.platform != "win32":
        return _default_output_devices()
    try:
        winmm = ctypes.windll.winmm
        count = int(winmm.waveOutGetNumDevs())
        wfx = _WAVEFORMATEX(1, 1, 16000, 32000, 2, 16, 0)
        devices: List[AudioOutputDevice] = []
        for idx in range(count):
            caps = _WAVEOUTCAPSW()
            if winmm.waveOutGetDevCapsW(idx, ctypes.byref(caps), ctypes.sizeof(caps)) != 0:
                continue
            h_out = ctypes.c_void_p()
            can_open = winmm.waveOutOpen(ctypes.byref(h_out), idx, ctypes.byref(wfx), 0, 0, 0) == 0
            if can_open:
                winmm.waveOutClose(h_out)
            quality = round(max(0.1, 0.95 - idx * 0.02), 3) if can_open else 0.0
            devices.append(
                AudioOutputDevice(
                    device_id=f"winmm-out-{idx}",
                    name=caps.szPname.strip() or f"Windows Output {idx}",
                    is_available=True,
                    can_open_stream=can_open,
                    loopback_quality=quality,
                    winmm_index=idx,
                )
            )
        return devices or _default_output_devices()
    except Exception:
        return _default_output_devices()


def capture_winmm_pcm(
    device_index: int,
    duration_ms: int = 80,
    sample_rate: int = 16000,
) -> Optional[bytes]:
    """Capture a short mono 16-bit PCM buffer from a Windows microphone for probing."""
    if sys.platform != "win32":
        return None
    winmm = ctypes.windll.winmm
    byte_len = max(320, int(sample_rate * (duration_ms / 1000.0)) * 2)
    wfx = _WAVEFORMATEX(1, 1, sample_rate, sample_rate * 2, 2, 16, 0)
    h_in = ctypes.c_void_p()
    if winmm.waveInOpen(ctypes.byref(h_in), device_index, ctypes.byref(wfx), 0, 0, 0) != 0:
        return None

    buf = ctypes.create_string_buffer(byte_len)
    hdr = _WAVEHDR(ctypes.cast(buf, ctypes.c_char_p), byte_len, 0, 0, 0, 0, None, 0)
    prepared = False
    try:
        if winmm.waveInPrepareHeader(h_in, ctypes.byref(hdr), ctypes.sizeof(hdr)) != 0:
            return None
        prepared = True
        if winmm.waveInAddBuffer(h_in, ctypes.byref(hdr), ctypes.sizeof(hdr)) != 0:
            return None
        if winmm.waveInStart(h_in) != 0:
            return None
        time.sleep(duration_ms / 1000.0 + 0.02)
        winmm.waveInStop(h_in)
        winmm.waveInReset(h_in)
        recorded = int(hdr.dwBytesRecorded)
        return bytes(buf.raw[:recorded]) if recorded > 0 else None
    except Exception:
        return None
    finally:
        if prepared:
            winmm.waveInUnprepareHeader(h_in, ctypes.byref(hdr), ctypes.sizeof(hdr))
        winmm.waveInClose(h_in)


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
        simulation_mode: bool = True,
    ) -> None:
        self.sound_engine = sound_engine or FeedbackSoundEngine(enabled=True)
        self.simulation_mode = simulation_mode
        self._custom_inputs_injected = input_devices is not None
        self._custom_outputs_injected = output_devices is not None
        if input_devices is not None:
            self.input_devices = list(input_devices)
        elif simulation_mode:
            self.input_devices = _default_input_devices()
        else:
            self.input_devices = discover_host_input_devices()

        if output_devices is not None:
            self.output_devices = list(output_devices)
        elif simulation_mode:
            self.output_devices = _default_output_devices()
        else:
            self.output_devices = discover_host_output_devices()

        self.smart_choice_enabled = smart_choice_enabled
        self.active_input_id: Optional[str] = configured_input_id
        self.active_output_id: Optional[str] = configured_output_id
        self._output_probe_fn = output_probe_fn

    def refresh_devices(self) -> None:
        """Re-scan host audio endpoints so newly plugged USB mics/speakers appear."""
        if self.simulation_mode:
            return
        if not self._custom_inputs_injected:
            self.input_devices = discover_host_input_devices()
            if self.active_input_id and not any(d.device_id == self.active_input_id for d in self.input_devices):
                self.active_input_id = None
        if not self._custom_outputs_injected:
            self.output_devices = discover_host_output_devices()
            if self.active_output_id and not any(d.device_id == self.active_output_id for d in self.output_devices):
                self.active_output_id = None

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
            pcm = dev.probe_pcm
            if pcm is None and dev.winmm_index is not None:
                pcm = capture_winmm_pcm(dev.winmm_index, duration_ms=60, sample_rate=dev.sample_rate)
            elif pcm is None and dev.alsa_device is not None:
                pcm = capture_alsa_pcm(dev.alsa_device, duration_ms=80, sample_rate=dev.sample_rate)
            if pcm:
                rms, _ = compute_pcm_features(pcm)
            dev.last_signal_rms = round(rms, 5)
            noise = max(dev.noise_rms, 1e-5)
            snr = rms / noise
            dev.last_snr_db = round(snr, 2)

            active_bonus = 10.0 if rms >= min_active_rms else 0.0
            preferred_hw_bonus = 3.0 if _matches_keywords(dev.name, _PREFERRED_INPUT_KEYWORDS) else 0.0
            score = active_bonus + preferred_hw_bonus + snr
            if score > best_score:
                best_score = score
                best_device = dev

        if best_device is not None:
            self.active_input_id = best_device.device_id
        return best_device

    def record_active_microphone_wav(self, duration_ms: int = 3000) -> Optional[bytes]:
        """Record mono 16kHz 16-bit WAV audio from the active host microphone."""
        dev = next((d for d in self.input_devices if d.device_id == self.active_input_id), None)
        if dev is None:
            dev = self.select_smart_microphone()
        if dev is None:
            return None

        if self.simulation_mode:
            pcm = dev.probe_pcm or generate_pcm_tone(280.0, min(duration_ms, 250), amplitude=0.25)
            return pcm_to_wav_bytes(pcm, sample_rate=dev.sample_rate)

        pcm: Optional[bytes] = None
        if dev.winmm_index is not None:
            pcm = capture_winmm_pcm(dev.winmm_index, duration_ms=duration_ms, sample_rate=dev.sample_rate)
        elif dev.alsa_device is not None:
            pcm = capture_alsa_pcm(dev.alsa_device, duration_ms=duration_ms, sample_rate=dev.sample_rate)
        elif dev.probe_pcm is not None:
            pcm = dev.probe_pcm

        return pcm_to_wav_bytes(pcm, sample_rate=dev.sample_rate) if pcm else None

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
                base = dev.loopback_quality if dev.can_open_stream else 0.0
                bonus = 0.05 if (dev.can_open_stream and _matches_keywords(dev.name, _PREFERRED_OUTPUT_KEYWORDS)) else 0.0
                score = min(1.0, base + bonus)

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
            "simulation_mode": self.simulation_mode,
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

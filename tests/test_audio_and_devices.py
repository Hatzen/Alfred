"""Tests for Low-CPU VAD, synthesized feedback beeps, and smart audio device selection."""

from __future__ import annotations

import io
import wave

from src.audio.beeps import BEEP_PROFILES, FeedbackSoundEngine
from src.audio.devices import AudioDeviceManager, AudioInputDevice, AudioOutputDevice
from src.audio.vad import IdleLoopThrottle, LowCpuVAD, VADState, generate_pcm_tone


def test_low_cpu_vad_distinguishes_silence_and_speech() -> None:
    vad = LowCpuVAD(base_threshold=0.03, hangover_frames=1)
    silence = bytes(640)  # 320 samples of zero PCM
    speech = generate_pcm_tone(frequency_hz=280.0, duration_ms=20, amplitude=0.35)

    res_quiet = vad.process_frame(silence)
    assert not res_quiet.is_speech
    assert res_quiet.state == VADState.SILENCE

    res_start = vad.process_frame(speech)
    assert res_start.is_speech
    assert res_start.state == VADState.SPEECH_START

    res_cont = vad.process_frame(speech)
    assert res_cont.is_speech
    assert res_cont.state == VADState.SPEECH

    # Hangover holds 1 frame, then ends speech cleanly
    _ = vad.process_frame(silence)
    res_end = vad.process_frame(silence)
    assert not res_end.is_speech
    assert res_end.state == VADState.SPEECH_END


def test_idle_loop_throttle_sleeps_appropriately_without_cpu_spin() -> None:
    recorded_sleeps = []
    throttle = IdleLoopThrottle(
        idle_interval_ms=45,
        active_interval_ms=10,
        sleep_fn=recorded_sleeps.append,
    )

    throttle.pace(speech_active=False)
    throttle.pace(speech_active=False)
    throttle.pace(speech_active=True)

    assert recorded_sleeps == [0.045, 0.045, 0.010]
    assert throttle.total_sleeps == 3
    assert round(throttle.total_slept_seconds, 3) == 0.100


def test_feedback_sound_engine_synthesizes_valid_wav_cues() -> None:
    played_cues = []
    engine = FeedbackSoundEngine(
        enabled=True,
        playback_hook=lambda wav_bytes, name: played_cues.append((name, len(wav_bytes))),
    )

    for cue in BEEP_PROFILES:
        event = engine.play(cue)
        assert event is not None
        assert event.cue_name == cue
        wav_data = engine.get_wav(cue)
        assert wav_data[:4] == b"RIFF"

        with wave.open(io.BytesIO(wav_data), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() > 0

    assert len(played_cues) == len(BEEP_PROFILES)


def test_smart_microphone_picks_actively_receiving_unmuted_mic() -> None:
    muted_loud = AudioInputDevice(
        device_id="mic-muted",
        name="Muted Studio Mic",
        is_available=True,
        is_muted=True,
        probe_pcm=generate_pcm_tone(300.0, 40, amplitude=0.8),
    )
    idle_quiet = AudioInputDevice(
        device_id="mic-quiet",
        name="Silent Built-in Mic",
        is_available=True,
        is_muted=False,
        noise_rms=0.01,
        probe_pcm=generate_pcm_tone(60.0, 40, amplitude=0.002),
    )
    active_voice = AudioInputDevice(
        device_id="mic-active",
        name="Active Headset Mic",
        is_available=True,
        is_muted=False,
        noise_rms=0.004,
        probe_pcm=generate_pcm_tone(250.0, 40, amplitude=0.35),
    )

    mgr = AudioDeviceManager(input_devices=[muted_loud, idle_quiet, active_voice])
    chosen = mgr.select_smart_microphone()

    assert chosen is not None
    assert chosen.device_id == "mic-active"
    assert mgr.active_input_id == "mic-active"


def test_smart_output_soundcheck_selects_working_speaker_and_plays_sweep() -> None:
    sound_engine = FeedbackSoundEngine(enabled=True)
    broken = AudioOutputDevice(
        device_id="spk-broken",
        name="Broken HDMI",
        can_open_stream=False,
        loopback_quality=0.0,
    )
    weak = AudioOutputDevice(
        device_id="spk-weak",
        name="Weak Monitor",
        can_open_stream=True,
        loopback_quality=0.45,
    )
    best = AudioOutputDevice(
        device_id="spk-best",
        name="Main Desk Speakers",
        can_open_stream=True,
        loopback_quality=0.98,
    )

    mgr = AudioDeviceManager(
        sound_engine=sound_engine,
        output_devices=[broken, weak, best],
    )
    result = mgr.run_soundcheck()

    assert result.passed is True
    assert result.selected_device_id == "spk-best"
    assert mgr.active_output_id == "spk-best"
    assert sound_engine.history[-1].cue_name == "soundcheck"


"""Tests for instant barge-in interruption ('stop' / 'forget it') during thinking and speaking."""

from __future__ import annotations

from src.audio.beeps import FeedbackSoundEngine
from src.interrupt.controller import AssistantState, InterruptController


def test_trigger_interrupt_cancels_session_and_plays_cancel_beep() -> None:
    sound_engine = FeedbackSoundEngine(enabled=True)
    controller = InterruptController(sound_engine=sound_engine)

    session = controller.begin_session(AssistantState.THINKING)
    assert controller.state == AssistantState.THINKING
    assert not session.is_cancelled()

    event = controller.trigger_interrupt(reason="phrase:stop")
    assert session.is_cancelled()
    assert event.previous_state == AssistantState.THINKING
    assert controller.state == AssistantState.IDLE
    assert sound_engine.history[-1].cue_name == "cancel"


def test_mid_speech_interrupt_drops_remaining_tts_chunks_immediately() -> None:
    sound_engine = FeedbackSoundEngine(enabled=True)
    controller = InterruptController(sound_engine=sound_engine)
    session = controller.begin_session(AssistantState.SPEAKING)

    spoken = []

    def emit_chunk(chunk: str) -> None:
        spoken.append(chunk)
        # Simulate user saying "forget it" right after hearing the first sentence
        if len(spoken) == 1:
            controller.trigger_interrupt(reason="phrase:forget it")

    long_answer = (
        "First sentence starts speaking now. "
        "Second sentence should immediately be dropped. "
        "Third sentence must never be spoken."
    )
    emitted = controller.stream_tts_chunks(long_answer, session=session, emit_fn=emit_chunk)

    assert len(emitted) == 1
    assert emitted[0] == "First sentence starts speaking now."
    assert controller.outbound_tts_queue == []
    assert controller.state == AssistantState.IDLE
    assert sound_engine.history[-1].cue_name == "cancel"


"""Tests for configurable wake-word filtering and follow-up window gating."""

from __future__ import annotations

from src.wakeword.detector import CommandFilter


def test_configurable_wake_names_accept_and_strip_command() -> None:
    filt = CommandFilter(
        wake_words=["Hey Alfred", "Hey Alexa", "Hey Google"],
        interrupt_phrases=["stop", "forget it"],
    )

    res1 = filt.evaluate("Hey Alfred, wie wird das Wetter?")
    assert res1.accepted is True
    assert res1.matched_wake_word == "hey alfred"
    assert res1.command_text == "wie wird das Wetter?"

    res2 = filt.evaluate("Hey Alexa tell me a joke")
    assert res2.accepted is True
    assert res2.matched_wake_word == "hey alexa"
    assert res2.command_text == "tell me a joke"

    res3 = filt.evaluate("Hey Google was ist Python?")
    assert res3.accepted is True
    assert res3.matched_wake_word == "hey google"
    assert res3.command_text == "was ist Python?"

    # Does not strip trailing wake word from assignment value when wake word isn't required
    filt_with_bare = CommandFilter(
        wake_words=["Hey Alfred", "Alfred"],
        interrupt_phrases=["stop"],
    )
    direct = filt_with_bare.evaluate("Merke dir: Projekt = Alfred", require_wake_word=False)
    assert direct.accepted is True
    assert direct.command_text == "Merke dir: Projekt = Alfred"

    vocative = filt_with_bare.evaluate("Wie spät ist es, Alfred?", require_wake_word=True)
    assert vocative.accepted is True
    assert vocative.command_text == "Wie spät ist es"


def test_non_wake_background_chatter_is_ignored_when_required() -> None:
    filt = CommandFilter(
        wake_words=["Hey Alfred", "Hey Alexa"],
        interrupt_phrases=["stop", "forget it"],
    )

    ignored = filt.evaluate("just talking in the room about dinner", require_wake_word=True)
    assert ignored.accepted is False
    assert ignored.is_interrupt is False
    assert ignored.command_text == ""


def test_interrupt_bypasses_wake_word_requirement() -> None:
    filt = CommandFilter(
        wake_words=["Hey Alfred"],
        interrupt_phrases=["stop", "forget it", "stopp", "vergiss es"],
    )

    for phrase in ("stop", "Forget it!", "stopp", "vergiss es"):
        decision = filt.evaluate(phrase, require_wake_word=True)
        assert decision.accepted is True
        assert decision.is_interrupt is True
        assert decision.matched_interrupt_phrase is not None


def test_follow_up_window_allows_reply_without_repeating_wake_word() -> None:
    fake_clock = [100.0]
    filt = CommandFilter(
        wake_words=["Hey Alfred"],
        interrupt_phrases=["stop"],
        follow_up_window_seconds=10.0,
        clock_fn=lambda: fake_clock[0],
    )

    assert not filt.evaluate("NilpferdOne", require_wake_word=True).accepted

    filt.open_follow_up_window()
    inside = filt.evaluate("NilpferdOne", require_wake_word=True)
    assert inside.accepted is True
    assert inside.via_follow_up is True

    fake_clock[0] = 112.0
    expired = filt.evaluate("NilpferdOne", require_wake_word=True)
    assert expired.accepted is False

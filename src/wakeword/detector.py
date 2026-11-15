"""Configurable wake-word command filter with Priority-0 interrupt recognition."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass
class FilterDecision:
    """Outcome of filtering an utterance against interrupt and wake-word rules."""

    accepted: bool
    is_interrupt: bool
    matched_wake_word: Optional[str]
    matched_interrupt_phrase: Optional[str]
    command_text: str
    via_follow_up: bool = False


class CommandFilter:
    """Filters utterances so heavy tasks only execute when Alfred is addressed (INV-02)."""

    def __init__(
        self,
        wake_words: Iterable[str],
        interrupt_phrases: Iterable[str],
        follow_up_window_seconds: float = 15.0,
        clock_fn=time.monotonic,
    ) -> None:
        self.wake_words: List[str] = self._sort_longest_first(wake_words)
        self.interrupt_phrases: List[str] = self._sort_longest_first(interrupt_phrases)
        self.follow_up_window_seconds = max(0.0, follow_up_window_seconds)
        self._clock_fn = clock_fn
        self._follow_up_until: float = 0.0

    @staticmethod
    def _sort_longest_first(phrases: Iterable[str]) -> List[str]:
        cleaned = {p.strip().lower() for p in phrases if p and p.strip()}
        return sorted(cleaned, key=len, reverse=True)

    def update_wake_words(self, wake_words: Iterable[str]) -> None:
        """Replace configured wake words dynamically."""
        self.wake_words = self._sort_longest_first(wake_words)

    def open_follow_up_window(self, seconds: Optional[float] = None) -> None:
        """Allow the next utterance within the window without repeating a wake word."""
        duration = self.follow_up_window_seconds if seconds is None else max(0.0, seconds)
        self._follow_up_until = self._clock_fn() + duration

    def close_follow_up_window(self) -> None:
        """Close any active follow-up grace period."""
        self._follow_up_until = 0.0

    def in_follow_up_window(self) -> bool:
        """Return True if a follow-up window is currently active."""
        return self._clock_fn() < self._follow_up_until

    def match_interrupt(self, text: str) -> Optional[str]:
        """Return the matched interrupt phrase if text is a stop/forget-it command."""
        normalized = " ".join(text.strip().lower().split())
        if not normalized:
            return None

        for phrase in self.interrupt_phrases:
            pattern = rf"(?:^|\b){re.escape(phrase)}(?:\b|$|[!.,?])"
            if re.search(pattern, normalized):
                return phrase
        return None

    def extract_wake_command(
        self, text: str, *, allow_mid_utterance: bool = True
    ) -> Optional[tuple]:
        """Match a configured wake name and return (wake_word, stripped_command) if present."""
        raw = text.strip()
        if not raw:
            return None

        for wake in self.wake_words:
            # 1. Leading wake phrase: "Hey Alfred, ..." or "Alfred: ..."
            lead_match = re.match(
                rf"^{re.escape(wake)}(?:[\s,:;!?.-]+(.*)|$)",
                raw,
                flags=re.IGNORECASE,
            )
            if lead_match:
                return wake, (lead_match.group(1) or "").strip()

            if not allow_mid_utterance:
                continue

            # 2. Multi-word wake phrases ("hey alfred", "hey alexa") anywhere in utterance
            if " " in wake:
                mid_match = re.search(
                    rf"(?:^|\s){re.escape(wake)}(?:[\s,:;!?.-]+(.*)|$)",
                    raw,
                    flags=re.IGNORECASE,
                )
                if mid_match:
                    prefix = raw[: mid_match.start()].strip()
                    remainder = (mid_match.group(1) or "").strip()
                    return wake, remainder if remainder else prefix

            # 3. Single-word trailing vocative after comma: "Wie spät ist es, Alfred?"
            trail_match = re.match(
                rf"^(.*),\s*{re.escape(wake)}[.!?]*$",
                raw,
                flags=re.IGNORECASE,
            )
            if trail_match:
                return wake, trail_match.group(1).strip()

        return None

    def evaluate(self, text: str, require_wake_word: bool = True) -> FilterDecision:
        """Classify utterance into interrupt, addressed command, follow-up, or ignored noise."""
        clean_text = text.strip()
        interrupt_hit = self.match_interrupt(clean_text)
        if interrupt_hit is not None:
            self.close_follow_up_window()
            return FilterDecision(
                accepted=True,
                is_interrupt=True,
                matched_wake_word=None,
                matched_interrupt_phrase=interrupt_hit,
                command_text=clean_text,
            )

        wake_match = self.extract_wake_command(
            clean_text, allow_mid_utterance=require_wake_word
        )
        if wake_match is not None:
            wake_word, command_text = wake_match
            return FilterDecision(
                accepted=True,
                is_interrupt=False,
                matched_wake_word=wake_word,
                matched_interrupt_phrase=None,
                command_text=command_text,
            )

        if not require_wake_word:
            return FilterDecision(
                accepted=bool(clean_text),
                is_interrupt=False,
                matched_wake_word=None,
                matched_interrupt_phrase=None,
                command_text=clean_text,
            )

        if self.in_follow_up_window() and clean_text:
            return FilterDecision(
                accepted=True,
                is_interrupt=False,
                matched_wake_word=None,
                matched_interrupt_phrase=None,
                command_text=clean_text,
                via_follow_up=True,
            )

        return FilterDecision(
            accepted=False,
            is_interrupt=False,
            matched_wake_word=None,
            matched_interrupt_phrase=None,
            command_text="",
        )

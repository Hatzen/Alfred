"""Preemptive interrupt controller for instant answer & TTS output cancellation."""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

from src.audio.beeps import FeedbackSoundEngine


class AssistantState(str, Enum):
    """Lifecycle states of the Alfred daemon."""

    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass
class InterruptEvent:
    """Recorded barge-in event for diagnostics and UI updates."""

    reason: str
    previous_state: AssistantState
    session_id: Optional[str]
    dropped_chunks: int
    timestamp: float = field(default_factory=time.time)


class GenerationSession:
    """Cancellation token tied to one assistant generation and speech output cycle."""

    def __init__(self, session_id: Optional[str] = None) -> None:
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self._cancel_event = threading.Event()
        self.started_at = time.time()

    def cancel(self) -> None:
        """Mark this session as immediately cancelled."""
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        """Return True if an interrupt has cancelled this session."""
        return self._cancel_event.is_set()


def split_speech_chunks(text: str) -> List[str]:
    """Split spoken output into sentence/clause chunks for responsive mid-speech interruption."""
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return []
    raw_parts = re.split(r"(?<=[.!?;:])\s+", cleaned)
    chunks: List[str] = []
    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= 90:
            chunks.append(part)
        else:
            # Break long clauses on commas or word spans so stop takes effect rapidly.
            words = part.split(" ")
            current: List[str] = []
            for word in words:
                current.append(word)
                if len(" ".join(current)) >= 60:
                    chunks.append(" ".join(current))
                    current = []
            if current:
                chunks.append(" ".join(current))
    return chunks


class InterruptController:
    """Coordinates instant cancellation of LLM generation and spoken TTS output (INV-01)."""

    def __init__(self, sound_engine: Optional[FeedbackSoundEngine] = None) -> None:
        self.sound_engine = sound_engine or FeedbackSoundEngine(enabled=True)
        self._lock = threading.Lock()
        self.state: AssistantState = AssistantState.IDLE
        self.active_session: Optional[GenerationSession] = None
        self.outbound_tts_queue: List[str] = []
        self.spoken_chunks: List[str] = []
        self.interrupt_history: List[InterruptEvent] = []

    def begin_session(self, initial_state: AssistantState = AssistantState.THINKING) -> GenerationSession:
        """Start a new generation session, cancelling any stale session cleanly."""
        with self._lock:
            if self.active_session is not None and not self.active_session.is_cancelled():
                self.active_session.cancel()
            session = GenerationSession()
            self.active_session = session
            self.outbound_tts_queue.clear()
            self.spoken_chunks.clear()
            self.state = initial_state
            return session

    def set_state(self, state: AssistantState, session: Optional[GenerationSession] = None) -> None:
        """Update assistant state only if the given session has not been cancelled."""
        with self._lock:
            if session is not None and session.is_cancelled():
                return
            self.state = state

    def finish_session(self, session: GenerationSession) -> None:
        """Return daemon state to IDLE when a session finishes naturally."""
        with self._lock:
            if self.active_session is session:
                self.state = AssistantState.IDLE

    def trigger_interrupt(self, reason: str = "user_interrupt") -> InterruptEvent:
        """Immediately abort active generation, drop pending TTS chunks, and beep (INV-01)."""
        with self._lock:
            prev_state = self.state
            session_id = self.active_session.session_id if self.active_session else None
            if self.active_session is not None:
                self.active_session.cancel()
            dropped = len(self.outbound_tts_queue)
            self.outbound_tts_queue.clear()
            self.state = AssistantState.IDLE

        event = InterruptEvent(
            reason=reason,
            previous_state=prev_state,
            session_id=session_id,
            dropped_chunks=dropped,
        )
        self.interrupt_history.append(event)
        self.sound_engine.play("cancel")
        return event

    def stream_tts_chunks(
        self,
        text: str,
        session: GenerationSession,
        emit_fn: Optional[Callable[[str], None]] = None,
    ) -> List[str]:
        """Emit TTS chunks one by one, halting immediately if the session is cancelled."""
        chunks = split_speech_chunks(text)
        with self._lock:
            if session.is_cancelled():
                return []
            self.outbound_tts_queue = list(chunks)
            self.state = AssistantState.SPEAKING

        emitted: List[str] = []
        while True:
            if session.is_cancelled():
                with self._lock:
                    self.outbound_tts_queue.clear()
                    self.state = AssistantState.IDLE
                break

            with self._lock:
                if not self.outbound_tts_queue:
                    self.state = AssistantState.IDLE
                    break
                chunk = self.outbound_tts_queue.pop(0)

            if session.is_cancelled():
                with self._lock:
                    self.outbound_tts_queue.clear()
                    self.state = AssistantState.IDLE
                break

            if emit_fn is not None:
                emit_fn(chunk)
            emitted.append(chunk)
            with self._lock:
                self.spoken_chunks.append(chunk)

        return emitted


"""Core Alfred AI Assistant orchestrator connecting audio, security, memory, and integrations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.audio.beeps import FeedbackSoundEngine
from src.audio.devices import AudioDeviceManager
from src.audio.vad import IdleLoopThrottle, LowCpuVAD, VADFrameResult
from src.config import AlfredConfig
from src.i18n.locales import detect_language, get_message, normalize_language
from src.integrations.fancytanky import FancyTankyConnector
from src.integrations.hermes import HermesBridge
from src.integrations.paperless import PaperlessConnector
from src.integrations.rest_learner import RESTSkillLearner
from src.integrations.search import KnowledgeSearchConnector
from src.interrupt.controller import AssistantState, GenerationSession, InterruptController
from src.memory.store import MemoryEntry, MemoryStore
from src.providers.localai import LocalAIClient
from src.security.passphrase import DynamicPassphraseValidator, SensitiveTopicGuard
from src.wakeword.detector import CommandFilter

_MEMORY_SAVE_PATTERNS = [
    re.compile(
        r"^(?:merke dir|merk dir|speichere)\s*(?:dass|:)?\s*(?P<key>.+?)\s+(?:ist|=)\s+(?P<value>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:remember(?:\s+that)?|save\s+memory)\s*(?::)?\s*(?P<key>.+?)\s+(?:is|=)\s+(?P<value>.+)$",
        re.IGNORECASE,
    ),
]

_MEMORY_RECALL_PATTERNS = [
    re.compile(
        r"^(?:was\s+ist\s+(?:mein|meine|der|die|das)|was\s+weißt\s+du\s+über|erinnere\s+dich\s+an)\s+(?P<key>.+?)[?!.]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:what\s+is\s+my|recall|do\s+you\s+remember)\s+(?P<key>.+?)[?!.]*$",
        re.IGNORECASE,
    ),
]

_PERSONALITY_PATTERNS = [
    re.compile(
        r"(?:ändere\s+(?:deine\s+)?persönlichkeit|persönlichkeit\s+auf|sei\s+ab\s+sofort)\s*[:\-]?\s*(?P<spec>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:change\s+(?:your\s+)?personality(?:\s+to)?|act\s+(?:more\s+)?like|be\s+more)\s*[:\-]?\s*(?P<spec>.+)$",
        re.IGNORECASE,
    ),
]


@dataclass
class AssistantResponse:
    """Structured response emitted for every voice, text, or API command."""

    accepted: bool
    reply: str
    language: str
    interrupted: bool = False
    requires_passphrase: bool = False
    blocked_by_security: bool = False
    matched_wake_word: Optional[str] = None
    route: str = "chat"
    provider: str = "alfred"
    tts_chunks: List[str] = field(default_factory=list)
    beeps_played: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AlfredAssistant:
    """High-level privacy-first assistant brain orchestrating all subsystems."""

    def __init__(
        self,
        config: Optional[AlfredConfig] = None,
        *,
        sound_engine: Optional[FeedbackSoundEngine] = None,
        device_manager: Optional[AudioDeviceManager] = None,
        vad: Optional[LowCpuVAD] = None,
        idle_throttle: Optional[IdleLoopThrottle] = None,
        command_filter: Optional[CommandFilter] = None,
        interrupt_controller: Optional[InterruptController] = None,
        passphrase_validator: Optional[DynamicPassphraseValidator] = None,
        security_guard: Optional[SensitiveTopicGuard] = None,
        memory_store: Optional[MemoryStore] = None,
        localai_client: Optional[LocalAIClient] = None,
        fancytanky: Optional[FancyTankyConnector] = None,
        paperless: Optional[PaperlessConnector] = None,
        search_connector: Optional[KnowledgeSearchConnector] = None,
        hermes_bridge: Optional[HermesBridge] = None,
        rest_learner: Optional[RESTSkillLearner] = None,
    ) -> None:
        self.config = config or AlfredConfig()
        self.sound_engine = sound_engine or FeedbackSoundEngine(enabled=True)
        self.device_manager = device_manager or AudioDeviceManager(
            sound_engine=self.sound_engine,
            smart_choice_enabled=self.config.smart_audio_enabled,
            configured_input_id=self.config.input_device_id,
            configured_output_id=self.config.output_device_id,
        )
        self.vad = vad or LowCpuVAD()
        self.idle_throttle = idle_throttle or IdleLoopThrottle(
            idle_interval_ms=self.config.idle_poll_interval_ms
        )
        self.command_filter = command_filter or CommandFilter(
            wake_words=self.config.wake_words,
            interrupt_phrases=self.config.interrupt_phrases,
            follow_up_window_seconds=self.config.follow_up_window_seconds,
        )
        self.interrupt_controller = interrupt_controller or InterruptController(
            sound_engine=self.sound_engine
        )
        self.passphrase_validator = passphrase_validator or DynamicPassphraseValidator(
            base_word=self.config.passphrase_base
        )
        self.security_guard = security_guard or SensitiveTopicGuard(
            validator=self.passphrase_validator,
            custom_keywords=self.config.sensitive_keywords,
        )
        self.memory_store = memory_store or MemoryStore(
            db_path=self.config.db_path,
            sensitivity_guard=self.security_guard,
        )
        self.localai_client = localai_client or LocalAIClient(
            localai_base_url=self.config.localai_base_url,
            api_key=self.config.localai_api_key,
            chat_model=self.config.localai_chat_model,
            tts_voice=self.config.localai_tts_voice,
            ollama_base_url=self.config.ollama_base_url,
            local_vad=self.vad,
        )
        self.fancytanky = fancytanky or FancyTankyConnector(base_url=self.config.fancytanky_url)
        self.paperless = paperless or PaperlessConnector(
            base_url=self.config.paperless_url,
            api_token=self.config.paperless_token,
        )
        self.search_connector = search_connector or KnowledgeSearchConnector()
        self.hermes_bridge = hermes_bridge or HermesBridge(
            enabled=self.config.hermes_enabled,
            mqtt_host=self.config.hermes_mqtt_host,
            mqtt_port=self.config.hermes_mqtt_port,
        )
        self.rest_learner = rest_learner or RESTSkillLearner(memory_store=self.memory_store)
        self._pending_sensitive_command: Optional[Dict[str, str]] = None

        if self.config.smart_audio_enabled:
            self.device_manager.select_smart_microphone()
            if not self.device_manager.active_output_id:
                self.device_manager.select_smart_output_device()

    # ------------------------------------------------------------------
    # Low-CPU Audio Frame Daemon Helper
    # ------------------------------------------------------------------

    def process_audio_frame(self, pcm_bytes: bytes, pace_loop: bool = True) -> VADFrameResult:
        """Process one PCM audio frame through LowCpuVAD and pace the loop to save CPU."""
        vad_result = self.vad.process_frame(pcm_bytes)
        if pace_loop:
            self.idle_throttle.pace(vad_result.is_speech)
        return vad_result

    # ------------------------------------------------------------------
    # Primary Command Pipeline
    # ------------------------------------------------------------------

    def process_input(
        self,
        text: str,
        *,
        require_wake_word: bool = True,
        explicit_passphrase: Optional[str] = None,
        language_override: Optional[str] = None,
        when: Optional[datetime] = None,
        tts_chunk_callback: Optional[Callable[[str], None]] = None,
    ) -> AssistantResponse:
        """Process text or transcribed speech through interrupt, wake, security, and brain."""
        history_start = len(self.sound_engine.history)
        preferred_lang = self._resolve_preferred_language(language_override)

        # Priority 0: Instant interrupt ("stop", "forget it", "stopp", "vergiss es")
        interrupt_hit = self.command_filter.match_interrupt(text)
        if interrupt_hit is not None:
            event = self.interrupt_controller.trigger_interrupt(reason=f"phrase:{interrupt_hit}")
            self._pending_sensitive_command = None
            lang = detect_language(text, default=preferred_lang)
            return AssistantResponse(
                accepted=True,
                reply=get_message("interrupted", lang),
                language=lang,
                interrupted=True,
                route="interrupt",
                provider="interrupt-controller",
                beeps_played=[e.cue_name for e in self.sound_engine.history[history_start:]],
                metadata={"dropped_chunks": event.dropped_chunks, "phrase": interrupt_hit},
            )

        # Pending passphrase challenge follow-up check
        pending_unlock = self._handle_pending_passphrase(text, preferred_lang, when)
        if pending_unlock is not None:
            if isinstance(pending_unlock, AssistantResponse):
                pending_unlock.beeps_played = [
                    e.cue_name for e in self.sound_engine.history[history_start:]
                ]
                return pending_unlock
            command_text = pending_unlock["command"]
            explicit_passphrase = pending_unlock["passphrase"]
            lang = pending_unlock["language"]
            matched_wake = None
        else:
            decision = self.command_filter.evaluate(text, require_wake_word=require_wake_word)
            if not decision.accepted:
                lang = detect_language(text, default=preferred_lang)
                return AssistantResponse(
                    accepted=False,
                    reply=get_message("wake_ignored", lang),
                    language=lang,
                    route="wake_ignored",
                )
            command_text = decision.command_text
            matched_wake = decision.matched_wake_word
            lang = normalize_language(language_override) if language_override else detect_language(
                command_text, default=preferred_lang
            )

        # Security check against sensitive/harmful topics AND sensitive memory hits
        memory_match = self._find_matching_memory(command_text)
        force_sensitive = bool(memory_match and memory_match.sensitive)
        assessment = self.security_guard.assess(
            command_text,
            explicit_passphrase=explicit_passphrase,
            force_sensitive=force_sensitive,
            when=when,
        )

        if assessment.requires_passphrase and not assessment.authorized:
            self.sound_engine.play("security")
            self._pending_sensitive_command = {"command": assessment.stripped_query, "language": lang}
            self.command_filter.open_follow_up_window()
            return AssistantResponse(
                accepted=True,
                reply=get_message(
                    "passphrase_required",
                    lang,
                    category=assessment.category or "sensitive",
                    base_word=self.passphrase_validator.base_word,
                ),
                language=lang,
                requires_passphrase=True,
                blocked_by_security=True,
                matched_wake_word=matched_wake,
                route="security_challenge",
                beeps_played=[e.cue_name for e in self.sound_engine.history[history_start:]],
                metadata={"category": assessment.category, "keywords": assessment.matched_keywords},
            )

        cleaned_command = assessment.stripped_query or command_text
        session = self.interrupt_controller.begin_session(AssistantState.THINKING)
        self.sound_engine.play("wake")
        self.sound_engine.play("thinking")

        route, provider, reply_text = self._dispatch_command(
            cleaned_command,
            lang=lang,
            session=session,
            authorized_sensitive=assessment.authorized,
        )

        if session.is_cancelled():
            return AssistantResponse(
                accepted=True,
                reply=get_message("interrupted", lang),
                language=lang,
                interrupted=True,
                matched_wake_word=matched_wake,
                route="interrupt",
                provider="interrupt-controller",
                beeps_played=[e.cue_name for e in self.sound_engine.history[history_start:]],
            )

        emitted_chunks = self.interrupt_controller.stream_tts_chunks(
            reply_text,
            session=session,
            emit_fn=tts_chunk_callback,
        )
        was_interrupted = session.is_cancelled()

        if not was_interrupted:
            self.sound_engine.play("success")
            self.interrupt_controller.finish_session(session)
            self.memory_store.add_episode("user", cleaned_command, language=lang)
            self.memory_store.add_episode("assistant", reply_text, language=lang)
            if self.config.hermes_enabled:
                self.hermes_bridge.build_tts_say_payload(
                    reply_text,
                    lang="de-DE" if lang == "de" else "en-US",
                )

        return AssistantResponse(
            accepted=True,
            reply=reply_text if not was_interrupted else get_message("interrupted", lang),
            language=lang,
            interrupted=was_interrupted,
            matched_wake_word=matched_wake,
            route=route,
            provider=provider,
            tts_chunks=emitted_chunks,
            beeps_played=[e.cue_name for e in self.sound_engine.history[history_start:]],
        )

    def _resolve_preferred_language(self, language_override: Optional[str]) -> str:
        if language_override:
            return normalize_language(language_override)
        profile = self.memory_store.get_personality()
        return normalize_language(profile.language or self.config.default_language)

    def _handle_pending_passphrase(
        self, text: str, preferred_lang: str, when: Optional[datetime]
    ) -> Optional[Any]:
        if not self._pending_sensitive_command:
            return None

        token = self.passphrase_validator.find_valid_passphrase(text, when=when)
        pending = self._pending_sensitive_command
        if token is not None:
            self._pending_sensitive_command = None
            self.command_filter.close_follow_up_window()
            return {"command": pending["command"], "passphrase": token, "language": pending["language"]}

        # Check if user explicitly attempted a base-word passphrase for the wrong weekday.
        if self.passphrase_validator.base_word.lower()[:4] in text.lower():
            self.sound_engine.play("security")
            return AssistantResponse(
                accepted=True,
                reply=get_message("passphrase_invalid", pending["language"]),
                language=pending["language"],
                requires_passphrase=True,
                blocked_by_security=True,
                route="security_rejected",
            )

        # User moved on to another topic; clear pending sensitive request.
        self._pending_sensitive_command = None
        return None

    def _find_matching_memory(self, query: str) -> Optional[MemoryEntry]:
        for pattern in _MEMORY_RECALL_PATTERNS:
            match = pattern.match(query.strip())
            if match:
                return self.memory_store.get_memory(match.group("key").strip())
        hits = self.memory_store.search_memories(query)
        return hits[0] if hits else None

    def _dispatch_command(
        self,
        command: str,
        *,
        lang: str,
        session: GenerationSession,
        authorized_sensitive: bool,
    ) -> tuple:
        handlers = [
            lambda: self._try_language_switch(command),
            lambda: self._try_personality_command(command, lang),
            lambda: self._try_memory_command(command, lang),
            lambda: self._try_learn_skill_command(command, lang),
            lambda: self._try_learned_skill_execution(command, lang, authorized_sensitive),
            lambda: self._try_integration_command(command, lang),
        ]
        for handler in handlers:
            result = handler()
            if result is not None:
                return result

        return self._run_llm_chat(command, lang=lang, session=session, include_sensitive=authorized_sensitive)

    def _try_language_switch(self, command: str) -> Optional[tuple]:
        lowered = command.lower().strip()
        if any(phrase in lowered for phrase in ("sprich deutsch", "auf deutsch", "switch to german")):
            self.memory_store.update_personality(language="de")
            return "language", "i18n", get_message("language_switched", "de")
        if any(phrase in lowered for phrase in ("speak english", "switch to english", "auf englisch")):
            self.memory_store.update_personality(language="en")
            return "language", "i18n", get_message("language_switched", "en")
        return None

    def _try_personality_command(self, command: str, lang: str) -> Optional[tuple]:
        for pattern in _PERSONALITY_PATTERNS:
            match = pattern.search(command.strip())
            if match:
                spec = match.group("spec").strip()
                updates: Dict[str, Any] = {"add_rule": spec}
                lower_spec = spec.lower()
                if any(w in lower_spec for w in ("humor", "witzig", "funny", "lustig")):
                    updates["humor_level"] = 8
                    updates["tone"] = "witty, warm, helpful"
                elif any(w in lower_spec for w in ("formal", "förmlich", "butler", "seriös")):
                    updates["formality"] = "formal"
                    updates["humor_level"] = 2
                    updates["tone"] = "distinguished, courteous, precise"
                else:
                    updates["tone"] = spec
                self.memory_store.update_personality(**updates)
                return "personality", "memory-store", get_message("personality_updated", lang, changes=spec)
        return None

    def _try_memory_command(self, command: str, lang: str) -> Optional[tuple]:
        for pattern in _MEMORY_SAVE_PATTERNS:
            match = pattern.match(command.strip())
            if match:
                key = match.group("key").strip()
                value = match.group("value").strip()
                entry = self.memory_store.save_memory(key=key, value=value)
                shown_value = "[geschützt]" if entry.sensitive and lang == "de" else (
                    "[protected]" if entry.sensitive else entry.value
                )
                return "memory_save", "memory-store", get_message("memory_saved", lang, key=entry.key, value=shown_value)

        for pattern in _MEMORY_RECALL_PATTERNS:
            match = pattern.match(command.strip())
            if match:
                key = match.group("key").strip()
                entry = self.memory_store.get_memory(key)
                if entry is not None:
                    return "memory_recall", "memory-store", get_message(
                        "memory_recalled", lang, key=entry.key, value=entry.value
                    )
                return "memory_recall", "memory-store", get_message("memory_not_found", lang)
        return None

    def _try_learn_skill_command(self, command: str, lang: str) -> Optional[tuple]:
        learned = self.rest_learner.parse_and_learn_from_text(command)
        if learned is not None:
            return "skill_learn", "rest-learner", get_message("skill_learned", lang, name=learned.name)
        return None

    def _try_learned_skill_execution(
        self, command: str, lang: str, authorized_sensitive: bool
    ) -> Optional[tuple]:
        skill = self.memory_store.match_skill(command)
        if skill is None:
            return None
        if skill.requires_passphrase and not authorized_sensitive:
            return (
                "security_challenge",
                "security",
                get_message(
                    "passphrase_required",
                    lang,
                    category="protected_skill",
                    base_word=self.passphrase_validator.base_word,
                ),
            )
        result = self.rest_learner.execute_skill(skill, {"query": command})
        return "skill_execute", f"skill:{skill.name}", get_message(
            "skill_executed", lang, name=skill.name, result=result.response_text
        )

    def _try_integration_command(self, command: str, lang: str) -> Optional[tuple]:
        lowered = command.lower()

        if any(term in lowered for term in ("fancytanky", "tanky", "panzer", "roboter", "robot")):
            reply = self.fancytanky.execute_natural_command(command, language=lang)
            return "fancytanky", "fancytanky", get_message("fancytanky_reply", lang, detail=reply)

        if any(term in lowered for term in ("paperless", "dokument", "dokumente", "rechnungen", "document")):
            search_term = re.sub(
                r"\b(?:paperless|dokumente?|documents?|suche|search|nach|for|in)\b",
                "",
                command,
                flags=re.IGNORECASE,
            ).strip() or "steuer"
            hits = self.paperless.search_documents(search_term)
            if not hits:
                detail = get_message("search_empty", lang, query=search_term)
            else:
                detail = "; ".join(f"{h.title} ({h.created or 'n/a'})" for h in hits[:3])
            return "paperless", "paperless", get_message("paperless_reply", lang, detail=detail)

        search_match = re.match(
            r"^(?:wikipedia|google|suche\s+(?:nach|im\s+internet\s+nach)|search\s+(?:for|the\s+web\s+for)|was\s+ist|wer\s+ist|who\s+is|what\s+is)\s+(?P<q>.+?)[?!.]*$",
            command.strip(),
            flags=re.IGNORECASE,
        )
        if search_match:
            query = search_match.group("q").strip()
            # Check memory first if user asked "was ist ..." about something they taught Alfred
            mem = self.memory_store.get_memory(query)
            if mem is not None:
                return "memory_recall", "memory-store", get_message(
                    "memory_recalled", lang, key=mem.key, value=mem.value
                )
            hit = self.search_connector.search(query, language=lang)
            if hit is not None:
                return "search", hit.source, f"{hit.title}: {hit.summary}"
            return "search", "search", get_message("search_empty", lang, query=query)

        return None

    def _run_llm_chat(
        self,
        command: str,
        *,
        lang: str,
        session: GenerationSession,
        include_sensitive: bool,
    ) -> tuple:
        system_prompt = self.memory_store.build_system_prompt(
            language=lang, include_sensitive=include_sensitive
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": command},
        ]
        chat_res = self.localai_client.chat_completion(
            messages=messages,
            language=lang,
            cancel_check=session.is_cancelled,
        )
        if chat_res.cancelled or session.is_cancelled():
            return "interrupt", "interrupt-controller", get_message("interrupted", lang)

        # Dispatch any Nous Hermes <tool_call> returned by local Hermes LLM
        tool_calls = self.hermes_bridge.parse_tool_calls(chat_res.content)
        if tool_calls:
            outputs: List[str] = []
            for call in tool_calls:
                skill = next(
                    (s for s in self.memory_store.list_skills() if s.name == call.name.lower()),
                    None,
                )
                if skill is not None:
                    res = self.rest_learner.execute_skill(skill, call.arguments)
                    outputs.append(f"[{skill.name}] {res.response_text}")
            if outputs:
                return "hermes_tool_call", chat_res.provider, " | ".join(outputs)

        return "chat", chat_res.provider, chat_res.content


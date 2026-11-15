"""SQLite persistent store for learned memories, personality, and Alexa-like skills."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.security.passphrase import SensitiveTopicGuard


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryEntry:
    """Represents a single persisted user fact or learned memory."""

    key: str
    value: str
    category: str = "general"
    sensitive: bool = False
    updated_at: str = field(default_factory=_utc_now)


@dataclass
class PersonalityProfile:
    """Configurable, mutable assistant personality persisted across restarts."""

    name: str = "Alfred"
    role: str = "Privacy-First Local AI Assistant"
    tone: str = "helpful, loyal, concise"
    humor_level: int = 3
    formality: str = "balanced"
    language: str = "de"
    custom_rules: List[str] = field(default_factory=list)
    updated_at: str = field(default_factory=_utc_now)


@dataclass
class SkillDefinition:
    """User-taught Alexa-like skill mapped to an HTTP/REST or internal action."""

    name: str
    description: str
    trigger_phrases: List[str]
    endpoint_url: str
    http_method: str = "GET"
    headers: Dict[str, str] = field(default_factory=dict)
    payload_template: Dict[str, Any] = field(default_factory=dict)
    requires_passphrase: bool = False
    updated_at: str = field(default_factory=_utc_now)


@dataclass
class EpisodeEntry:
    """Recorded dialogue turn for context and auditability."""

    id: int
    role: str
    content: str
    language: str
    created_at: str


class MemoryStore:
    """Durable SQLite persistence for Alfred memories, personality, and skills (INV-04)."""

    def __init__(
        self,
        db_path: str = "data/alfred_memory.db",
        sensitivity_guard: Optional[SensitiveTopicGuard] = None,
    ) -> None:
        self.db_path = db_path
        self._guard = sensitivity_guard or SensitiveTopicGuard()
        self._lock = threading.RLock()

        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    sensitive INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS personality (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    tone TEXT NOT NULL,
                    humor_level INTEGER NOT NULL,
                    formality TEXT NOT NULL,
                    language TEXT NOT NULL,
                    custom_rules TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS skills (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    trigger_phrases TEXT NOT NULL,
                    endpoint_url TEXT NOT NULL,
                    http_method TEXT NOT NULL,
                    headers TEXT NOT NULL,
                    payload_template TEXT NOT NULL,
                    requires_passphrase INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    language TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            cur.execute("SELECT COUNT(*) FROM personality WHERE id = 1")
            if cur.fetchone()[0] == 0:
                default = PersonalityProfile()
                cur.execute(
                    """
                    INSERT INTO personality (
                        id, name, role, tone, humor_level, formality, language, custom_rules, updated_at
                    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        default.name,
                        default.role,
                        default.tone,
                        default.humor_level,
                        default.formality,
                        default.language,
                        json.dumps(default.custom_rules),
                        default.updated_at,
                    ),
                )
            self._conn.commit()

    def close(self) -> None:
        """Close the SQLite database connection."""
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Memories
    # ------------------------------------------------------------------

    def save_memory(
        self,
        key: str,
        value: str,
        category: str = "general",
        sensitive: Optional[bool] = None,
    ) -> MemoryEntry:
        """Persist or update a learned memory, auto-detecting sensitive content."""
        norm_key = key.strip().lower()
        if not norm_key:
            raise ValueError("Memory key must not be empty.")

        detected_cat, _ = self._guard.detect_sensitivity(f"{norm_key} {value}")
        is_sensitive = bool(sensitive) if sensitive is not None else (detected_cat is not None)
        now = _utc_now()

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO memories (key, value, category, sensitive, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    sensitive = excluded.sensitive,
                    updated_at = excluded.updated_at
                """,
                (norm_key, value.strip(), category, int(is_sensitive), now),
            )
            self._conn.commit()

        return MemoryEntry(
            key=norm_key,
            value=value.strip(),
            category=category,
            sensitive=is_sensitive,
            updated_at=now,
        )

    def get_memory(self, key: str) -> Optional[MemoryEntry]:
        """Look up a specific memory by key or partial substring match."""
        norm_key = key.strip().lower()
        with self._lock:
            row = self._conn.execute(
                "SELECT key, value, category, sensitive, updated_at FROM memories WHERE key = ?",
                (norm_key,),
            ).fetchone()
            if row is None:
                row = self._conn.execute(
                    """
                    SELECT key, value, category, sensitive, updated_at
                    FROM memories
                    WHERE key LIKE ? OR value LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (f"%{norm_key}%", f"%{norm_key}%"),
                ).fetchone()
        if row is None:
            return None
        return self._row_to_memory(row)

    def search_memories(self, query: str) -> List[MemoryEntry]:
        """Search memories matching any significant token in query."""
        tokens = [t.strip().lower() for t in query.split() if len(t.strip()) >= 3]
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value, category, sensitive, updated_at FROM memories ORDER BY updated_at DESC"
            ).fetchall()

        entries = [self._row_to_memory(r) for r in rows]
        if not tokens:
            return entries
        matched = [
            e
            for e in entries
            if any(tok in e.key.lower() or tok in e.value.lower() for tok in tokens)
        ]
        return matched

    def list_memories(self, include_sensitive_values: bool = False) -> List[MemoryEntry]:
        """Return all memories, masking sensitive values when locked."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value, category, sensitive, updated_at FROM memories ORDER BY updated_at DESC"
            ).fetchall()
        entries: List[MemoryEntry] = []
        for row in rows:
            entry = self._row_to_memory(row)
            if entry.sensitive and not include_sensitive_values:
                entry = MemoryEntry(
                    key=entry.key,
                    value="[LOCKED - PASSPHRASE REQUIRED]",
                    category=entry.category,
                    sensitive=True,
                    updated_at=entry.updated_at,
                )
            entries.append(entry)
        return entries

    def delete_memory(self, key: str) -> bool:
        """Delete a memory entry by key."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM memories WHERE key = ?", (key.strip().lower(),))
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            key=row["key"],
            value=row["value"],
            category=row["category"],
            sensitive=bool(row["sensitive"]),
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # Personality
    # ------------------------------------------------------------------

    def get_personality(self) -> PersonalityProfile:
        """Load the current persisted personality profile."""
        with self._lock:
            row = self._conn.execute(
                """
                SELECT name, role, tone, humor_level, formality, language, custom_rules, updated_at
                FROM personality WHERE id = 1
                """
            ).fetchone()
        return PersonalityProfile(
            name=row["name"],
            role=row["role"],
            tone=row["tone"],
            humor_level=int(row["humor_level"]),
            formality=row["formality"],
            language=row["language"],
            custom_rules=json.loads(row["custom_rules"]),
            updated_at=row["updated_at"],
        )

    def update_personality(
        self,
        *,
        name: Optional[str] = None,
        role: Optional[str] = None,
        tone: Optional[str] = None,
        humor_level: Optional[int] = None,
        formality: Optional[str] = None,
        language: Optional[str] = None,
        add_rule: Optional[str] = None,
        custom_rules: Optional[List[str]] = None,
    ) -> PersonalityProfile:
        """Update and persist one or more personality attributes."""
        current = self.get_personality()
        rules = list(current.custom_rules) if custom_rules is None else list(custom_rules)
        if add_rule and add_rule.strip() and add_rule.strip() not in rules:
            rules.append(add_rule.strip())

        updated = PersonalityProfile(
            name=name.strip() if name else current.name,
            role=role.strip() if role else current.role,
            tone=tone.strip() if tone else current.tone,
            humor_level=max(0, min(10, humor_level)) if humor_level is not None else current.humor_level,
            formality=formality.strip() if formality else current.formality,
            language=language.strip().lower() if language else current.language,
            custom_rules=rules,
            updated_at=_utc_now(),
        )

        with self._lock:
            self._conn.execute(
                """
                UPDATE personality
                SET name = ?, role = ?, tone = ?, humor_level = ?, formality = ?,
                    language = ?, custom_rules = ?, updated_at = ?
                WHERE id = 1
                """,
                (
                    updated.name,
                    updated.role,
                    updated.tone,
                    updated.humor_level,
                    updated.formality,
                    updated.language,
                    json.dumps(updated.custom_rules),
                    updated.updated_at,
                ),
            )
            self._conn.commit()
        return updated

    def build_system_prompt(self, language: str = "de", include_sensitive: bool = False) -> str:
        """Render the dynamic LLM system prompt combining personality and safe memories."""
        profile = self.get_personality()
        memories = self.list_memories(include_sensitive_values=include_sensitive)
        safe_facts = [
            f"- {m.key}: {m.value}"
            for m in memories
            if include_sensitive or not m.sensitive
        ][:15]

        lang_line = (
            "Antworte standardmäßig auf Deutsch."
            if language == "de"
            else "Respond in English by default."
        )
        parts = [
            f"You are {profile.name} ({profile.role}).",
            f"Tone: {profile.tone} | Formality: {profile.formality} | Humor: {profile.humor_level}/10.",
            lang_line,
        ]
        if profile.custom_rules:
            parts.append("Custom personality rules: " + "; ".join(profile.custom_rules))
        if safe_facts:
            parts.append("Learned persistent memories:\n" + "\n".join(safe_facts))
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Dynamic Skills (Alexa-like skills)
    # ------------------------------------------------------------------

    def save_skill(self, skill: SkillDefinition) -> SkillDefinition:
        """Persist or update a dynamic Alexa-like REST skill."""
        norm_name = skill.name.strip().lower()
        if not norm_name:
            raise ValueError("Skill name must not be empty.")
        now = _utc_now()
        triggers = [t.strip().lower() for t in skill.trigger_phrases if t and t.strip()]
        if not triggers:
            triggers = [norm_name]

        with self._lock:
            self._conn.execute(
                """
                INSERT INTO skills (
                    name, description, trigger_phrases, endpoint_url, http_method,
                    headers, payload_template, requires_passphrase, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = excluded.description,
                    trigger_phrases = excluded.trigger_phrases,
                    endpoint_url = excluded.endpoint_url,
                    http_method = excluded.http_method,
                    headers = excluded.headers,
                    payload_template = excluded.payload_template,
                    requires_passphrase = excluded.requires_passphrase,
                    updated_at = excluded.updated_at
                """,
                (
                    norm_name,
                    skill.description.strip(),
                    json.dumps(triggers),
                    skill.endpoint_url.strip(),
                    skill.http_method.upper(),
                    json.dumps(skill.headers),
                    json.dumps(skill.payload_template),
                    int(skill.requires_passphrase),
                    now,
                ),
            )
            self._conn.commit()

        return SkillDefinition(
            name=norm_name,
            description=skill.description.strip(),
            trigger_phrases=triggers,
            endpoint_url=skill.endpoint_url.strip(),
            http_method=skill.http_method.upper(),
            headers=dict(skill.headers),
            payload_template=dict(skill.payload_template),
            requires_passphrase=skill.requires_passphrase,
            updated_at=now,
        )

    def list_skills(self) -> List[SkillDefinition]:
        """Return all persisted dynamic skills."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT name, description, trigger_phrases, endpoint_url, http_method,
                       headers, payload_template, requires_passphrase, updated_at
                FROM skills ORDER BY updated_at DESC
                """
            ).fetchall()
        return [self._row_to_skill(r) for r in rows]

    def match_skill(self, utterance: str) -> Optional[SkillDefinition]:
        """Find the best matching skill for a user utterance based on trigger phrases."""
        lowered = utterance.strip().lower()
        if not lowered:
            return None

        best_skill: Optional[SkillDefinition] = None
        best_len = 0
        for skill in self.list_skills():
            for trigger in skill.trigger_phrases:
                if trigger in lowered and len(trigger) > best_len:
                    best_len = len(trigger)
                    best_skill = skill
        return best_skill

    @staticmethod
    def _row_to_skill(row: sqlite3.Row) -> SkillDefinition:
        return SkillDefinition(
            name=row["name"],
            description=row["description"],
            trigger_phrases=json.loads(row["trigger_phrases"]),
            endpoint_url=row["endpoint_url"],
            http_method=row["http_method"],
            headers=json.loads(row["headers"]),
            payload_template=json.loads(row["payload_template"]),
            requires_passphrase=bool(row["requires_passphrase"]),
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # Episodes
    # ------------------------------------------------------------------

    def add_episode(self, role: str, content: str, language: str = "de") -> EpisodeEntry:
        """Append a conversation entry to SQLite history."""
        now = _utc_now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO episodes (role, content, language, created_at) VALUES (?, ?, ?, ?)",
                (role, content, language, now),
            )
            self._conn.commit()
            row_id = int(cur.lastrowid)
        return EpisodeEntry(id=row_id, role=role, content=content, language=language, created_at=now)

    def recent_episodes(self, limit: int = 20) -> List[EpisodeEntry]:
        """Return recent conversation episodes ordered oldest-to-newest."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, role, content, language, created_at
                FROM episodes ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            EpisodeEntry(
                id=int(r["id"]),
                role=r["role"],
                content=r["content"],
                language=r["language"],
                created_at=r["created_at"],
            )
            for r in reversed(rows)
        ]


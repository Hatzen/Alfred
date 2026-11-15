"""Dynamic weekday passphrase validation and sensitive/harmful topic guard."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional, Tuple

WEEKDAY_NUMBERS_EN: Dict[int, str] = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
}

WEEKDAY_NUMBERS_DE: Dict[int, List[str]] = {
    1: ["eins"],
    2: ["zwei", "zwo"],
    3: ["drei"],
    4: ["vier"],
    5: ["fuenf", "fünf"],
    6: ["sechs"],
    7: ["sieben"],
}

CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "personal_finance": [
        "steuernummer",
        "taxnumber",
        "tax number",
        "tax id",
        "steuer-id",
        "iban",
        "kreditkarte",
        "credit card",
        "passwort",
        "password",
        "pin",
        "geheim",
        "secret",
        "sozialversicherungsnummer",
        "ssn",
    ],
    "adult_content": [
        "porn",
        "pornography",
        "pornografie",
        "porno",
        "nsfw",
        "erotik",
        "xxx",
    ],
    "harmful_actions": [
        "hack",
        "exploit",
        "malware",
        "ransomware",
        "delete all",
        "alles löschen",
        "rm -rf",
        "format c:",
        "waffe",
        "weapon",
        "bomb",
        "bombe",
        "selbstmord",
        "suicide",
    ],
}


@dataclass
class SecurityAssessment:
    """Result of evaluating a request for sensitive/harmful content and passphrase verification."""

    requires_passphrase: bool
    authorized: bool
    category: Optional[str] = None
    matched_keywords: List[str] = field(default_factory=list)
    stripped_query: str = ""
    used_passphrase: Optional[str] = None


class DynamicPassphraseValidator:
    """Validates configurable base-word + weekday-number passphrases (INV-03)."""

    def __init__(
        self,
        base_word: str = "Nilpferd",
        now_fn: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.base_word = base_word.strip() or "Nilpferd"
        self._now_fn = now_fn

    def set_base_word(self, base_word: str) -> None:
        """Update the configured base secret word."""
        cleaned = base_word.strip()
        if not cleaned:
            raise ValueError("Passphrase base word must not be empty.")
        self.base_word = cleaned

    def expected_tokens_for_weekday(self, iso_weekday: int) -> List[str]:
        """Generate all accepted passphrase variants for an ISO weekday (1=Monday .. 7=Sunday)."""
        if iso_weekday not in WEEKDAY_NUMBERS_EN:
            raise ValueError(f"ISO weekday must be 1..7, got {iso_weekday}")

        base = self.base_word.lower()
        stems = [base]
        if len(base) > 3:
            # Support dropped trailing consonant variant from README (e.g. Nilpferd -> Nilpfer1).
            stems.append(base[:-1])

        suffixes = [str(iso_weekday), WEEKDAY_NUMBERS_EN[iso_weekday]]
        suffixes.extend(WEEKDAY_NUMBERS_DE[iso_weekday])

        candidates: List[str] = []
        for stem in stems:
            for suffix in suffixes:
                candidates.append(f"{stem}{suffix}")
                candidates.append(f"{stem} {suffix}")
        return sorted(set(candidates), key=len, reverse=True)

    def current_weekday(self, when: Optional[datetime] = None) -> int:
        """Return ISO weekday (1=Monday .. 7=Sunday) for given or current timestamp."""
        dt = when or self._now_fn()
        return dt.isoweekday()

    def find_valid_passphrase(
        self, text: str, when: Optional[datetime] = None
    ) -> Optional[str]:
        """Return the matched dynamic passphrase token if present in text for today's weekday."""
        if not text:
            return None

        weekday = self.current_weekday(when)
        for token in self.expected_tokens_for_weekday(weekday):
            pattern = rf"(?:^|\b){re.escape(token)}(?:\b|$)"
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def verify(self, text: str, when: Optional[datetime] = None) -> bool:
        """Return True if text contains a valid dynamic passphrase for the target weekday."""
        return self.find_valid_passphrase(text, when=when) is not None

    def strip_passphrase(self, text: str, when: Optional[datetime] = None) -> Tuple[str, Optional[str]]:
        """Remove an embedded valid passphrase from text and return (cleaned_text, matched_token)."""
        matched = self.find_valid_passphrase(text, when=when)
        if not matched:
            return text.strip(), None
        cleaned = re.sub(
            rf"(?:^|\b){re.escape(matched)}(?:\b|$)",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,:;.-")
        return cleaned, matched


class SensitiveTopicGuard:
    """Blocks sensitive personal, adult, or harmful queries without today's passphrase (INV-03)."""

    def __init__(
        self,
        validator: Optional[DynamicPassphraseValidator] = None,
        custom_keywords: Optional[Iterable[str]] = None,
    ) -> None:
        self.validator = validator or DynamicPassphraseValidator()
        self.custom_keywords: List[str] = sorted(
            {kw.strip().lower() for kw in (custom_keywords or []) if kw and kw.strip()}
        )

    def add_sensitive_keyword(self, keyword: str) -> None:
        """Register an additional custom sensitive keyword at runtime."""
        cleaned = keyword.strip().lower()
        if cleaned and cleaned not in self.custom_keywords:
            self.custom_keywords.append(cleaned)
            self.custom_keywords.sort()

    def detect_sensitivity(self, text: str) -> Tuple[Optional[str], List[str]]:
        """Return (category, matched_keywords) if text matches sensitive or harmful terms."""
        lowered = text.lower()
        for category, words in CATEGORY_KEYWORDS.items():
            hits = [w for w in words if self._keyword_in_text(w, lowered)]
            if hits:
                return category, hits

        custom_hits = [w for w in self.custom_keywords if self._keyword_in_text(w, lowered)]
        if custom_hits:
            return "custom_sensitive", custom_hits

        return None, []

    @staticmethod
    def _keyword_in_text(keyword: str, lowered_text: str) -> bool:
        if " " in keyword or "-" in keyword or ":" in keyword:
            return keyword in lowered_text
        return re.search(rf"\b{re.escape(keyword)}\b", lowered_text) is not None

    def assess(
        self,
        query: str,
        explicit_passphrase: Optional[str] = None,
        force_sensitive: bool = False,
        when: Optional[datetime] = None,
    ) -> SecurityAssessment:
        """Evaluate whether a query requires a passphrase and whether it is authorized."""
        stripped_query, inline_match = self.validator.strip_passphrase(query, when=when)
        category, matched = self.detect_sensitivity(stripped_query or query)

        if force_sensitive and category is None:
            category = "sensitive_memory"

        if category is None:
            return SecurityAssessment(
                requires_passphrase=False,
                authorized=True,
                stripped_query=stripped_query or query.strip(),
                used_passphrase=inline_match,
            )

        token = inline_match
        if token is None and explicit_passphrase:
            token = self.validator.find_valid_passphrase(explicit_passphrase, when=when)

        return SecurityAssessment(
            requires_passphrase=True,
            authorized=token is not None,
            category=category,
            matched_keywords=matched,
            stripped_query=stripped_query,
            used_passphrase=token,
        )


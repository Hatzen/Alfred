"""German-first (de) and English (en) language detection and message templates."""

from __future__ import annotations

import re
from typing import Dict

SUPPORTED_LANGUAGES = ("de", "en")

_GERMAN_CUES = {
    "hallo",
    "bitte",
    "danke",
    "wie",
    "was",
    "wer",
    "wo",
    "wann",
    "warum",
    "merke",
    "speichere",
    "suche",
    "zeig",
    "steuernummer",
    "vergiss",
    "stopp",
    "abbrechen",
    "sprich",
    "persönlichkeit",
    "deutsch",
    "panzer",
    "fahre",
    "dokument",
    "dokumente",
    "heute",
    "ist",
    "mein",
    "meine",
    "dein",
    "deine",
    "und",
    "mit",
    "für",
    "über",
}

_ENGLISH_CUES = {
    "hello",
    "please",
    "thanks",
    "thank",
    "how",
    "what",
    "who",
    "where",
    "when",
    "why",
    "remember",
    "save",
    "search",
    "show",
    "tax",
    "forget",
    "cancel",
    "speak",
    "personality",
    "english",
    "tank",
    "drive",
    "document",
    "documents",
    "today",
    "is",
    "my",
    "your",
    "and",
    "with",
    "for",
    "about",
}

_MESSAGES: Dict[str, Dict[str, str]] = {
    "de": {
        "wake_ignored": "Kein Aktivierungswort erkannt. Sag zum Beispiel 'Hey Alfred' vor deinem Befehl.",
        "interrupted": "Verstanden, ich breche sofort ab.",
        "passphrase_required": (
            "Dieser Bereich enthält sensible oder geschützte Informationen ({category}). "
            "Bitte nenne das dynamische Wochentag-Passwort (Basiswort '{base_word}' + heutige Wochentagszahl)."
        ),
        "passphrase_invalid": (
            "Das angegebene Wochentag-Passwort ist ungültig oder gehört zu einem anderen Wochentag."
        ),
        "passphrase_accepted": "Passwort bestätigt. Ich führe deine Anfrage jetzt aus.",
        "memory_saved": "Alles klar, ich habe mir gemerkt: {key} = {value}.",
        "memory_recalled": "Aus meinem Gedächtnis weiß ich über '{key}': {value}.",
        "memory_not_found": "Dazu habe ich aktuell noch keine gespeicherte Erinnerung.",
        "personality_updated": "Meine Persönlichkeit wurde aktualisiert ({changes}).",
        "skill_learned": "Neuer Skill '{name}' wurde gelernt und für zukünftige Befehle gespeichert.",
        "skill_executed": "Skill '{name}' ausgeführt: {result}",
        "search_empty": "Zu '{query}' konnte ich leider keine Treffer finden.",
        "fancytanky_reply": "FancyTanky-Rückmeldung: {detail}",
        "paperless_reply": "Paperless-Ergebnis: {detail}",
        "language_switched": "Sprache auf Deutsch umgestellt.",
        "default_personality_prompt": (
            "Du bist Alfred, ein privater, lokaler KI-Assistent. "
            "Antworte präzise, hilfsbereit und freundlich auf Deutsch."
        ),
    },
    "en": {
        "wake_ignored": "No wake phrase detected. Please address me with 'Hey Alfred' before a command.",
        "interrupted": "Understood, dropping the current response immediately.",
        "passphrase_required": (
            "This request touches sensitive or restricted information ({category}). "
            "Please provide today's dynamic weekday passphrase (base word '{base_word}' + weekday number)."
        ),
        "passphrase_invalid": (
            "The provided weekday passphrase is invalid or does not match today's weekday."
        ),
        "passphrase_accepted": "Passphrase verified. Executing your request now.",
        "memory_saved": "Got it, I stored in memory: {key} = {value}.",
        "memory_recalled": "From memory for '{key}': {value}.",
        "memory_not_found": "I do not have a stored memory for that yet.",
        "personality_updated": "Personality updated ({changes}).",
        "skill_learned": "Learned new skill '{name}' and persisted it for future commands.",
        "skill_executed": "Executed skill '{name}': {result}",
        "search_empty": "I could not find results for '{query}'.",
        "fancytanky_reply": "FancyTanky response: {detail}",
        "paperless_reply": "Paperless result: {detail}",
        "language_switched": "Language switched to English.",
        "default_personality_prompt": (
            "You are Alfred, a privacy-first local AI assistant. "
            "Respond clearly, concisely, and helpfully in English."
        ),
    },
}


def normalize_language(language: str, default: str = "de") -> str:
    """Normalize language code to supported 'de' or 'en'."""
    if not language:
        return default if default in SUPPORTED_LANGUAGES else "de"
    code = language.strip().lower()[:2]
    return code if code in SUPPORTED_LANGUAGES else (default if default in SUPPORTED_LANGUAGES else "de")


def detect_language(text: str, default: str = "de") -> str:
    """Detect whether an utterance is German ('de') or English ('en')."""
    normalized_default = normalize_language(default)
    if not text:
        return normalized_default

    lowered = text.lower()
    if any(ch in lowered for ch in ("ä", "ö", "ü", "ß")):
        return "de"

    tokens = set(re.findall(r"[a-zA-ZäöüßÄÖÜ]+", lowered))
    de_score = len(tokens & _GERMAN_CUES)
    en_score = len(tokens & _ENGLISH_CUES)

    if de_score > en_score:
        return "de"
    if en_score > de_score:
        return "en"
    return normalized_default


def get_message(message_id: str, language: str = "de", **kwargs: object) -> str:
    """Retrieve and format a localized template message."""
    lang = normalize_language(language)
    template = _MESSAGES.get(lang, _MESSAGES["de"]).get(
        message_id, _MESSAGES["en"].get(message_id, message_id)
    )
    return template.format(**kwargs) if kwargs else template

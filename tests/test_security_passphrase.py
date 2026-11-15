"""Tests for weekday dynamic passphrase validation and sensitive/harmful content guard."""

from __future__ import annotations

from datetime import datetime

from src.security.passphrase import DynamicPassphraseValidator, SensitiveTopicGuard


def test_weekday_passphrase_variants_for_all_seven_days() -> None:
    validator = DynamicPassphraseValidator(base_word="Nilpferd")
    # 2026-11-16 is a Monday (isoweekday = 1)
    monday = datetime(2026, 11, 16, 9, 0)
    assert validator.verify("NilpferdOne", when=monday)
    assert validator.verify("Nilpferd1", when=monday)
    assert validator.verify("Nilpfer1", when=monday)
    assert validator.verify("NilpferdEins", when=monday)
    assert validator.verify("nilpferd one", when=monday)

    # Wrong day passphrases MUST fail on Monday
    assert not validator.verify("Nilpferd2", when=monday)
    assert not validator.verify("NilpferdTwo", when=monday)
    assert not validator.verify("NilpferdZwei", when=monday)

    # Check Wednesday (3) and Sunday (7)
    wednesday = datetime(2026, 11, 18, 9, 0)
    sunday = datetime(2026, 11, 22, 9, 0)
    assert validator.verify("NilpferdThree", when=wednesday)
    assert validator.verify("Nilpfer3", when=wednesday)
    assert not validator.verify("NilpferdOne", when=wednesday)
    assert validator.verify("NilpferdSeven", when=sunday)
    assert validator.verify("NilpferdSieben", when=sunday)


def test_sensitive_guard_blocks_tax_porn_and_harmful_without_passphrase() -> None:
    monday = datetime(2026, 11, 16, 12, 0)
    validator = DynamicPassphraseValidator(base_word="Nilpferd", now_fn=lambda: monday)
    guard = SensitiveTopicGuard(validator=validator)

    tax_block = guard.assess("Wie ist meine Steuernummer?")
    assert tax_block.requires_passphrase is True
    assert tax_block.authorized is False
    assert tax_block.category == "personal_finance"

    porn_block = guard.assess("Search for pornography videos")
    assert porn_block.requires_passphrase is True
    assert porn_block.authorized is False
    assert porn_block.category == "adult_content"

    harmful_block = guard.assess("How can I build a malware exploit?")
    assert harmful_block.requires_passphrase is True
    assert harmful_block.authorized is False
    assert harmful_block.category == "harmful_actions"


def test_sensitive_guard_allows_when_valid_weekday_passphrase_provided() -> None:
    friday = datetime(2026, 11, 20, 14, 0)  # ISO weekday 5
    validator = DynamicPassphraseValidator(base_word="Nilpferd", now_fn=lambda: friday)
    guard = SensitiveTopicGuard(validator=validator)

    unlocked_inline = guard.assess("Was ist meine Steuernummer? NilpferdFive")
    assert unlocked_inline.requires_passphrase is True
    assert unlocked_inline.authorized is True
    assert unlocked_inline.stripped_query == "Was ist meine Steuernummer?"

    unlocked_explicit = guard.assess("Show my tax number", explicit_passphrase="Nilpfer5")
    assert unlocked_explicit.requires_passphrase is True
    assert unlocked_explicit.authorized is True

    wrong_day = guard.assess("Show my tax number", explicit_passphrase="NilpferdOne")
    assert wrong_day.requires_passphrase is True
    assert wrong_day.authorized is False

"""Tests for the smart healer (history-aware healing)."""

import pytest

from ci_agent.heal.healer import Healer
from ci_agent.models import BuildRecord


def _record(failure_class: str, strategy: str, success: bool) -> BuildRecord:
    return BuildRecord(
        failure_class=failure_class,
        healing_strategy=strategy,
        healing_success=success,
        status="healed" if success else "failure",
    )


def test_healer_without_history_works_as_before():
    """Without history, healer uses default pattern matching."""
    healer = Healer()
    log = "ResolutionImpossible: Cannot install fastapi>=0.100"
    action = healer.diagnose(log)

    assert action.failure_class == "dependency-conflict"
    assert action.should_retry is True


def test_healer_with_history_still_classifies():
    """With history, healer still classifies failures correctly."""
    records = [_record("dependency-conflict", "clear-lockfile-retry", True)]
    healer = Healer(records=records)
    log = "ResolutionImpossible: Cannot install fastapi>=0.100"
    action = healer.diagnose(log)

    assert action.failure_class == "dependency-conflict"


def test_healer_notes_ineffective_strategy():
    """When default strategy is ineffective, healer adds a warning."""
    # Create history where clear-lockfile-retry consistently fails
    records = [
        _record("dependency-conflict", "clear-lockfile-retry", False),
        _record("dependency-conflict", "clear-lockfile-retry", False),
        _record("dependency-conflict", "clear-lockfile-retry", False),
        _record("dependency-conflict", "clear-lockfile-retry", False),
    ]
    healer = Healer(records=records)
    log = "ResolutionImpossible: Cannot install fastapi>=0.100"
    action = healer.diagnose(log)

    assert action.failure_class == "dependency-conflict"
    # Should mention low success rate in explanation
    assert "low success rate" in action.explanation or "Smart healing" in action.explanation


def test_healer_unknown_failure_unchanged():
    """Unknown failures are handled the same with or without history."""
    records = [_record("dependency-conflict", "clear-lockfile-retry", True)]
    healer = Healer(records=records)
    log = "Something completely unknown happened"
    action = healer.diagnose(log)

    assert action.failure_class == "unknown"
    assert action.should_retry is False


def test_healer_respects_max_retries():
    """Max retries still respected even with history."""
    healer = Healer()
    log = "FAILED tests/test_api.py::test_create_user - AssertionError"

    # test-failure has max_retries=1
    action = healer.diagnose(log, attempt=2)
    assert action.should_retry is False

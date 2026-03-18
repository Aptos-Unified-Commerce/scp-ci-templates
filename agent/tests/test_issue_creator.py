"""Tests for the auto-issue creator."""

import pytest

from ci_agent.heal.issue_creator import should_create_issue


def test_should_create_issue_recurring_low_success():
    assert should_create_issue(
        failure_class="dependency-conflict",
        total_attempts=5,
        success_rate=0.2,
    ) is True


def test_should_not_create_issue_high_success():
    assert should_create_issue(
        failure_class="dependency-conflict",
        total_attempts=5,
        success_rate=0.8,
    ) is False


def test_should_not_create_issue_too_few_attempts():
    assert should_create_issue(
        failure_class="dependency-conflict",
        total_attempts=2,
        success_rate=0.0,
    ) is False


def test_unknown_failures_flagged_faster():
    """Unknown failures trigger issue creation after just 2 attempts."""
    assert should_create_issue(
        failure_class="unknown",
        total_attempts=2,
        success_rate=0.0,
    ) is True


def test_boundary_exactly_min_attempts():
    assert should_create_issue(
        failure_class="test-failure",
        total_attempts=3,
        success_rate=0.3,
    ) is True


def test_boundary_exactly_max_success_rate():
    """At exactly 50% success rate, should NOT create issue (threshold is <0.5)."""
    assert should_create_issue(
        failure_class="test-failure",
        total_attempts=10,
        success_rate=0.5,
    ) is False


def test_custom_thresholds():
    assert should_create_issue(
        failure_class="test-failure",
        total_attempts=5,
        success_rate=0.6,
        min_attempts=5,
        max_success_rate=0.7,
    ) is True

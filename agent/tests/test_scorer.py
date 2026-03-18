"""Tests for the strategy scorer (closed-loop healing)."""

import pytest

from ci_agent.heal.scorer import StrategyScorer
from ci_agent.models import BuildRecord


def _record(failure_class: str, strategy: str, success: bool) -> BuildRecord:
    return BuildRecord(
        failure_class=failure_class,
        healing_strategy=strategy,
        healing_success=success,
        status="healed" if success else "failure",
    )


def test_new_strategy_gets_neutral_score():
    scorer = StrategyScorer([])
    assert scorer.score("dependency-conflict", "clear-lockfile") == 0.5


def test_successful_strategy_scores_high():
    records = [
        _record("dependency-conflict", "clear-lockfile", True),
        _record("dependency-conflict", "clear-lockfile", True),
        _record("dependency-conflict", "clear-lockfile", True),
    ]
    scorer = StrategyScorer(records)
    score = scorer.score("dependency-conflict", "clear-lockfile")
    assert score > 0.7


def test_failing_strategy_scores_low():
    records = [
        _record("test-failure", "retry-tests", False),
        _record("test-failure", "retry-tests", False),
        _record("test-failure", "retry-tests", False),
    ]
    scorer = StrategyScorer(records)
    score = scorer.score("test-failure", "retry-tests")
    assert score < 0.3


def test_rank_strategies():
    records = [
        _record("dependency-conflict", "clear-lockfile", True),
        _record("dependency-conflict", "clear-lockfile", True),
        _record("dependency-conflict", "reinstall-deps", False),
        _record("dependency-conflict", "reinstall-deps", False),
    ]
    scorer = StrategyScorer(records)
    ranked = scorer.rank_strategies(
        "dependency-conflict",
        ["clear-lockfile", "reinstall-deps"],
    )
    assert ranked[0][0] == "clear-lockfile"
    assert ranked[1][0] == "reinstall-deps"


def test_best_strategy():
    records = [
        _record("oom", "reduce-parallelism", True),
        _record("oom", "reduce-parallelism", True),
        _record("oom", "prune-and-retry", False),
    ]
    scorer = StrategyScorer(records)
    best = scorer.best_strategy("oom", ["reduce-parallelism", "prune-and-retry"])
    assert best == "reduce-parallelism"


def test_is_strategy_ineffective():
    records = [
        _record("test-failure", "retry-tests", False),
        _record("test-failure", "retry-tests", False),
        _record("test-failure", "retry-tests", False),
        _record("test-failure", "retry-tests", False),  # 0/4 = 0%
    ]
    scorer = StrategyScorer(records)
    assert scorer.is_strategy_ineffective("test-failure", "retry-tests") is True


def test_is_strategy_not_ineffective_with_few_attempts():
    records = [
        _record("test-failure", "retry-tests", False),
    ]
    scorer = StrategyScorer(records)
    # Only 1 attempt — not enough data
    assert scorer.is_strategy_ineffective("test-failure", "retry-tests") is False


def test_get_recurring_failures():
    records = [
        _record("dependency-conflict", "clear-lockfile", False),
        _record("dependency-conflict", "clear-lockfile", False),
        _record("dependency-conflict", "clear-lockfile", False),
        _record("test-failure", "retry-tests", True),
        _record("test-failure", "retry-tests", True),
        _record("test-failure", "retry-tests", True),
    ]
    scorer = StrategyScorer(records)
    recurring = scorer.get_recurring_failures(min_occurrences=3)

    assert len(recurring) == 2
    # dependency-conflict should be first (worst success rate)
    assert recurring[0]["failure_class"] == "dependency-conflict"
    assert recurring[0]["needs_permanent_fix"] is True
    assert recurring[1]["failure_class"] == "test-failure"
    assert recurring[1]["needs_permanent_fix"] is False


def test_summary():
    records = [
        _record("oom", "reduce-parallelism", True),
        _record("oom", "reduce-parallelism", False),
    ]
    scorer = StrategyScorer(records)
    s = scorer.summary()
    assert "oom" in s
    assert s["oom"]["reduce-parallelism"]["attempts"] == 2
    assert s["oom"]["reduce-parallelism"]["successes"] == 1

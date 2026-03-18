"""Derive insights from build history."""

from __future__ import annotations

from collections import Counter

from ci_agent.models import BuildRecord


def avg_build_time(records: list[BuildRecord]) -> float:
    """Average build duration in seconds."""
    times = [r.duration_seconds for r in records if r.duration_seconds > 0]
    return sum(times) / len(times) if times else 0.0


def failure_rate(records: list[BuildRecord]) -> float:
    """Proportion of builds that failed (not healed)."""
    if not records:
        return 0.0
    failures = sum(1 for r in records if r.status == "failure")
    return failures / len(records)


def top_failure_classes(records: list[BuildRecord], n: int = 5) -> list[tuple[str, int]]:
    """Most common failure classifications."""
    classes = [r.failure_class for r in records if r.failure_class]
    return Counter(classes).most_common(n)


def build_time_trend(records: list[BuildRecord], window: int = 10) -> str:
    """Compare recent build times to older ones. Returns 'improving', 'stable', or 'degrading'."""
    times = [r.duration_seconds for r in records if r.duration_seconds > 0]
    if len(times) < window * 2:
        return "stable"

    recent = times[-window:]
    older = times[-window * 2 : -window]

    avg_recent = sum(recent) / len(recent)
    avg_older = sum(older) / len(older)

    ratio = avg_recent / avg_older if avg_older > 0 else 1.0

    if ratio < 0.85:
        return "improving"
    elif ratio > 1.15:
        return "degrading"
    return "stable"


def detect_flaky_tests(records: list[BuildRecord]) -> list[str]:
    """Identify tests that appear in failures intermittently.

    A test is considered flaky if it appears in failure_class == 'test-flaky'
    or if the same branch alternates between success and failure.
    """
    flaky: set[str] = []

    # Check for branches that alternate between success and failure
    branch_results: dict[str, list[str]] = {}
    for r in records:
        branch_results.setdefault(r.branch, []).append(r.status)

    flaky_branches = []
    for branch, statuses in branch_results.items():
        if len(statuses) >= 4:
            # Check for alternating pattern
            alternations = sum(
                1 for i in range(1, len(statuses)) if statuses[i] != statuses[i - 1]
            )
            if alternations >= len(statuses) * 0.4:
                flaky_branches.append(branch)

    return flaky_branches


def healing_effectiveness(records: list[BuildRecord]) -> dict[str, float]:
    """Success rate of each healing strategy."""
    strategy_results: dict[str, list[bool]] = {}

    for r in records:
        if r.healing_strategy and r.healing_success is not None:
            strategy_results.setdefault(r.healing_strategy, []).append(r.healing_success)

    return {
        strategy: sum(results) / len(results)
        for strategy, results in strategy_results.items()
        if results
    }

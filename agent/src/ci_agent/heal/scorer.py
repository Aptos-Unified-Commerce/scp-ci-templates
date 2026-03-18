"""Strategy scoring — learns from build history to rank healing strategies.

Instead of always using the first matching strategy, the scorer ranks strategies
by their historical success rate for a given failure class. This creates a
closed feedback loop: every healed (or not healed) build updates the scores,
and future builds use better strategies first.

Scoring model:
  score = (successes + 1) / (total_attempts + 2)  # Laplace smoothing

  - New strategies get a neutral score of 0.5 (benefit of the doubt)
  - Strategies that consistently fail drop toward 0.0
  - Strategies that consistently work rise toward 1.0
"""

from __future__ import annotations

from collections import defaultdict

from ci_agent.models import BuildRecord


class StrategyScorer:
    """Scores healing strategies based on historical effectiveness."""

    def __init__(self, records: list[BuildRecord] | None = None) -> None:
        # {failure_class: {strategy: [success, success, fail, ...]}}
        self._history: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
        if records:
            self._load_from_records(records)

    def _load_from_records(self, records: list[BuildRecord]) -> None:
        """Build scoring model from build history."""
        for r in records:
            if r.failure_class and r.healing_strategy and r.healing_success is not None:
                self._history[r.failure_class][r.healing_strategy].append(r.healing_success)

    def score(self, failure_class: str, strategy: str) -> float:
        """Get the effectiveness score for a strategy on a failure class.

        Returns 0.0-1.0. Uses Laplace smoothing so new strategies start at 0.5.
        """
        attempts = self._history.get(failure_class, {}).get(strategy, [])
        if not attempts:
            return 0.5  # No data — neutral score
        successes = sum(1 for a in attempts if a)
        return (successes + 1) / (len(attempts) + 2)

    def rank_strategies(self, failure_class: str, candidates: list[str]) -> list[tuple[str, float]]:
        """Rank candidate strategies by score (highest first).

        Returns list of (strategy_name, score) tuples.
        """
        scored = [(s, self.score(failure_class, s)) for s in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def best_strategy(self, failure_class: str, candidates: list[str]) -> str | None:
        """Return the highest-scoring strategy, or None if no candidates."""
        ranked = self.rank_strategies(failure_class, candidates)
        return ranked[0][0] if ranked else None

    def is_strategy_ineffective(self, failure_class: str, strategy: str, threshold: float = 0.25) -> bool:
        """Check if a strategy has been tried enough and has a low success rate.

        Returns True if there are 3+ attempts and success rate is below threshold.
        """
        attempts = self._history.get(failure_class, {}).get(strategy, [])
        if len(attempts) < 3:
            return False  # Not enough data
        success_rate = sum(1 for a in attempts if a) / len(attempts)
        return success_rate < threshold

    def get_recurring_failures(self, min_occurrences: int = 3) -> list[dict]:
        """Find failure classes that keep recurring despite healing attempts.

        Returns list of {failure_class, total_attempts, success_rate, strategies_tried}.
        """
        recurring = []
        for failure_class, strategies in self._history.items():
            total_attempts = sum(len(attempts) for attempts in strategies.values())
            total_successes = sum(
                sum(1 for a in attempts if a)
                for attempts in strategies.values()
            )

            if total_attempts >= min_occurrences:
                success_rate = total_successes / total_attempts if total_attempts > 0 else 0.0
                recurring.append({
                    "failure_class": failure_class,
                    "total_attempts": total_attempts,
                    "success_rate": success_rate,
                    "strategies_tried": list(strategies.keys()),
                    "needs_permanent_fix": success_rate < 0.5,
                })

        # Sort by success rate (worst first)
        recurring.sort(key=lambda x: x["success_rate"])
        return recurring

    def summary(self) -> dict:
        """Full scoring summary for all failure classes and strategies."""
        result = {}
        for failure_class, strategies in self._history.items():
            result[failure_class] = {}
            for strategy, attempts in strategies.items():
                successes = sum(1 for a in attempts if a)
                result[failure_class][strategy] = {
                    "attempts": len(attempts),
                    "successes": successes,
                    "score": self.score(failure_class, strategy),
                }
        return result

"""Main healing orchestrator — diagnoses failures and prescribes actions.

Smart healing: uses build history to rank strategies by effectiveness.
If a strategy has been tried 3+ times with <25% success rate for a
given failure class, it is deprioritized and alternatives are tried first.
"""

from __future__ import annotations

from ci_agent.heal.scorer import StrategyScorer
from ci_agent.heal.strategies import FAILURE_PATTERNS, classify_failure
from ci_agent.models import BuildRecord, HealingAction


class Healer:
    """Diagnoses build failures and returns healing actions.

    When build history is provided, the healer uses strategy scoring
    to pick the most effective strategy (closed-loop learning).
    Without history, it falls back to the default pattern-match order.
    """

    def __init__(self, records: list[BuildRecord] | None = None) -> None:
        self.scorer = StrategyScorer(records) if records else None

    def diagnose(self, log_content: str, attempt: int = 1) -> HealingAction:
        """Analyze log content and return a healing action.

        Args:
            log_content: The build log output.
            attempt: Current retry attempt (1-based). Beyond max_retries, no retry.
        """
        pattern = classify_failure(log_content)

        if pattern is None:
            return HealingAction(
                failure_class="unknown",
                strategy="none",
                explanation="Could not classify the failure. Manual investigation required.",
                should_retry=False,
            )

        # If we have history, check if the default strategy is ineffective
        # and try to find a better one
        chosen_pattern = pattern
        explanation_suffix = ""

        if self.scorer:
            # Check if the matched strategy is known to be ineffective
            if self.scorer.is_strategy_ineffective(pattern.name, pattern.strategy):
                # Try to find an alternative strategy from other patterns
                # that match the same failure class
                alternative = self._find_alternative_strategy(pattern.name, pattern.strategy)
                if alternative:
                    chosen_pattern = alternative
                    explanation_suffix = (
                        f" (Smart healing: default strategy '{pattern.strategy}' has low success rate "
                        f"for '{pattern.name}' — trying '{alternative.strategy}' instead)"
                    )
                else:
                    explanation_suffix = (
                        f" (Warning: strategy '{pattern.strategy}' has low success rate "
                        f"for '{pattern.name}' but no alternative available)"
                    )

        should_retry = attempt <= chosen_pattern.max_retries

        return HealingAction(
            failure_class=chosen_pattern.name,
            strategy=chosen_pattern.strategy,
            retry_env=chosen_pattern.retry_env,
            retry_commands=chosen_pattern.retry_commands,
            explanation=chosen_pattern.explanation + explanation_suffix,
            should_retry=should_retry,
            needs_code_fix=not should_retry and chosen_pattern.name in ("dependency-conflict", "import-error"),
        )

    def _find_alternative_strategy(self, failure_class: str, current_strategy: str) -> object | None:
        """Find an alternative pattern with a different strategy for the same failure class.

        Looks through all patterns that match the same failure class name
        but have a different strategy, and returns the one with the best score.
        """
        candidates = []
        for p in FAILURE_PATTERNS:
            if p.name == failure_class and p.strategy != current_strategy:
                candidates.append(p)

        if not candidates or not self.scorer:
            return None

        # Score candidates and return the best
        best = None
        best_score = -1.0
        for p in candidates:
            score = self.scorer.score(failure_class, p.strategy)
            if score > best_score:
                best_score = score
                best = p

        return best

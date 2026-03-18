"""Main healing orchestrator — diagnoses failures and prescribes actions."""

from __future__ import annotations

from ci_agent.heal.strategies import classify_failure
from ci_agent.models import HealingAction


class Healer:
    """Diagnoses build failures and returns healing actions."""

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

        should_retry = attempt <= pattern.max_retries

        return HealingAction(
            failure_class=pattern.name,
            strategy=pattern.strategy,
            retry_env=pattern.retry_env,
            retry_commands=pattern.retry_commands,
            explanation=pattern.explanation,
            should_retry=should_retry,
            needs_code_fix=not should_retry and pattern.name in ("dependency-conflict", "import-error"),
        )

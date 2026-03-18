"""Auto-create GitHub issues for recurring build failures.

When the same failure class hits 3+ times and healing doesn't permanently
fix it, this module creates a GitHub issue with full context so the team
can investigate the root cause.

Deduplication: checks for existing open issues with the same label before
creating a new one. Won't spam the repo.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess

logger = logging.getLogger(__name__)

ISSUE_LABEL = "ci-recurring-failure"


def should_create_issue(
    failure_class: str,
    total_attempts: int,
    success_rate: float,
    min_attempts: int = 3,
    max_success_rate: float = 0.5,
) -> bool:
    """Determine if a recurring failure warrants an auto-created issue.

    Args:
        failure_class: The failure classification.
        total_attempts: Total healing attempts for this failure class.
        success_rate: Proportion of successful healings (0.0-1.0).
        min_attempts: Minimum attempts before considering an issue.
        max_success_rate: Create issue if success rate is below this.
    """
    if failure_class == "unknown":
        return total_attempts >= 2  # Unknown failures get flagged faster
    return total_attempts >= min_attempts and success_rate < max_success_rate


def create_recurring_failure_issue(
    failure_class: str,
    total_attempts: int,
    success_rate: float,
    strategies_tried: list[str],
    recent_branches: list[str] | None = None,
) -> str | None:
    """Create a GitHub issue for a recurring failure.

    Returns the issue URL if created, None if skipped or failed.
    Requires `gh` CLI and GITHUB_TOKEN to be available.
    """
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repo:
        logger.info("GITHUB_TOKEN or GITHUB_REPOSITORY not set — skipping issue creation")
        return None

    # Check for existing open issue to avoid duplicates
    if _has_existing_issue(failure_class, token):
        logger.info("Open issue already exists for '%s' — skipping", failure_class)
        return None

    title = f"Recurring CI failure: {failure_class} ({total_attempts} attempts, {success_rate:.0%} heal rate)"

    body = _build_issue_body(
        failure_class=failure_class,
        total_attempts=total_attempts,
        success_rate=success_rate,
        strategies_tried=strategies_tried,
        recent_branches=recent_branches,
        repo=repo,
    )

    try:
        result = subprocess.run(
            [
                "gh", "issue", "create",
                "--title", title,
                "--body", body,
                "--label", ISSUE_LABEL,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "GH_TOKEN": token},
        )

        if result.returncode == 0:
            issue_url = result.stdout.strip()
            logger.info("Created issue: %s", issue_url)
            return issue_url

        # Label might not exist — create it and retry
        if "label" in result.stderr.lower() and "not found" in result.stderr.lower():
            _create_label(token)
            result = subprocess.run(
                [
                    "gh", "issue", "create",
                    "--title", title,
                    "--body", body,
                    "--label", ISSUE_LABEL,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "GH_TOKEN": token},
            )
            if result.returncode == 0:
                issue_url = result.stdout.strip()
                logger.info("Created issue (after label creation): %s", issue_url)
                return issue_url

        logger.error("Failed to create issue: %s", result.stderr.strip())
        return None

    except subprocess.TimeoutExpired:
        logger.error("Timed out creating issue")
        return None
    except Exception as exc:
        logger.error("Error creating issue: %s", exc)
        return None


def _has_existing_issue(failure_class: str, token: str) -> bool:
    """Check if there's already an open issue for this failure class."""
    try:
        result = subprocess.run(
            [
                "gh", "issue", "list",
                "--label", ISSUE_LABEL,
                "--state", "open",
                "--search", f"Recurring CI failure: {failure_class}",
                "--json", "number",
                "--limit", "1",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "GH_TOKEN": token},
        )
        if result.returncode == 0 and result.stdout.strip():
            issues = json.loads(result.stdout)
            return len(issues) > 0
    except Exception:
        pass
    return False


def _create_label(token: str) -> None:
    """Create the ci-recurring-failure label if it doesn't exist."""
    try:
        subprocess.run(
            [
                "gh", "label", "create", ISSUE_LABEL,
                "--description", "Auto-created by CI Agent for recurring build failures",
                "--color", "d93f0b",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "GH_TOKEN": token},
        )
    except Exception:
        pass


def _build_issue_body(
    failure_class: str,
    total_attempts: int,
    success_rate: float,
    strategies_tried: list[str],
    recent_branches: list[str] | None,
    repo: str,
) -> str:
    strategies_md = "\n".join(f"- `{s}`" for s in strategies_tried) if strategies_tried else "- None"
    branches_md = "\n".join(f"- `{b}`" for b in (recent_branches or [])) if recent_branches else "- N/A"

    run_id = os.environ.get("GITHUB_RUN_ID", "N/A")
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}" if run_id != "N/A" else "N/A"

    return f"""## Recurring CI Failure Detected

The CI Agent has detected a recurring build failure that self-healing has not been able to permanently resolve.

### Failure Details

| | |
|---|---|
| **Failure class** | `{failure_class}` |
| **Total healing attempts** | {total_attempts} |
| **Healing success rate** | {success_rate:.0%} |
| **Latest run** | [Run #{run_id}]({run_url}) |

### Healing Strategies Tried

{strategies_md}

### Affected Branches

{branches_md}

### What This Means

The CI pipeline has attempted to auto-heal this failure **{total_attempts} times** with a success rate of only **{success_rate:.0%}**. This indicates the root cause needs a permanent fix rather than retry-based healing.

### Suggested Actions

1. Review the [latest build logs]({run_url}) for the full error output
2. Identify the root cause of the `{failure_class}` failure
3. Apply a permanent fix (code change, dependency update, config fix)
4. Close this issue once the fix is verified

---
_This issue was auto-created by the CI Agent. It will not create duplicate issues while this one is open._
"""

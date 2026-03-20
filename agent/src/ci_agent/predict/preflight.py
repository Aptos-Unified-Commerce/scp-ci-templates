"""Predictive failure model — pre-flight checks before running the full build.

Uses build history to predict whether this build is likely to fail, and
what the most probable failure class would be. If risk is high, it can
suggest pre-emptive fixes before wasting CI time.

Model: lightweight heuristic-based (no ML training needed).
Features: recent failure rate, time patterns, file change patterns,
dependency staleness, branch health.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ci_agent.models import BuildRecord


@dataclass
class PredictionResult:
    """Output of the pre-flight prediction."""

    risk_level: str = "low"  # low, medium, high
    risk_score: float = 0.0  # 0.0-1.0
    predicted_failure: str | None = None  # Most likely failure class
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "predicted_failure": self.predicted_failure,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
        }

    def to_markdown(self) -> str:
        icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(self.risk_level, "⚪")
        lines = [
            f"### Pre-Flight Check: {icon} {self.risk_level.upper()} risk ({self.risk_score:.0%})\n",
        ]
        if self.predicted_failure:
            lines.append(f"**Most likely failure:** `{self.predicted_failure}`\n")
        if self.warnings:
            lines.append("**Warnings:**")
            for w in self.warnings:
                lines.append(f"- {w}")
            lines.append("")
        if self.suggestions:
            lines.append("**Suggestions:**")
            for s in self.suggestions:
                lines.append(f"- {s}")
        return "\n".join(lines)


class PreflightPredictor:
    """Predicts build failure risk before running the build."""

    def __init__(self, records: list[BuildRecord], repo_path: str = ".") -> None:
        self.records = records
        self.repo_path = Path(repo_path)

    def predict(self) -> PredictionResult:
        """Run all pre-flight checks and produce a risk assessment."""
        result = PredictionResult()
        risk_factors: list[float] = []

        # Check 1: Recent failure rate on this branch
        branch_risk = self._check_branch_health()
        if branch_risk:
            risk_factors.append(branch_risk["score"])
            result.warnings.append(branch_risk["warning"])
            if branch_risk.get("suggestion"):
                result.suggestions.append(branch_risk["suggestion"])

        # Check 2: Recurring failure patterns
        recurring_risk = self._check_recurring_failures()
        if recurring_risk:
            risk_factors.append(recurring_risk["score"])
            result.warnings.append(recurring_risk["warning"])
            result.predicted_failure = recurring_risk.get("predicted_class")
            if recurring_risk.get("suggestion"):
                result.suggestions.append(recurring_risk["suggestion"])

        # Check 3: Dependency freshness (stale lockfile)
        dep_risk = self._check_dependency_staleness()
        if dep_risk:
            risk_factors.append(dep_risk["score"])
            result.warnings.append(dep_risk["warning"])
            if dep_risk.get("suggestion"):
                result.suggestions.append(dep_risk["suggestion"])

        # Check 4: Large changeset
        change_risk = self._check_changeset_size()
        if change_risk:
            risk_factors.append(change_risk["score"])
            result.warnings.append(change_risk["warning"])

        # Check 5: Recently failed files
        file_risk = self._check_changed_files_history()
        if file_risk:
            risk_factors.append(file_risk["score"])
            result.warnings.append(file_risk["warning"])

        # Aggregate risk
        if risk_factors:
            result.risk_score = min(1.0, sum(risk_factors) / len(risk_factors) + max(risk_factors) * 0.3)
        else:
            result.risk_score = 0.1  # Baseline low risk

        if result.risk_score >= 0.7:
            result.risk_level = "high"
        elif result.risk_score >= 0.4:
            result.risk_level = "medium"
        else:
            result.risk_level = "low"

        if not result.suggestions:
            result.suggestions.append("No pre-emptive action needed — build looks healthy.")

        return result

    def _check_branch_health(self) -> dict | None:
        """Check recent failure rate on the current branch."""
        branch = os.environ.get("GITHUB_REF_NAME", "")
        if not branch:
            return None

        branch_records = [r for r in self.records[-20:] if r.branch == branch]
        if len(branch_records) < 3:
            return None

        failures = sum(1 for r in branch_records if r.status == "failure")
        rate = failures / len(branch_records)

        if rate > 0.5:
            return {
                "score": rate,
                "warning": f"Branch `{branch}` has {rate:.0%} failure rate in last {len(branch_records)} builds",
                "suggestion": f"Consider investigating existing failures on `{branch}` before pushing more changes",
            }
        return None

    def _check_recurring_failures(self) -> dict | None:
        """Check for failure patterns that keep recurring."""
        from collections import Counter

        recent_failures = [
            r.failure_class for r in self.records[-30:]
            if r.failure_class and r.status in ("failure", "healed")
        ]
        if not recent_failures:
            return None

        most_common = Counter(recent_failures).most_common(1)[0]
        failure_class, count = most_common

        if count >= 3:
            return {
                "score": min(1.0, count / 5),
                "warning": f"`{failure_class}` has occurred {count} times in recent builds",
                "predicted_class": failure_class,
                "suggestion": f"Pre-emptive fix: address `{failure_class}` root cause before building",
            }
        return None

    def _check_dependency_staleness(self) -> dict | None:
        """Check if lockfile is very old compared to pyproject.toml."""
        pyproject = self.repo_path / "pyproject.toml"
        lockfile = self.repo_path / "uv.lock"

        if not pyproject.exists() or not lockfile.exists():
            return None

        pyproject_mtime = pyproject.stat().st_mtime
        lock_mtime = lockfile.stat().st_mtime

        # If pyproject.toml is newer than lockfile by more than 7 days
        diff_days = (pyproject_mtime - lock_mtime) / 86400
        if diff_days > 7:
            return {
                "score": min(1.0, diff_days / 30),
                "warning": f"Lockfile is {diff_days:.0f} days older than pyproject.toml — deps may be stale",
                "suggestion": "Run `uv lock` to refresh dependency resolution before building",
            }
        return None

    def _check_changeset_size(self) -> dict | None:
        """Check if the current changeset is unusually large."""
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", "HEAD~1", "HEAD"],
                capture_output=True, text=True, cwd=self.repo_path, timeout=10,
            )
            if result.returncode != 0:
                return None

            lines = result.stdout.strip().splitlines()
            if not lines:
                return None

            # Last line has summary: "X files changed, Y insertions(+), Z deletions(-)"
            summary = lines[-1]
            import re
            m = re.search(r"(\d+) files? changed", summary)
            files_changed = int(m.group(1)) if m else 0

            if files_changed > 20:
                return {
                    "score": min(1.0, files_changed / 50),
                    "warning": f"Large changeset: {files_changed} files changed in last commit",
                }
        except Exception:
            pass
        return None

    def _check_changed_files_history(self) -> dict | None:
        """Check if recently changed files have a history of causing failures."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                capture_output=True, text=True, cwd=self.repo_path, timeout=10,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None

            changed_files = set(result.stdout.strip().splitlines())

            # Check if any of these files appeared in recent failure logs
            # (simplified: check if test files were changed while tests have been failing)
            test_files = {f for f in changed_files if "test" in f.lower()}
            recent_test_failures = sum(
                1 for r in self.records[-10:]
                if r.failure_class in ("test-failure", "test-flaky")
            )

            if test_files and recent_test_failures >= 2:
                return {
                    "score": 0.5,
                    "warning": f"Test files changed ({len(test_files)} files) while tests have been failing recently",
                }
        except Exception:
            pass
        return None

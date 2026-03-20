"""PR review agent — analyzes diffs for issues before merging.

Reviews pull request diffs for:
  - Breaking API changes (removed/renamed public functions, changed signatures)
  - Missing tests for new code
  - Security issues (hardcoded secrets, SQL injection patterns, unsafe eval)
  - Dependency changes (new deps added, major version bumps)
  - Large file additions (binaries, generated code)

Can run as a heuristic-only check or with optional LLM-powered deep review.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ReviewFinding:
    """A single finding from the PR review."""

    category: str  # breaking-change, missing-test, security, dependency, size
    severity: str  # error, warning, info
    file: str
    line: int = 0
    message: str = ""


@dataclass
class ReviewResult:
    """Output of the PR review."""

    findings: list[ReviewFinding] = field(default_factory=list)
    summary: str = ""
    approved: bool = True  # False if any errors found

    def to_dict(self) -> dict:
        return {
            "findings": [
                {"category": f.category, "severity": f.severity, "file": f.file,
                 "line": f.line, "message": f.message}
                for f in self.findings
            ],
            "summary": self.summary,
            "approved": self.approved,
            "error_count": sum(1 for f in self.findings if f.severity == "error"),
            "warning_count": sum(1 for f in self.findings if f.severity == "warning"),
        }

    def to_markdown(self) -> str:
        errors = [f for f in self.findings if f.severity == "error"]
        warnings = [f for f in self.findings if f.severity == "warning"]
        infos = [f for f in self.findings if f.severity == "info"]

        status = "APPROVED" if self.approved else "CHANGES REQUESTED"
        icon = "✅" if self.approved else "❌"

        lines = [f"### PR Review: {icon} {status}\n"]

        if self.summary:
            lines.append(f"{self.summary}\n")

        if errors:
            lines.append("#### Errors (must fix)")
            for f in errors:
                loc = f"`{f.file}:{f.line}`" if f.line else f"`{f.file}`"
                lines.append(f"- **[{f.category}]** {loc} — {f.message}")
            lines.append("")

        if warnings:
            lines.append("#### Warnings")
            for f in warnings:
                loc = f"`{f.file}:{f.line}`" if f.line else f"`{f.file}`"
                lines.append(f"- **[{f.category}]** {loc} — {f.message}")
            lines.append("")

        if infos:
            lines.append("#### Info")
            for f in infos:
                lines.append(f"- **[{f.category}]** `{f.file}` — {f.message}")

        if not self.findings:
            lines.append("No issues found. Looks good!")

        return "\n".join(lines)


class PRReviewer:
    """Reviews PR diffs for common issues."""

    def __init__(self, repo_path: str = ".", base_ref: str = "main") -> None:
        self.repo_path = Path(repo_path)
        self.base_ref = base_ref

    def review(self) -> ReviewResult:
        """Run all review checks on the current diff."""
        result = ReviewResult()

        diff = self._get_diff()
        if not diff:
            result.summary = "No diff found — nothing to review."
            return result

        changed_files = self._get_changed_files()

        self._check_breaking_changes(diff, changed_files, result)
        self._check_missing_tests(changed_files, result)
        self._check_security(diff, result)
        self._check_dependency_changes(diff, changed_files, result)
        self._check_large_files(changed_files, result)

        errors = sum(1 for f in result.findings if f.severity == "error")
        warnings = sum(1 for f in result.findings if f.severity == "warning")

        result.approved = errors == 0
        result.summary = f"Found {errors} error(s) and {warnings} warning(s) across {len(changed_files)} changed files."

        return result

    def _get_diff(self) -> str:
        """Get the diff between base and HEAD."""
        try:
            result = subprocess.run(
                ["git", "diff", f"{self.base_ref}...HEAD"],
                capture_output=True, text=True, cwd=self.repo_path, timeout=30,
            )
            return result.stdout if result.returncode == 0 else ""
        except Exception:
            return ""

    def _get_changed_files(self) -> list[str]:
        """Get list of changed files."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{self.base_ref}...HEAD"],
                capture_output=True, text=True, cwd=self.repo_path, timeout=15,
            )
            if result.returncode == 0:
                return [f for f in result.stdout.strip().splitlines() if f]
        except Exception:
            pass
        return []

    def _check_breaking_changes(self, diff: str, files: list[str], result: ReviewResult) -> None:
        """Check for removed or renamed public functions/classes."""
        py_files = [f for f in files if f.endswith(".py")]

        for line in diff.splitlines():
            # Removed function definitions
            if line.startswith("-") and not line.startswith("---"):
                if re.match(r"-\s*def [a-z]\w+\(", line) and not line.strip().startswith("-    def _"):
                    func_name = re.search(r"def (\w+)", line)
                    if func_name:
                        result.findings.append(ReviewFinding(
                            category="breaking-change",
                            severity="warning",
                            file="",
                            message=f"Public function `{func_name.group(1)}` appears to be removed",
                        ))

                # Removed class definitions
                if re.match(r"-\s*class [A-Z]\w+", line):
                    class_name = re.search(r"class (\w+)", line)
                    if class_name:
                        result.findings.append(ReviewFinding(
                            category="breaking-change",
                            severity="warning",
                            file="",
                            message=f"Public class `{class_name.group(1)}` appears to be removed",
                        ))

    def _check_missing_tests(self, files: list[str], result: ReviewResult) -> None:
        """Check if new source files have corresponding tests."""
        src_files = [f for f in files if f.startswith("src/") and f.endswith(".py") and "__init__" not in f]
        test_files = [f for f in files if "test" in f.lower() and f.endswith(".py")]

        if src_files and not test_files:
            result.findings.append(ReviewFinding(
                category="missing-test",
                severity="warning",
                file=src_files[0],
                message=f"{len(src_files)} source file(s) changed but no test files modified",
            ))

    def _check_security(self, diff: str, result: ReviewResult) -> None:
        """Check diff for security anti-patterns."""
        patterns = [
            (r"\+.*(?:password|secret|api_key|token)\s*=\s*['\"][^'\"]{8,}", "Possible hardcoded credential"),
            (r"\+.*eval\s*\(", "Use of `eval()` — potential code injection"),
            (r"\+.*exec\s*\(", "Use of `exec()` — potential code injection"),
            (r"\+.*\bpickle\.loads?\b", "Use of `pickle.load` — deserialization vulnerability"),
            (r"\+.*AKIA[0-9A-Z]{16}", "AWS Access Key ID in code"),
            (r"\+.*-----BEGIN.*PRIVATE KEY-----", "Private key in code"),
            (r"\+.*subprocess\.call\(.*shell\s*=\s*True", "Shell injection risk with `subprocess.call(shell=True)`"),
        ]

        for i, line in enumerate(diff.splitlines()):
            if not line.startswith("+") or line.startswith("+++"):
                continue
            for pattern, message in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    result.findings.append(ReviewFinding(
                        category="security",
                        severity="error",
                        file="",
                        line=0,
                        message=message,
                    ))
                    break

    def _check_dependency_changes(self, diff: str, files: list[str], result: ReviewResult) -> None:
        """Check for dependency additions or major version bumps."""
        dep_files = [f for f in files if f in ("pyproject.toml", "requirements.txt", "package.json")]
        if not dep_files:
            return

        # Count added dependencies
        new_deps = []
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                # Python deps
                m = re.match(r'\+\s*"([a-zA-Z0-9_-]+)', line)
                if m and m.group(1) not in ("pytest", "pytest-cov", "pytest-mock"):
                    new_deps.append(m.group(1))

        if len(new_deps) > 3:
            result.findings.append(ReviewFinding(
                category="dependency",
                severity="info",
                file=dep_files[0],
                message=f"{len(new_deps)} new dependencies added: {', '.join(new_deps[:5])}",
            ))

    def _check_large_files(self, files: list[str], result: ReviewResult) -> None:
        """Check for large files being added."""
        for f in files:
            path = self.repo_path / f
            if path.exists() and path.stat().st_size > 1_000_000:
                size_mb = path.stat().st_size / 1_000_000
                result.findings.append(ReviewFinding(
                    category="size",
                    severity="warning",
                    file=f,
                    message=f"Large file ({size_mb:.1f}MB) — consider if this should be in git",
                ))


def review_with_llm(diff: str, heuristic_result: ReviewResult) -> str | None:
    """Optional: ask Claude to do a deeper review of the PR diff.

    Only activates when ANTHROPIC_API_KEY is set.
    """
    from ci_agent.llm.advisor import is_available

    if not is_available():
        return None

    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()

    # Truncate diff to ~3000 lines
    diff_lines = diff.splitlines()
    truncated = "\n".join(diff_lines[:3000])

    heuristic_summary = heuristic_result.to_markdown()

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""You are reviewing a pull request. The automated checks found these issues:

{heuristic_summary}

Now review the diff yourself for anything the automated checks missed:
- Business logic bugs
- Edge cases not handled
- Error handling gaps
- Performance concerns
- API design issues

Be concise. Only flag real issues, not style preferences. Max 5 findings.

```diff
{truncated}
```""",
        }],
    )

    return message.content[0].text

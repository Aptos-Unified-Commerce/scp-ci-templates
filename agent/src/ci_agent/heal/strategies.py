"""Failure pattern catalog and healing strategies."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class FailurePattern:
    """A known failure pattern with its healing strategy."""

    name: str
    patterns: list[str]  # Regex patterns to match against log output
    strategy: str
    explanation: str
    retry_commands: list[str]
    retry_env: dict[str, str]
    max_retries: int = 2


# Ordered by specificity — first match wins
FAILURE_PATTERNS: list[FailurePattern] = [
    FailurePattern(
        name="dependency-conflict",
        patterns=[
            r"ResolutionImpossible",
            r"Could not find a version that satisfies",
            r"No matching distribution found",
            r"CONFLICTING DEPENDENCIES",
            r"version solving failed",
        ],
        strategy="clear-lockfile-retry",
        explanation="Dependency resolution failed. Clearing lockfile and retrying with fresh resolution.",
        retry_commands=["rm -f uv.lock", "rm -f package-lock.json", "rm -f yarn.lock"],
        retry_env={"UV_RESOLUTION": "lowest-direct"},
    ),
    FailurePattern(
        name="test-flaky",
        patterns=[
            r"FAILED.*(?:timeout|Timeout|TIMEOUT)",
            r"flaky",
            r"intermittent",
        ],
        strategy="retry-failed-only",
        explanation="Detected likely flaky test. Retrying only failed tests.",
        retry_commands=[],
        retry_env={"PYTEST_ADDOPTS": "--lf --timeout=120"},
    ),
    FailurePattern(
        name="test-failure",
        patterns=[
            r"FAILED\s+tests?/",
            r"AssertionError",
            r"AssertError",
            r"FAIL\s+\S+_test\.go",
            r"Test failed",
        ],
        strategy="retry-tests",
        explanation="Test failure detected. Retrying test suite.",
        retry_commands=[],
        retry_env={},
        max_retries=1,
    ),
    FailurePattern(
        name="network-timeout",
        patterns=[
            r"timeout",
            r"timed out",
            r"ETIMEDOUT",
            r"ECONNREFUSED",
            r"ECONNRESET",
            r"ConnectionResetError",
            r"ReadTimeoutError",
        ],
        strategy="retry-with-timeout",
        explanation="Network timeout detected. Retrying with extended timeouts.",
        retry_commands=[],
        retry_env={"PIP_TIMEOUT": "120", "UV_HTTP_TIMEOUT": "120"},
    ),
    FailurePattern(
        name="rate-limit",
        patterns=[
            r"rate limit",
            r"429",
            r"Too Many Requests",
            r"RateLimitExceeded",
        ],
        strategy="backoff-retry",
        explanation="Rate limit hit. Waiting and retrying.",
        retry_commands=["sleep 30"],
        retry_env={},
    ),
    FailurePattern(
        name="disk-space",
        patterns=[
            r"No space left on device",
            r"ENOSPC",
            r"out of disk space",
        ],
        strategy="prune-and-retry",
        explanation="Disk space exhausted. Pruning caches and retrying.",
        retry_commands=[
            "docker system prune -af 2>/dev/null || true",
            "pip cache purge 2>/dev/null || true",
            "rm -rf /tmp/pip-* 2>/dev/null || true",
        ],
        retry_env={},
    ),
    FailurePattern(
        name="auth-failure",
        patterns=[
            r"Permission denied",
            r"403 Forbidden",
            r"401 Unauthorized",
            r"AuthorizationError",
            r"ExpiredToken",
            r"InvalidIdentityToken",
        ],
        strategy="refresh-credentials",
        explanation="Authentication/authorization failure. Refreshing credentials and retrying.",
        retry_commands=[],
        retry_env={"CI_AGENT_REFRESH_CREDS": "true"},
    ),
    FailurePattern(
        name="oom",
        patterns=[
            r"Killed",
            r"MemoryError",
            r"OutOfMemoryError",
            r"JavaScript heap out of memory",
            r"ENOMEM",
        ],
        strategy="reduce-parallelism",
        explanation="Out of memory. Reducing parallelism and retrying.",
        retry_commands=[],
        retry_env={"PYTEST_ADDOPTS": "-x --forked", "NODE_OPTIONS": "--max-old-space-size=4096"},
    ),
    FailurePattern(
        name="docker-build-failure",
        patterns=[
            r"docker build.*failed",
            r"ERROR \[.+\] RUN",
            r"executor failed running",
            r"failed to compute cache key",
        ],
        strategy="docker-no-cache",
        explanation="Docker build failed. Retrying without cache.",
        retry_commands=[],
        retry_env={"DOCKER_BUILD_NO_CACHE": "true"},
    ),
    FailurePattern(
        name="import-error",
        patterns=[
            r"ModuleNotFoundError",
            r"ImportError",
            r"Cannot find module",
        ],
        strategy="reinstall-deps",
        explanation="Module import failed. Reinstalling dependencies from scratch.",
        retry_commands=["rm -rf .venv node_modules", "uv sync --all-extras 2>/dev/null || npm ci 2>/dev/null || true"],
        retry_env={},
    ),
    FailurePattern(
        name="ecr-throttle",
        patterns=[
            r"toomanyrequests",
            r"You have reached your pull rate limit",
            r"RepositoryNotFoundException",
            r"ECR.*throttl",
        ],
        strategy="ecr-backoff-retry",
        explanation="ECR rate limit or throttle. Waiting and retrying.",
        retry_commands=["sleep 60"],
        retry_env={},
    ),
    FailurePattern(
        name="codeartifact-unavailable",
        patterns=[
            r"CodeArtifact.*ServiceException",
            r"CodeArtifact.*Unavailable",
            r"Could not connect to codeartifact",
            r"GetAuthorizationToken.*failed",
        ],
        strategy="codeartifact-retry",
        explanation="CodeArtifact temporarily unavailable. Refreshing token and retrying.",
        retry_commands=[],
        retry_env={"CI_AGENT_REFRESH_CREDS": "true"},
    ),
    FailurePattern(
        name="git-conflict",
        patterns=[
            r"CONFLICT \(content\)",
            r"Merge conflict",
            r"Your local changes.*would be overwritten",
            r"cannot lock ref",
        ],
        strategy="git-reset-retry",
        explanation="Git conflict detected. Resetting and retrying from clean state.",
        retry_commands=["git reset --hard HEAD", "git clean -fd"],
        retry_env={},
        max_retries=1,
    ),
    FailurePattern(
        name="npm-install-failure",
        patterns=[
            r"npm ERR!",
            r"ERR_SOCKET_TIMEOUT",
            r"ERESOLVE unable to resolve dependency tree",
            r"npm warn.*peer dep",
        ],
        strategy="npm-clean-retry",
        explanation="NPM install failed. Clearing cache and retrying.",
        retry_commands=["rm -rf node_modules package-lock.json", "npm cache clean --force"],
        retry_env={},
    ),
]


def classify_failure(log_content: str) -> FailurePattern | None:
    """Match log content against known failure patterns. Returns the first match."""
    # Only look at the last 500 lines for efficiency
    lines = log_content.splitlines()
    tail = "\n".join(lines[-500:]) if len(lines) > 500 else log_content

    for pattern in FAILURE_PATTERNS:
        for regex in pattern.patterns:
            if re.search(regex, tail, re.IGNORECASE):
                return pattern

    return None

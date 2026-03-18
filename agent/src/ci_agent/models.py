"""Shared data models for the CI agent."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class BuildPlan:
    """Output of the detection phase — describes what and how to build."""

    repo_role: str = "framework"  # framework (library → CodeArtifact) or agent (service → ECR)
    project_type: str = "python"  # python, node, go, rust, java, unknown
    frameworks: list[str] = field(default_factory=list)
    test_tool: str | None = None
    deploy_target: str = "codeartifact"  # codeartifact (frameworks) or ecr (agents)
    has_dockerfile: bool = False
    python_version: str | None = None
    node_version: str | None = None
    go_version: str | None = None
    security_warnings: list[str] = field(default_factory=list)
    suggested_workflow: str = "ci-framework"  # ci-framework or ci-agent-service
    confidence: float = 1.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, data: str) -> BuildPlan:
        return cls(**{k: v for k, v in json.loads(data).items() if k in cls.__dataclass_fields__})


@dataclass
class HealingAction:
    """A healing strategy to apply after a build failure."""

    failure_class: str  # dependency-conflict, test-failure, timeout, etc.
    strategy: str  # clear-cache, retry-flaky, extend-timeout, etc.
    retry_env: dict[str, str] = field(default_factory=dict)
    retry_commands: list[str] = field(default_factory=list)
    needs_code_fix: bool = False
    fix_diff: str | None = None
    explanation: str = ""
    should_retry: bool = True

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


@dataclass
class BuildRecord:
    """A single build run record for history tracking."""

    run_id: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    branch: str = ""
    commit_sha: str = ""
    build_type: str = ""  # framework or agent
    duration_seconds: float = 0.0
    status: str = "unknown"  # success, failure, healed
    failure_class: str | None = None
    healing_strategy: str | None = None
    healing_success: bool | None = None
    detection_result: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> BuildRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AnalysisReport:
    """Output of the analysis phase — build insights and recommendations."""

    total_builds: int = 0
    avg_build_time: float = 0.0
    failure_rate: float = 0.0
    top_failure_classes: list[tuple[str, int]] = field(default_factory=list)
    flaky_tests: list[str] = field(default_factory=list)
    build_time_trend: str = "stable"  # improving, stable, degrading
    recommendations: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def to_markdown(self) -> str:
        lines = [
            "## CI Agent Analysis Report",
            f"_Generated: {self.generated_at}_\n",
            f"**Total builds analyzed:** {self.total_builds}",
            f"**Average build time:** {self.avg_build_time:.1f}s",
            f"**Failure rate:** {self.failure_rate:.1%}",
            f"**Build time trend:** {self.build_time_trend}\n",
        ]
        if self.top_failure_classes:
            lines.append("### Top Failure Classes")
            for cls, count in self.top_failure_classes:
                lines.append(f"- `{cls}`: {count} occurrences")
            lines.append("")
        if self.flaky_tests:
            lines.append("### Flaky Tests")
            for test in self.flaky_tests:
                lines.append(f"- `{test}`")
            lines.append("")
        if self.recommendations:
            lines.append("### Recommendations")
            for rec in self.recommendations:
                lines.append(f"- {rec}")
        return "\n".join(lines)

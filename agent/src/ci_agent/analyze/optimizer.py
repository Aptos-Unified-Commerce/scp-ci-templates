"""Build optimization suggestions based on detection and history."""

from __future__ import annotations

from ci_agent.analyze.insights import avg_build_time, healing_effectiveness
from ci_agent.models import BuildPlan, BuildRecord


def generate_recommendations(
    records: list[BuildRecord],
    plan: BuildPlan | None = None,
) -> list[str]:
    """Generate actionable optimization recommendations."""
    recommendations: list[str] = []

    if not records:
        return ["No build history available. Run more builds to get optimization suggestions."]

    # Build time recommendations
    avg_time = avg_build_time(records)
    if avg_time > 300:
        recommendations.append(
            f"Average build time is {avg_time:.0f}s ({avg_time / 60:.1f} min). "
            "Consider parallelizing test runs or enabling dependency caching."
        )

    if avg_time > 600:
        recommendations.append(
            "Build time exceeds 10 minutes. Consider splitting into separate "
            "test and build jobs for faster feedback on PRs."
        )

    # Healing effectiveness
    effectiveness = healing_effectiveness(records)
    for strategy, rate in effectiveness.items():
        if rate < 0.3:
            recommendations.append(
                f"Healing strategy `{strategy}` has a {rate:.0%} success rate. "
                "The underlying issue needs a permanent fix."
            )

    # Repeated failures
    failure_records = [r for r in records if r.status == "failure"]
    if len(failure_records) > len(records) * 0.3:
        recommendations.append(
            f"Failure rate is {len(failure_records) / len(records):.0%}. "
            "Investigate the most common failure classes and address root causes."
        )

    # Docker-specific
    if plan and plan.has_dockerfile:
        docker_times = [r.duration_seconds for r in records if r.build_type == "docker" and r.duration_seconds > 0]
        if docker_times and sum(docker_times) / len(docker_times) > 180:
            recommendations.append(
                "Docker builds are slow. Consider multi-stage builds, "
                ".dockerignore optimization, and BuildKit layer caching."
            )

    # Healed builds
    healed = [r for r in records if r.status == "healed"]
    if len(healed) > 5:
        recommendations.append(
            f"{len(healed)} builds required healing. These indicate fragile areas "
            "in the build pipeline that should be permanently fixed."
        )

    if not recommendations:
        recommendations.append("Build pipeline looks healthy. No optimization suggestions at this time.")

    return recommendations

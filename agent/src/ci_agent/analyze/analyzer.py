"""Main analysis orchestrator — generates an AnalysisReport from build history."""

from __future__ import annotations

from ci_agent.analyze.history import BuildHistory
from ci_agent.analyze.insights import (
    avg_build_time,
    build_time_trend,
    detect_flaky_tests,
    failure_rate,
    top_failure_classes,
)
from ci_agent.analyze.optimizer import generate_recommendations
from ci_agent.models import AnalysisReport


class Analyzer:
    """Analyzes build history and produces an AnalysisReport."""

    def __init__(self, history_file: str = "build_history.json") -> None:
        self.history = BuildHistory(history_file)

    def analyze(self) -> AnalysisReport:
        records = self.history.get_recent(50)

        if not records:
            return AnalysisReport(
                recommendations=["No build history available yet."],
            )

        return AnalysisReport(
            total_builds=len(records),
            avg_build_time=avg_build_time(records),
            failure_rate=failure_rate(records),
            top_failure_classes=top_failure_classes(records),
            flaky_tests=detect_flaky_tests(records),
            build_time_trend=build_time_trend(records),
            recommendations=generate_recommendations(records),
        )

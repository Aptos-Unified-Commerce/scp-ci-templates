"""Tests for the analysis module."""

import json
import tempfile
from pathlib import Path

import pytest

from ci_agent.analyze.analyzer import Analyzer
from ci_agent.analyze.history import BuildHistory
from ci_agent.analyze.insights import avg_build_time, build_time_trend, failure_rate
from ci_agent.models import BuildRecord


def _make_records(n: int, status: str = "success", duration: float = 60.0) -> list[BuildRecord]:
    return [
        BuildRecord(
            run_id=i,
            branch="main",
            commit_sha=f"abc{i:04d}",
            build_type="python",
            duration_seconds=duration,
            status=status,
        )
        for i in range(n)
    ]


def test_avg_build_time():
    records = _make_records(5, duration=120.0)
    assert avg_build_time(records) == 120.0


def test_failure_rate_all_success():
    records = _make_records(10)
    assert failure_rate(records) == 0.0


def test_failure_rate_mixed():
    records = _make_records(7) + _make_records(3, status="failure")
    assert failure_rate(records) == 0.3


def test_build_time_trend_stable():
    records = _make_records(20, duration=60.0)
    assert build_time_trend(records) == "stable"


def test_history_persistence(tmp_path):
    history_file = str(tmp_path / "history.json")

    # Write
    history = BuildHistory(history_file)
    history.add(BuildRecord(run_id=1, status="success", duration_seconds=45.0))
    history.add(BuildRecord(run_id=2, status="failure", failure_class="test-failure"))
    history.save()

    # Read back
    history2 = BuildHistory(history_file)
    assert len(history2.records) == 2
    assert history2.records[0].run_id == 1
    assert history2.records[1].failure_class == "test-failure"


def test_history_max_records(tmp_path):
    history_file = str(tmp_path / "history.json")
    history = BuildHistory(history_file)

    for i in range(250):
        history.add(BuildRecord(run_id=i))

    history.save()

    history2 = BuildHistory(history_file)
    assert len(history2.records) == 200  # MAX_RECORDS
    assert history2.records[0].run_id == 50  # Oldest kept


def test_analyzer_empty_history(tmp_path):
    history_file = str(tmp_path / "empty.json")
    analyzer = Analyzer(history_file=history_file)
    report = analyzer.analyze()

    assert report.total_builds == 0
    assert "No build history" in report.recommendations[0]


def test_analyzer_report_markdown(tmp_path):
    history_file = str(tmp_path / "history.json")
    history = BuildHistory(history_file)
    for r in _make_records(10, duration=90.0):
        history.add(r)
    history.save()

    analyzer = Analyzer(history_file=history_file)
    report = analyzer.analyze()
    md = report.to_markdown()

    assert "Analysis Report" in md
    assert "90.0s" in md

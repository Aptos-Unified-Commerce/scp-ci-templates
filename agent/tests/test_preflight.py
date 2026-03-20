"""Tests for the predictive pre-flight checks."""

import pytest

from ci_agent.models import BuildRecord
from ci_agent.predict.preflight import PreflightPredictor


def _record(status="success", branch="main", failure_class=None):
    return BuildRecord(status=status, branch=branch, failure_class=failure_class)


def test_healthy_repo_low_risk(tmp_path):
    records = [_record() for _ in range(10)]
    predictor = PreflightPredictor(records, repo_path=str(tmp_path))
    result = predictor.predict()
    assert result.risk_level == "low"
    assert result.risk_score < 0.4


def test_failing_branch_high_risk(tmp_path):
    import os
    os.environ["GITHUB_REF_NAME"] = "feature-broken"
    records = [
        _record(status="failure", branch="feature-broken", failure_class="test-failure"),
        _record(status="failure", branch="feature-broken", failure_class="test-failure"),
        _record(status="failure", branch="feature-broken", failure_class="test-failure"),
        _record(status="success", branch="feature-broken"),
    ]
    predictor = PreflightPredictor(records, repo_path=str(tmp_path))
    result = predictor.predict()
    assert result.risk_level in ("medium", "high")
    assert result.risk_score > 0.3
    os.environ.pop("GITHUB_REF_NAME", None)


def test_recurring_failure_predicts_class(tmp_path):
    records = [
        _record(status="failure", failure_class="dependency-conflict"),
        _record(status="failure", failure_class="dependency-conflict"),
        _record(status="failure", failure_class="dependency-conflict"),
        _record(status="success"),
    ]
    predictor = PreflightPredictor(records, repo_path=str(tmp_path))
    result = predictor.predict()
    assert result.predicted_failure == "dependency-conflict"


def test_empty_history_low_risk(tmp_path):
    predictor = PreflightPredictor([], repo_path=str(tmp_path))
    result = predictor.predict()
    assert result.risk_level == "low"


def test_result_to_markdown(tmp_path):
    records = [_record() for _ in range(5)]
    predictor = PreflightPredictor(records, repo_path=str(tmp_path))
    result = predictor.predict()
    md = result.to_markdown()
    assert "Pre-Flight Check" in md
    assert "LOW" in md or "low" in md.lower()

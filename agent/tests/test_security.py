"""Tests for the security scanning module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ci_agent.security.scanner import SecurityFinding, SecurityReport, SecurityScanner


def test_security_report_add():
    report = SecurityReport()
    report.add(SecurityFinding(
        tool="test", severity="high", category="vulnerability",
        title="CVE-2024-1234", description="Test vuln",
    ))
    report.add(SecurityFinding(
        tool="test", severity="critical", category="vulnerability",
        title="CVE-2024-5678", description="Critical vuln",
    ))

    assert report.total == 2
    assert report.has_critical is True
    assert report.has_high is True
    assert report.summary == {"high": 1, "critical": 1}


def test_security_report_no_findings():
    report = SecurityReport()
    assert report.total == 0
    assert report.has_critical is False
    assert report.has_high is False


def test_security_report_to_json():
    report = SecurityReport()
    report.add(SecurityFinding(
        tool="bandit", severity="medium", category="sast",
        title="B101", description="Use of assert", file="main.py", line=10,
    ))
    data = json.loads(report.to_json())
    assert data["total"] == 1
    assert data["findings"][0]["tool"] == "bandit"


def test_security_report_markdown():
    report = SecurityReport()
    report.tools_run = ["pip-audit", "bandit"]
    report.tools_skipped = ["trivy"]
    report.add(SecurityFinding(
        tool="pip-audit", severity="high", category="vulnerability",
        title="requests 2.28.0 — CVE-2023-1234", description="Test",
        fix="2.31.0",
    ))
    md = report.to_markdown()
    assert "Security Scan Report" in md
    assert "pip-audit" in md
    assert "CVE-2023-1234" in md
    assert "trivy" in md  # In skipped tools


def test_scanner_skips_unavailable_tools(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\nversion = "0.1.0"\n')
    scanner = SecurityScanner(repo_path=str(tmp_path))

    with patch("ci_agent.security.scanner._tool_available", return_value=False):
        report = scanner.scan_all()

    # All tools should be skipped
    assert "pip-audit" in report.tools_skipped
    assert "bandit" in report.tools_skipped
    assert "gitleaks" in report.tools_skipped
    assert report.total == 0


def test_scanner_no_python_skips_pip_audit(tmp_path):
    """Non-Python repo should not attempt pip-audit."""
    scanner = SecurityScanner(repo_path=str(tmp_path))
    # No pyproject.toml or requirements.txt → _run_pip_audit returns early
    with patch("ci_agent.security.scanner._tool_available", return_value=True):
        with patch("subprocess.run") as mock_run:
            scanner._run_pip_audit()
    mock_run.assert_not_called()

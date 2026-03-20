"""Tests for the docs generator module."""

from pathlib import Path

import pytest

from ci_agent.docs.generator import (
    BuildContext,
    collect_build_context,
    generate_all_docs,
    generate_architecture,
    generate_build_report,
    generate_changelog,
    write_docs,
)


@pytest.fixture
def sample_repo(tmp_path):
    """Create a minimal repo structure."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "scp-test-lib"\nversion = "0.5.0"\n'
    )
    src = tmp_path / "src" / "scp_test_lib"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text('"""SCP Test Library."""\n')
    (src / "main.py").write_text('"""Main module for the test library."""\n\ndef hello():\n    return "hi"\n')
    (src / "utils.py").write_text('"""Utility functions."""\n\nclass Helper:\n    pass\n\ndef compute():\n    pass\n')
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text("def test_hello(): pass\n")
    return tmp_path


def test_collect_build_context(sample_repo):
    ctx = collect_build_context(sample_repo)
    assert ctx.repo_name == "scp-test-lib"
    assert ctx.version == "0.5.0"


def test_collect_build_context_with_plan(sample_repo):
    plan = {
        "repo_role": "framework",
        "project_type": "python",
        "frameworks": ["fastapi"],
        "test_tool": "pytest",
    }
    ctx = collect_build_context(sample_repo, build_plan=plan)
    assert ctx.repo_role == "framework"
    assert ctx.frameworks == ["fastapi"]


def test_generate_build_report():
    ctx = BuildContext(
        repo_name="scp-test",
        branch="main",
        commit_sha="abc1234",
        version="1.0.0",
        repo_role="framework",
        project_type="python",
        test_count=50,
        test_passed=48,
        coverage=85.0,
        build_status="passed",
    )
    report = generate_build_report(ctx)
    assert "scp-test" in report
    assert "1.0.0" in report
    assert "48/50" in report
    assert "85%" in report
    assert "PASSED" in report


def test_generate_build_report_failed():
    ctx = BuildContext(build_status="failed", repo_name="test")
    report = generate_build_report(ctx)
    assert "FAILED" in report


def test_generate_changelog(sample_repo):
    changelog = generate_changelog(sample_repo)
    assert "Changelog" in changelog


def test_generate_architecture(sample_repo):
    arch = generate_architecture(sample_repo)
    assert "Architecture" in arch
    assert "main.py" in arch
    assert "utils.py" in arch
    assert "`Helper`" in arch
    assert "`compute`" in arch
    assert "`hello`" in arch


def test_generate_all_docs(sample_repo):
    docs = generate_all_docs(
        str(sample_repo),
        build_status="passed",
        test_count=10,
        test_passed=10,
        coverage=90.0,
    )
    assert "BUILD_REPORT.md" in docs
    assert "CHANGELOG.md" in docs
    assert "ARCHITECTURE.md" in docs
    assert "PASSED" in docs["BUILD_REPORT.md"]


def test_write_docs(sample_repo):
    docs = {"BUILD_REPORT.md": "# Report\ntest", "CHANGELOG.md": "# Log\ntest"}
    written = write_docs(str(sample_repo), docs)
    assert len(written) == 2
    assert (sample_repo / "docs" / "BUILD_REPORT.md").exists()
    assert (sample_repo / "docs" / "CHANGELOG.md").exists()
    assert "# Report" in (sample_repo / "docs" / "BUILD_REPORT.md").read_text()

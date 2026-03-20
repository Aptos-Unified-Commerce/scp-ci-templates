"""Tests for the PR review agent."""

import pytest

from ci_agent.review.pr_reviewer import PRReviewer, ReviewFinding, ReviewResult


def test_review_result_approved():
    result = ReviewResult()
    assert result.approved is True


def test_review_result_not_approved_with_errors():
    result = ReviewResult(
        findings=[
            ReviewFinding(category="security", severity="error", file="main.py",
                         message="Hardcoded password"),
        ],
        approved=False,
    )
    assert result.approved is False
    d = result.to_dict()
    assert d["error_count"] == 1


def test_review_result_to_markdown():
    result = ReviewResult(
        findings=[
            ReviewFinding(category="security", severity="error", file="main.py",
                         line=10, message="Hardcoded password"),
            ReviewFinding(category="missing-test", severity="warning", file="src/auth.py",
                         message="No tests for new code"),
        ],
        approved=False,
        summary="Found 1 error(s) and 1 warning(s).",
    )
    md = result.to_markdown()
    assert "CHANGES REQUESTED" in md
    assert "Hardcoded password" in md
    assert "No tests for new code" in md


def test_review_result_approved_markdown():
    result = ReviewResult(approved=True, summary="All good.")
    md = result.to_markdown()
    assert "APPROVED" in md


def test_empty_review():
    result = ReviewResult()
    md = result.to_markdown()
    assert "No issues found" in md


def test_reviewer_no_diff(tmp_path):
    reviewer = PRReviewer(repo_path=str(tmp_path), base_ref="main")
    result = reviewer.review()
    assert "No diff found" in result.summary


def test_security_check_detects_patterns():
    result = ReviewResult()
    reviewer = PRReviewer()

    diff = '''
+++ b/config.py
+password = "supersecret123"
+AKIAIOSFODNN7EXAMPLE
+subprocess.call("rm -rf /", shell=True)
'''
    reviewer._check_security(diff, result)
    categories = [f.category for f in result.findings]
    assert "security" in categories
    assert len(result.findings) >= 2  # At least password + AWS key or shell injection


def test_missing_test_check():
    result = ReviewResult()
    reviewer = PRReviewer()

    files = ["src/auth/login.py", "src/auth/token.py"]
    reviewer._check_missing_tests(files, result)
    assert any(f.category == "missing-test" for f in result.findings)


def test_no_missing_test_when_tests_present():
    result = ReviewResult()
    reviewer = PRReviewer()

    files = ["src/auth/login.py", "tests/test_login.py"]
    reviewer._check_missing_tests(files, result)
    assert not any(f.category == "missing-test" for f in result.findings)

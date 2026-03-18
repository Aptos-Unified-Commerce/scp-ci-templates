"""Tests for the versioning module."""

import pytest

from ci_agent.version.versioner import (
    apply_version,
    bump_version,
    classify_commits,
    generate_changelog,
    get_current_version,
    parse_version,
)


def test_parse_version():
    assert parse_version("1.2.3") == (1, 2, 3)
    assert parse_version("0.1.0") == (0, 1, 0)
    assert parse_version("2.0") == (2, 0, 0)


def test_bump_version_patch():
    assert bump_version("1.2.3", "patch") == "1.2.4"


def test_bump_version_minor():
    assert bump_version("1.2.3", "minor") == "1.3.0"


def test_bump_version_major():
    assert bump_version("1.2.3", "major") == "2.0.0"


def test_bump_version_none():
    assert bump_version("1.2.3", "none") == "1.2.3"


def test_classify_breaking_change():
    commits = ["feat!: remove legacy API", "fix: typo"]
    bump, breaking, features, fixes = classify_commits(commits)
    assert bump == "major"
    assert len(breaking) == 1


def test_classify_feature():
    commits = ["feat: add new endpoint", "chore: update deps"]
    bump, breaking, features, fixes = classify_commits(commits)
    assert bump == "minor"
    assert len(features) == 1


def test_classify_fix():
    commits = ["fix: handle null response", "docs: update readme"]
    bump, breaking, features, fixes = classify_commits(commits)
    assert bump == "patch"
    assert len(fixes) == 1


def test_classify_no_commits():
    bump, breaking, features, fixes = classify_commits([])
    assert bump == "none"


def test_get_current_version_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "1.5.2"\n'
    )
    assert get_current_version(tmp_path) == "1.5.2"


def test_get_current_version_from_package_json(tmp_path):
    import json
    (tmp_path / "package.json").write_text(json.dumps({"name": "test", "version": "2.0.1"}))
    assert get_current_version(tmp_path) == "2.0.1"


def test_get_current_version_fallback(tmp_path):
    assert get_current_version(tmp_path) == "0.0.1"


def test_apply_version_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "1.0.0"\n'
    )
    modified = apply_version(tmp_path, "1.1.0")
    assert "pyproject.toml" in modified
    assert '"1.1.0"' in (tmp_path / "pyproject.toml").read_text()


def test_apply_version_creates_pyproject_if_missing(tmp_path):
    """If no pyproject.toml exists, create one with the version."""
    modified = apply_version(tmp_path, "0.0.1")
    assert any("pyproject.toml" in m for m in modified)

    pyproject = tmp_path / "pyproject.toml"
    assert pyproject.exists()
    text = pyproject.read_text()
    assert '"0.0.1"' in text
    assert "[project]" in text
    assert "[build-system]" in text


def test_apply_version_injects_version_if_missing(tmp_path):
    """If pyproject.toml exists but has no version field, inject it."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nrequires-python = ">=3.11"\n'
    )
    modified = apply_version(tmp_path, "0.2.0")
    assert "pyproject.toml" in modified
    text = (tmp_path / "pyproject.toml").read_text()
    assert '"0.2.0"' in text


def test_generate_changelog():
    from ci_agent.version.versioner import VersionInfo
    info = VersionInfo(
        current="1.0.0",
        new="1.1.0",
        bump_type="minor",
        commits_analyzed=3,
        breaking_changes=[],
        features=["feat: add auth module"],
        fixes=["fix: handle timeout"],
    )
    changelog = generate_changelog(info)
    assert "1.1.0" in changelog
    assert "auth module" in changelog
    assert "timeout" in changelog

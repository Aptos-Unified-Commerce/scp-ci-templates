"""Detect testing tools and configuration."""

from __future__ import annotations

from pathlib import Path


def detect_test_tool(repo_path: Path, project_type: str) -> str | None:
    """Detect the test tool configured in the project."""
    if project_type == "python":
        return _detect_python_test_tool(repo_path)
    elif project_type == "node":
        return _detect_node_test_tool(repo_path)
    elif project_type == "go":
        return _detect_go_tests(repo_path)
    elif project_type == "rust":
        return "cargo-test"
    elif project_type == "java":
        return _detect_java_test_tool(repo_path)
    return None


def _detect_python_test_tool(repo_path: Path) -> str | None:
    # Check pyproject.toml for [tool.pytest]
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text()
        if "[tool.pytest" in text:
            return "pytest"

    # Check for config files
    if (repo_path / "pytest.ini").exists():
        return "pytest"
    if (repo_path / "setup.cfg").exists():
        text = (repo_path / "setup.cfg").read_text()
        if "[tool:pytest]" in text:
            return "pytest"
    if (repo_path / "tox.ini").exists():
        return "tox"

    # Check test directory existence
    if (repo_path / "tests").is_dir():
        return "pytest"  # Default assumption for Python

    return None


def _detect_node_test_tool(repo_path: Path) -> str | None:
    import json

    # Check jest config
    for name in ["jest.config.js", "jest.config.ts", "jest.config.mjs"]:
        if (repo_path / name).exists():
            return "jest"

    # Check package.json
    pkg = repo_path / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text())
            if "jest" in data:
                return "jest"
            scripts = data.get("scripts", {})
            test_script = scripts.get("test", "")
            if "jest" in test_script:
                return "jest"
            if "vitest" in test_script:
                return "vitest"
            if "mocha" in test_script:
                return "mocha"
        except Exception:
            pass

    return None


def _detect_go_tests(repo_path: Path) -> str | None:
    # Check for any _test.go files
    for p in repo_path.rglob("*_test.go"):
        return "go-test"
    return None


def _detect_java_test_tool(repo_path: Path) -> str | None:
    if (repo_path / "pom.xml").exists():
        return "maven-surefire"
    if (repo_path / "build.gradle").exists() or (repo_path / "build.gradle.kts").exists():
        return "gradle-test"
    return None

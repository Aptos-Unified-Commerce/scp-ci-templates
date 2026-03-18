"""Tests for the detection module."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from ci_agent.detect.detector import Detector


@pytest.fixture
def python_repo(tmp_path):
    """Create a minimal Python project."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11"\n'
        'dependencies = ["fastapi", "boto3"]\n\n'
        "[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


@pytest.fixture
def docker_repo(tmp_path):
    """Create a project with a Dockerfile."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "test-svc"\nversion = "0.1.0"\n'
        'dependencies = ["flask"]\n'
    )
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\nCOPY . .\n")
    (tmp_path / "src").mkdir()
    return tmp_path


@pytest.fixture
def node_repo(tmp_path):
    """Create a Node.js project."""
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "test-app",
                "dependencies": {"express": "^4.0.0"},
                "devDependencies": {"jest": "^29.0.0"},
                "scripts": {"test": "jest"},
            }
        )
    )
    return tmp_path


def test_detect_python_project(python_repo):
    detector = Detector(repo_path=str(python_repo))
    plan = detector.detect()

    assert plan.project_type == "python"
    assert plan.has_dockerfile is False
    assert plan.deploy_target == "codeartifact"
    assert plan.suggested_workflow == "ci-python"
    assert plan.test_tool == "pytest"
    assert "fastapi" in plan.frameworks
    assert plan.python_version == ">=3.11"
    assert plan.confidence > 0.5


def test_detect_docker_project(docker_repo):
    detector = Detector(repo_path=str(docker_repo))
    plan = detector.detect()

    assert plan.project_type == "python"
    assert plan.has_dockerfile is True
    assert plan.deploy_target == "ecr"
    assert plan.suggested_workflow == "ci-docker"
    assert "flask" in plan.frameworks


def test_detect_node_project(node_repo):
    detector = Detector(repo_path=str(node_repo))
    plan = detector.detect()

    assert plan.project_type == "node"
    assert plan.has_dockerfile is False
    assert plan.test_tool == "jest"
    assert "express" in plan.frameworks


def test_detect_unknown_project(tmp_path):
    detector = Detector(repo_path=str(tmp_path))
    plan = detector.detect()

    assert plan.project_type == "unknown"
    assert plan.confidence == 0.0


def test_config_override(tmp_path):
    (tmp_path / ".ci-agent.yml").write_text(
        "project_type: python\n"
        "deploy_target: lambda\n"
        "suggested_workflow: ci-python\n"
        "frameworks:\n  - fastapi\n"
    )
    detector = Detector(repo_path=str(tmp_path))
    plan = detector.detect()

    assert plan.project_type == "python"
    assert plan.deploy_target == "lambda"
    assert plan.confidence == 1.0


def test_security_detects_env_file(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\nversion = "0.1.0"\n')
    (tmp_path / ".env").write_text("SECRET=foo\n")

    detector = Detector(repo_path=str(tmp_path))
    plan = detector.detect()

    assert any(".env" in w for w in plan.security_warnings)

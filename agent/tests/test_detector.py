"""Tests for the detection module."""

import json
from pathlib import Path

import pytest

from ci_agent.detect.detector import Detector


@pytest.fixture
def framework_repo(tmp_path):
    """A framework repo: Python library, no Dockerfile → CodeArtifact."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "scp-ai-platform"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11"\n'
        'dependencies = ["langchain", "boto3"]\n\n'
        "[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


@pytest.fixture
def agent_repo(tmp_path):
    """An agent repo: Python service with Dockerfile → ECR."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "scp-agent-test-runner"\nversion = "0.1.0"\n'
        'dependencies = ["fastapi", "scp-ai-platform"]\n'
    )
    (tmp_path / "Dockerfile").write_text(
        "FROM python:3.11-slim\n"
        "ARG PIP_EXTRA_INDEX_URL\n"
        "COPY . .\n"
        "RUN pip install -r requirements.txt\n"
        "CMD [\"uvicorn\", \"main:app\"]\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    return tmp_path


@pytest.fixture
def node_repo(tmp_path):
    """A Node.js project (no Dockerfile → framework)."""
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


def test_detect_framework_repo(framework_repo):
    """Python library without Dockerfile → framework → CodeArtifact."""
    detector = Detector(repo_path=str(framework_repo))
    plan = detector.detect()

    assert plan.repo_role == "framework"
    assert plan.project_type == "python"
    assert plan.has_dockerfile is False
    assert plan.deploy_target == "codeartifact"
    assert plan.suggested_workflow == "ci-framework"
    assert plan.test_tool == "pytest"
    assert "langchain" in plan.frameworks
    assert plan.python_version == ">=3.11"
    assert plan.confidence > 0.5


def test_detect_agent_repo(agent_repo):
    """Python service with Dockerfile → agent → ECR."""
    detector = Detector(repo_path=str(agent_repo))
    plan = detector.detect()

    assert plan.repo_role == "agent"
    assert plan.project_type == "python"
    assert plan.has_dockerfile is True
    assert plan.deploy_target == "ecr"
    assert plan.suggested_workflow == "ci-agent-service"
    assert "fastapi" in plan.frameworks


def test_detect_node_framework(node_repo):
    """Node.js project without Dockerfile → framework."""
    detector = Detector(repo_path=str(node_repo))
    plan = detector.detect()

    assert plan.repo_role == "framework"
    assert plan.project_type == "node"
    assert plan.has_dockerfile is False
    assert plan.test_tool == "jest"
    assert "express" in plan.frameworks


def test_detect_unknown_project(tmp_path):
    detector = Detector(repo_path=str(tmp_path))
    plan = detector.detect()

    assert plan.project_type == "unknown"
    assert plan.confidence == 0.0


def test_config_override_as_agent(tmp_path):
    """Override detection to force agent role."""
    (tmp_path / ".ci-agent.yml").write_text(
        "repo_role: agent\n"
        "project_type: python\n"
        "frameworks:\n  - fastapi\n"
    )
    detector = Detector(repo_path=str(tmp_path))
    plan = detector.detect()

    assert plan.repo_role == "agent"
    assert plan.deploy_target == "ecr"
    assert plan.suggested_workflow == "ci-agent-service"
    assert plan.confidence == 1.0


def test_config_override_as_framework(tmp_path):
    """Override detection to force framework role."""
    (tmp_path / ".ci-agent.yml").write_text(
        "repo_role: framework\n"
        "project_type: python\n"
    )
    detector = Detector(repo_path=str(tmp_path))
    plan = detector.detect()

    assert plan.repo_role == "framework"
    assert plan.deploy_target == "codeartifact"
    assert plan.suggested_workflow == "ci-framework"


def test_security_detects_env_file(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\nversion = "0.1.0"\n')
    (tmp_path / ".env").write_text("SECRET=foo\n")

    detector = Detector(repo_path=str(tmp_path))
    plan = detector.detect()

    assert any(".env" in w for w in plan.security_warnings)

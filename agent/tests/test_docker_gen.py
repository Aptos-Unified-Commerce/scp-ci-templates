"""Tests for the Docker generator module."""

from pathlib import Path

import pytest

from ci_agent.docker.generator import generate_dockerfile, load_docker_config


@pytest.fixture
def golden_template(tmp_path):
    """Create a minimal golden Dockerfile template."""
    template = tmp_path / "agent.Dockerfile"
    template.write_text(
        "FROM python:{{python_version}}-slim\n"
        "{{extra_build_packages}}\n"
        "{{extra_runtime_packages}}\n"
        "EXPOSE {{port}}\n"
        "CMD {{entrypoint}}\n"
    )
    return template


@pytest.fixture
def agent_repo(tmp_path):
    """Create a minimal agent repo."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "scp-agent-orders"\nversion = "0.1.0"\n'
    )
    src = tmp_path / "src" / "scp_agent_orders"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    return tmp_path


def test_generate_default_dockerfile(golden_template, agent_repo):
    output = agent_repo / "Dockerfile"
    result = generate_dockerfile(golden_template, agent_repo, output)

    assert output.exists()
    assert "python:3.11-slim" in result
    assert "EXPOSE 8000" in result
    assert "scp_agent_orders.main:app" in result


def test_generate_with_ci_agent_yml(golden_template, agent_repo):
    (agent_repo / ".ci-agent.yml").write_text(
        "docker:\n"
        "  python_version: '3.12'\n"
        "  port: 9000\n"
        '  entrypoint: \'["gunicorn", "app:create_app()"]\'\n'
        "  extra_system_packages:\n"
        "    - libpq5\n"
        "  extra_build_packages:\n"
        "    - gcc\n"
        "    - libpq-dev\n"
    )
    result = generate_dockerfile(golden_template, agent_repo)

    assert "python:3.12-slim" in result
    assert "EXPOSE 9000" in result
    assert "gunicorn" in result
    assert "libpq5" in result
    assert "gcc" in result
    assert "libpq-dev" in result


def test_load_config_defaults(agent_repo):
    config = load_docker_config(agent_repo)
    assert config["python_version"] == "3.11"
    assert config["port"] == 8000
    assert config["extra_system_packages"] == []


def test_load_config_with_override(agent_repo):
    (agent_repo / ".ci-agent.yml").write_text(
        "docker:\n"
        "  python_version: '3.12'\n"
        "  port: 9090\n"
    )
    config = load_docker_config(agent_repo)
    assert config["python_version"] == "3.12"
    assert config["port"] == 9090


def test_auto_detect_entrypoint(agent_repo):
    config = load_docker_config(agent_repo)
    assert "scp_agent_orders.main:app" in config["entrypoint"]
    assert "uvicorn" in config["entrypoint"]


def test_no_ci_agent_yml_uses_defaults(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-svc"\nversion = "0.1.0"\n')
    config = load_docker_config(tmp_path)
    assert config["python_version"] == "3.11"
    assert config["port"] == 8000

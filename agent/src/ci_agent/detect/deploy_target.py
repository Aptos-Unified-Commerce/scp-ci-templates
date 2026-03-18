"""Detect repo role (framework vs agent) and deployment target."""

from __future__ import annotations

import re
from pathlib import Path

# Files/dirs that strongly indicate a service (agent) rather than a library
SERVICE_INDICATORS = [
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Procfile",
    "kubernetes",
    "k8s",
    "deploy",
    ".dockerignore",
]

# Entrypoint patterns in pyproject.toml that indicate a service
SERVICE_ENTRYPOINT_PATTERNS = [
    r"\[project\.scripts\]",  # has CLI entry points → could be either
    r"uvicorn",
    r"gunicorn",
    r"flask run",
    r"celery",
    r"grpc",
]

# Dependency patterns that strongly suggest a service
SERVICE_DEPENDENCY_PATTERNS = [
    r"fastapi",
    r"flask",
    r"django",
    r"uvicorn",
    r"gunicorn",
    r"grpcio",
    r"celery",
]


def detect_repo_role(repo_path: Path, has_dockerfile: bool) -> tuple[str, str]:
    """Determine if this repo is a 'framework' (library) or 'agent' (service).

    Returns (repo_role, deploy_target):
        - framework → codeartifact  (library published as a Python package)
        - agent     → ecr           (service built as a Docker image)

    Heuristics (in priority order):
        1. Dockerfile present → agent (service that ships as a container)
        2. Service indicator files/dirs → agent
        3. Service-like dependencies (FastAPI, Flask, etc.) → agent
        4. Default → framework (library published to CodeArtifact)
        5. .ci-agent.yml can override any of this
    """
    # Strong signal: Dockerfile
    if has_dockerfile:
        return "agent", "ecr"

    # Check for other service indicator files/dirs
    for indicator in SERVICE_INDICATORS:
        if (repo_path / indicator).exists():
            return "agent", "ecr"

    # Check pyproject.toml for service entrypoints and dependencies
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text()

        # Check for service-like entry points / server commands
        for pattern in SERVICE_ENTRYPOINT_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                # Also check dependencies to confirm it's a service
                for dep_pattern in SERVICE_DEPENDENCY_PATTERNS:
                    if re.search(dep_pattern, text, re.IGNORECASE):
                        return "agent", "ecr"

    # Check requirements.txt for service dependencies
    requirements = repo_path / "requirements.txt"
    if requirements.exists():
        text = requirements.read_text()
        service_dep_count = sum(
            1 for pattern in SERVICE_DEPENDENCY_PATTERNS
            if re.search(pattern, text, re.IGNORECASE)
        )
        if service_dep_count >= 2:
            return "agent", "ecr"

    # No Dockerfile, no service indicators — it's a framework/library
    return "framework", "codeartifact"

"""Detect repo role (framework vs agent) and deployment target."""

from __future__ import annotations

from pathlib import Path


def detect_repo_role(repo_path: Path, has_dockerfile: bool) -> tuple[str, str]:
    """Determine if this repo is a 'framework' (library) or 'agent' (service).

    Returns (repo_role, deploy_target):
        - framework → codeartifact  (library published as a Python package)
        - agent     → ecr           (service built as a Docker image)

    Heuristics:
        1. Dockerfile present → agent (service that ships as a container)
        2. No Dockerfile      → framework (library published to CodeArtifact)
        3. .ci-agent.yml can override this
    """
    if has_dockerfile:
        return "agent", "ecr"

    # No Dockerfile — it's a framework/library
    return "framework", "codeartifact"

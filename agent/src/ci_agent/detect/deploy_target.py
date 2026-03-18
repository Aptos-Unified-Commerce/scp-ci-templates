"""Detect deployment target from project structure."""

from __future__ import annotations

from pathlib import Path


def detect_deploy_target(repo_path: Path, project_type: str, has_dockerfile: bool) -> str:
    """Infer the deployment target.

    Priority:
    1. Dockerfile → ecr
    2. SAM/serverless → lambda
    3. CDK → cdk
    4. Python library → codeartifact
    5. Node library → npm (or codeartifact)
    """
    # Docker always means ECR
    if has_dockerfile:
        return "ecr"

    # SAM template
    if (repo_path / "template.yaml").exists() or (repo_path / "template.yml").exists():
        return "lambda"

    # Serverless framework
    if (repo_path / "serverless.yml").exists() or (repo_path / "serverless.yaml").exists():
        return "lambda"

    # AWS CDK
    if (repo_path / "cdk.json").exists():
        return "cdk"

    # Terraform
    for tf in repo_path.glob("*.tf"):
        return "terraform"

    # Library — publish to artifact repo
    if project_type == "python":
        return "codeartifact"
    if project_type == "node":
        return "npm"
    if project_type == "go":
        return "go-module"

    return "codeartifact"

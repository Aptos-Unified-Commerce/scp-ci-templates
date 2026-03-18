"""Main detection orchestrator — generates a BuildPlan."""

from __future__ import annotations

from pathlib import Path

import yaml

from ci_agent.detect.deploy_target import detect_deploy_target
from ci_agent.detect.framework import detect_frameworks
from ci_agent.detect.project_type import (
    detect_go_version,
    detect_node_version,
    detect_project_type,
    detect_python_version,
)
from ci_agent.detect.security import run_security_checks
from ci_agent.detect.test_tools import detect_test_tool
from ci_agent.models import BuildPlan

WORKFLOW_MAP = {
    "python": "ci-python",
    "node": "ci-node",
    "go": "ci-go",
    "rust": "ci-rust",
    "java": "ci-java",
    "docker-only": "ci-docker",
}


class Detector:
    """Scans a repository and produces a BuildPlan."""

    def __init__(self, repo_path: str = ".") -> None:
        self.repo_path = Path(repo_path).resolve()

    def detect(self) -> BuildPlan:
        # Check for manual override first
        override = self._load_override()
        if override:
            return override

        has_dockerfile = (self.repo_path / "Dockerfile").exists()
        primary_type, all_types = detect_project_type(self.repo_path)
        frameworks = detect_frameworks(self.repo_path, primary_type)
        test_tool = detect_test_tool(self.repo_path, primary_type)
        deploy_target = detect_deploy_target(self.repo_path, primary_type, has_dockerfile)
        security_warnings = run_security_checks(self.repo_path)

        # Determine suggested workflow
        if has_dockerfile and primary_type != "docker-only":
            # Has both code and Dockerfile — Docker build is primary
            suggested_workflow = "ci-docker"
        else:
            suggested_workflow = WORKFLOW_MAP.get(primary_type, "ci-python")

        # Calculate confidence
        confidence = self._calculate_confidence(primary_type, frameworks, test_tool)

        return BuildPlan(
            project_type=primary_type,
            frameworks=frameworks,
            test_tool=test_tool,
            deploy_target=deploy_target,
            has_dockerfile=has_dockerfile,
            python_version=detect_python_version(self.repo_path),
            node_version=detect_node_version(self.repo_path),
            go_version=detect_go_version(self.repo_path),
            security_warnings=security_warnings,
            suggested_workflow=suggested_workflow,
            confidence=confidence,
        )

    def _load_override(self) -> BuildPlan | None:
        """Load .ci-agent.yml override file if present."""
        config_file = self.repo_path / ".ci-agent.yml"
        if not config_file.exists():
            return None

        try:
            config = yaml.safe_load(config_file.read_text())
            if not isinstance(config, dict):
                return None

            has_dockerfile = (self.repo_path / config.get("dockerfile_path", "Dockerfile")).exists()

            return BuildPlan(
                project_type=config.get("project_type", "unknown"),
                frameworks=config.get("frameworks", []),
                test_tool=config.get("test_tool"),
                deploy_target=config.get("deploy_target", "codeartifact"),
                has_dockerfile=has_dockerfile,
                python_version=config.get("python_version"),
                node_version=config.get("node_version"),
                go_version=config.get("go_version"),
                security_warnings=[],
                suggested_workflow=config.get("suggested_workflow", "ci-python"),
                confidence=1.0,
            )
        except Exception:
            return None

    def _calculate_confidence(
        self,
        project_type: str,
        frameworks: list[str],
        test_tool: str | None,
    ) -> float:
        """Heuristic confidence score for the detection."""
        if project_type == "unknown":
            return 0.0

        score = 0.5  # Base: we found a project type

        if frameworks:
            score += 0.2  # We identified specific frameworks

        if test_tool:
            score += 0.15  # We know how to test it

        if (self.repo_path / "pyproject.toml").exists() or (self.repo_path / "package.json").exists():
            score += 0.15  # Strong project metadata file

        return min(score, 1.0)

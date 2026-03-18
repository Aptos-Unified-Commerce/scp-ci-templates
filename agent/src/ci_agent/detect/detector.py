"""Main detection orchestrator — generates a BuildPlan."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ci_agent.detect.deploy_target import detect_repo_role
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

logger = logging.getLogger(__name__)

# Valid values for .ci-agent.yml fields
VALID_REPO_ROLES = {"framework", "agent"}
VALID_PROJECT_TYPES = {"python", "node", "go", "rust", "java", "unknown"}
VALID_DEPLOY_TARGETS = {"codeartifact", "ecr"}
VALID_SUGGESTED_WORKFLOWS = {"ci-framework", "ci-agent-service"}


class Detector:
    """Scans a repository and produces a BuildPlan.

    Classification:
        - Framework: Python library → test + uv build → publish to CodeArtifact
        - Agent: Python service with Dockerfile → test + docker build → push to ECR
    """

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
        repo_role, deploy_target = detect_repo_role(self.repo_path, has_dockerfile)
        security_warnings = run_security_checks(self.repo_path)

        # Map role to workflow
        suggested_workflow = "ci-agent-service" if repo_role == "agent" else "ci-framework"

        confidence = self._calculate_confidence(primary_type, frameworks, test_tool)

        return BuildPlan(
            repo_role=repo_role,
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
        """Load .ci-agent.yml override file if present.

        Validates config values and logs warnings for invalid fields,
        falling back to defaults for bad values rather than silently ignoring.
        """
        config_file = self.repo_path / ".ci-agent.yml"
        if not config_file.exists():
            return None

        try:
            config = yaml.safe_load(config_file.read_text())
            if not isinstance(config, dict):
                logger.warning(".ci-agent.yml is not a valid YAML dict — ignoring override")
                return None

            warnings: list[str] = []

            # Validate known fields
            repo_role = config.get("repo_role")
            if repo_role and repo_role not in VALID_REPO_ROLES:
                warnings.append(
                    f"Invalid repo_role '{repo_role}' in .ci-agent.yml "
                    f"(expected one of {VALID_REPO_ROLES}). Falling back to auto-detection."
                )
                repo_role = None

            project_type = config.get("project_type")
            if project_type and project_type not in VALID_PROJECT_TYPES:
                warnings.append(
                    f"Invalid project_type '{project_type}' in .ci-agent.yml "
                    f"(expected one of {VALID_PROJECT_TYPES}). Falling back to 'python'."
                )
                project_type = "python"

            suggested_workflow = config.get("suggested_workflow")
            if suggested_workflow and suggested_workflow not in VALID_SUGGESTED_WORKFLOWS:
                warnings.append(
                    f"Invalid suggested_workflow '{suggested_workflow}' in .ci-agent.yml "
                    f"(expected one of {VALID_SUGGESTED_WORKFLOWS}). Will auto-derive."
                )
                suggested_workflow = None

            # Warn about unknown top-level keys
            known_keys = {
                "repo_role", "project_type", "frameworks", "test_tool",
                "python_version", "node_version", "go_version",
                "suggested_workflow", "dockerfile_path", "docker",
            }
            unknown_keys = set(config.keys()) - known_keys
            if unknown_keys:
                warnings.append(
                    f"Unknown keys in .ci-agent.yml: {unknown_keys}. These will be ignored."
                )

            for w in warnings:
                logger.warning(w)

            has_dockerfile = (self.repo_path / config.get("dockerfile_path", "Dockerfile")).exists()
            if repo_role is None:
                repo_role = "agent" if has_dockerfile else "framework"
            if suggested_workflow is None:
                suggested_workflow = "ci-agent-service" if repo_role == "agent" else "ci-framework"

            return BuildPlan(
                repo_role=repo_role,
                project_type=project_type or "python",
                frameworks=config.get("frameworks", []),
                test_tool=config.get("test_tool"),
                deploy_target="ecr" if repo_role == "agent" else "codeartifact",
                has_dockerfile=has_dockerfile,
                python_version=config.get("python_version"),
                node_version=config.get("node_version"),
                go_version=config.get("go_version"),
                security_warnings=warnings,
                suggested_workflow=suggested_workflow,
                confidence=1.0,
            )
        except yaml.YAMLError as exc:
            logger.error("Failed to parse .ci-agent.yml: %s — falling back to auto-detection", exc)
            return None
        except Exception as exc:
            logger.error("Unexpected error loading .ci-agent.yml: %s", exc)
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
            score += 0.2

        if test_tool:
            score += 0.15

        if (self.repo_path / "pyproject.toml").exists() or (self.repo_path / "package.json").exists():
            score += 0.15

        return min(score, 1.0)

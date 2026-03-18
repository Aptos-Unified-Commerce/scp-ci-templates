"""Detect frameworks from dependency files."""

from __future__ import annotations

import json
import re
from pathlib import Path

# framework name -> patterns to search in dependency lists
PYTHON_FRAMEWORKS = {
    "fastapi": ["fastapi"],
    "flask": ["flask"],
    "django": ["django"],
    "celery": ["celery"],
    "aws-lambda-powertools": ["aws-lambda-powertools"],
    "langchain": ["langchain"],
    "streamlit": ["streamlit"],
    "gradio": ["gradio"],
}

NODE_FRAMEWORKS = {
    "express": ["express"],
    "next": ["next"],
    "nestjs": ["@nestjs/core"],
    "react": ["react"],
    "vue": ["vue"],
    "angular": ["@angular/core"],
}

GO_FRAMEWORKS = {
    "gin": ["github.com/gin-gonic/gin"],
    "fiber": ["github.com/gofiber/fiber"],
    "echo": ["github.com/labstack/echo"],
    "chi": ["github.com/go-chi/chi"],
}


def _read_python_deps(repo_path: Path) -> list[str]:
    """Read dependency names from pyproject.toml or requirements.txt."""
    deps: list[str] = []

    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text()
        # Grab everything in dependencies = [...] blocks
        for match in re.findall(r'"([a-zA-Z0-9_-]+)', text):
            deps.append(match.lower())

    for req_file in ["requirements.txt", "requirements-dev.txt"]:
        path = repo_path / req_file
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    name = re.split(r"[>=<!\[;]", line)[0].strip()
                    if name:
                        deps.append(name.lower())

    return deps


def _read_node_deps(repo_path: Path) -> list[str]:
    """Read dependency names from package.json."""
    pkg = repo_path / "package.json"
    if not pkg.exists():
        return []

    try:
        data = json.loads(pkg.read_text())
        deps = list(data.get("dependencies", {}).keys())
        deps += list(data.get("devDependencies", {}).keys())
        return [d.lower() for d in deps]
    except Exception:
        return []


def _read_go_deps(repo_path: Path) -> list[str]:
    """Read module paths from go.mod require block."""
    gomod = repo_path / "go.mod"
    if not gomod.exists():
        return []

    deps = []
    text = gomod.read_text()
    for match in re.findall(r"require\s*\((.*?)\)", text, re.DOTALL):
        for line in match.splitlines():
            parts = line.strip().split()
            if parts and not parts[0].startswith("//"):
                deps.append(parts[0].lower())

    # Also single-line requires
    for match in re.findall(r"^require\s+(\S+)", text, re.MULTILINE):
        deps.append(match.lower())

    return deps


def detect_frameworks(repo_path: Path, project_type: str) -> list[str]:
    """Detect frameworks used in the project."""
    found: list[str] = []

    if project_type in ("python", "docker-only"):
        deps = _read_python_deps(repo_path)
        for framework, patterns in PYTHON_FRAMEWORKS.items():
            if any(p in deps for p in patterns):
                found.append(framework)

    if project_type == "node":
        deps = _read_node_deps(repo_path)
        for framework, patterns in NODE_FRAMEWORKS.items():
            if any(p in deps for p in patterns):
                found.append(framework)

    if project_type == "go":
        deps = _read_go_deps(repo_path)
        for framework, patterns in GO_FRAMEWORKS.items():
            if any(p.lower() in deps for p in patterns):
                found.append(framework)

    return found

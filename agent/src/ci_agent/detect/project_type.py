"""Detect the primary project type from marker files."""

from __future__ import annotations

from pathlib import Path

# Ordered by priority — first match wins for primary type
MARKERS = {
    "python": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"],
    "node": ["package.json"],
    "go": ["go.mod"],
    "rust": ["Cargo.toml"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
}


def detect_project_type(repo_path: Path) -> tuple[str, list[str]]:
    """Return (primary_type, all_detected_types).

    If only a Dockerfile is found with no language markers, returns 'docker-only'.
    """
    detected: list[str] = []

    for lang, markers in MARKERS.items():
        for marker in markers:
            if (repo_path / marker).exists():
                if lang not in detected:
                    detected.append(lang)
                break

    if not detected:
        if (repo_path / "Dockerfile").exists():
            return "docker-only", ["docker-only"]
        return "unknown", []

    return detected[0], detected


def detect_python_version(repo_path: Path) -> str | None:
    """Extract Python version constraint from pyproject.toml."""
    pyproject = repo_path / "pyproject.toml"
    if not pyproject.exists():
        return None

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        return data.get("project", {}).get("requires-python")
    except Exception:
        # Fallback: regex parse
        import re

        text = pyproject.read_text()
        m = re.search(r'requires-python\s*=\s*"([^"]+)"', text)
        return m.group(1) if m else None


def detect_node_version(repo_path: Path) -> str | None:
    """Extract Node version from package.json or .nvmrc."""
    nvmrc = repo_path / ".nvmrc"
    if nvmrc.exists():
        return nvmrc.read_text().strip()

    pkg = repo_path / "package.json"
    if pkg.exists():
        import json

        try:
            data = json.loads(pkg.read_text())
            return data.get("engines", {}).get("node")
        except Exception:
            return None
    return None


def detect_go_version(repo_path: Path) -> str | None:
    """Extract Go version from go.mod."""
    gomod = repo_path / "go.mod"
    if not gomod.exists():
        return None

    import re

    text = gomod.read_text()
    m = re.search(r"^go\s+(\S+)", text, re.MULTILINE)
    return m.group(1) if m else None

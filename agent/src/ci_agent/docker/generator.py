"""Generate Dockerfile at runtime from the golden template + repo config.

The golden Dockerfile lives in scp-ci-templates/dockerfiles/agent.Dockerfile.
Per-repo customization comes from .ci-agent.yml in the caller repo.

Supported .ci-agent.yml fields for Docker:
  docker:
    python_version: "3.11"         # Base Python version (default: 3.11)
    port: 8000                     # Exposed port (default: 8000)
    entrypoint: '["uvicorn", "my_pkg.main:app", "--host", "0.0.0.0", "--port", "8000"]'
    extra_system_packages: []      # apt packages for runtime (e.g., ["libpq5"])
    extra_build_packages: []       # apt packages for build (e.g., ["libpq-dev", "gcc"])
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

# Defaults if .ci-agent.yml doesn't specify
DEFAULTS = {
    "python_version": "3.11",
    "port": 8000,
    "entrypoint": None,  # Auto-detected from pyproject.toml
    "extra_system_packages": [],
    "extra_build_packages": [],
}


def load_docker_config(repo_path: Path) -> dict:
    """Load Docker config from .ci-agent.yml, merged with defaults."""
    config = dict(DEFAULTS)

    ci_agent_yml = repo_path / ".ci-agent.yml"
    if ci_agent_yml.exists():
        try:
            data = yaml.safe_load(ci_agent_yml.read_text())
            if isinstance(data, dict) and "docker" in data:
                docker_config = data["docker"]
                for key in DEFAULTS:
                    if key in docker_config:
                        config[key] = docker_config[key]
        except Exception:
            pass

    # Auto-detect entrypoint if not specified
    if config["entrypoint"] is None:
        config["entrypoint"] = _detect_entrypoint(repo_path, config["port"])

    return config


def _detect_entrypoint(repo_path: Path, port: int) -> str:
    """Auto-detect the entrypoint from pyproject.toml or common patterns."""
    # Check pyproject.toml for [project.scripts]
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text()

        # Look for package name to guess uvicorn target
        m = re.search(r'name\s*=\s*"([^"]+)"', text)
        if m:
            pkg_name = m.group(1).replace("-", "_")

            # Check if main.py or app.py exists in src/{pkg}/
            for entry in ["main:app", "app:app"]:
                filename = entry.split(":")[0] + ".py"
                candidate = repo_path / "src" / pkg_name / filename
                if candidate.exists():
                    return json.dumps(["uvicorn", f"{pkg_name}.{entry}", "--host", "0.0.0.0", "--port", str(port)])

    # Fallback: generic uvicorn
    return json.dumps(["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(port)])


def _apt_install_block(packages: list[str], comment: str) -> str:
    """Generate an apt-get install block, or empty string if no packages."""
    if not packages:
        return ""
    pkgs = " ".join(packages)
    return (
        f"# {comment}\n"
        f"RUN apt-get update && apt-get install -y --no-install-recommends {pkgs} && "
        f"rm -rf /var/lib/apt/lists/*"
    )


def generate_dockerfile(
    template_path: Path,
    repo_path: Path,
    output_path: Path | None = None,
) -> str:
    """Generate a Dockerfile from the golden template + repo config.

    Args:
        template_path: Path to agent.Dockerfile template.
        repo_path: Path to the caller repo root.
        output_path: If set, write the generated Dockerfile here.

    Returns:
        The generated Dockerfile content.
    """
    config = load_docker_config(repo_path)
    template = template_path.read_text()

    # Replace placeholders
    dockerfile = template
    dockerfile = dockerfile.replace("{{python_version}}", str(config["python_version"]))
    dockerfile = dockerfile.replace("{{port}}", str(config["port"]))
    dockerfile = dockerfile.replace("{{entrypoint}}", config["entrypoint"])
    dockerfile = dockerfile.replace(
        "{{extra_build_packages}}",
        _apt_install_block(config["extra_build_packages"], "Extra build dependencies"),
    )
    dockerfile = dockerfile.replace(
        "{{extra_runtime_packages}}",
        _apt_install_block(config["extra_system_packages"], "Extra runtime dependencies"),
    )

    # Clean up empty lines from unused placeholders
    dockerfile = re.sub(r'\n{3,}', '\n\n', dockerfile)

    if output_path:
        output_path.write_text(dockerfile)

    return dockerfile

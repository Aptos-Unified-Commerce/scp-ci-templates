"""Lightweight security checks on the repository."""

from __future__ import annotations

import re
from pathlib import Path

# Files that should never be committed
SENSITIVE_FILES = [
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "service-account.json",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
]

# Patterns in file content that indicate secrets
SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"(?i)(password|secret|token|api_key)\s*=\s*['\"][^'\"]+['\"]", "Hardcoded credential"),
    (r"-----BEGIN (RSA |EC )?PRIVATE KEY-----", "Private key in source"),
]


def run_security_checks(repo_path: Path) -> list[str]:
    """Return a list of security warnings."""
    warnings: list[str] = []

    # Check for sensitive files
    for pattern in SENSITIVE_FILES:
        if "*" in pattern:
            matches = list(repo_path.glob(pattern))
        else:
            matches = [repo_path / pattern] if (repo_path / pattern).exists() else []
        for match in matches:
            # Skip if in .gitignore patterns (simplified check)
            if not _is_gitignored(repo_path, match):
                warnings.append(f"Sensitive file detected: `{match.relative_to(repo_path)}`")

    # Check Dockerfile for USER root
    dockerfile = repo_path / "Dockerfile"
    if dockerfile.exists():
        content = dockerfile.read_text()
        if "USER root" in content and content.rstrip().endswith("USER root"):
            warnings.append("Dockerfile runs as root — consider adding a non-root USER")
        if re.search(r"ENV\s+.*(?:PASSWORD|SECRET|TOKEN|API_KEY)\s*=", content, re.IGNORECASE):
            warnings.append("Dockerfile contains secrets in ENV — use build args or secrets mount")

    # Check for unpinned dependencies
    _check_unpinned_deps(repo_path, warnings)

    # Quick scan of Python/JS files for hardcoded secrets (only top-level files and src/)
    _scan_for_secrets(repo_path, warnings)

    return warnings


def _is_gitignored(repo_path: Path, file_path: Path) -> bool:
    """Simplified gitignore check — just check if the pattern exists in .gitignore."""
    gitignore = repo_path / ".gitignore"
    if not gitignore.exists():
        return False
    patterns = gitignore.read_text().splitlines()
    rel = str(file_path.relative_to(repo_path))
    for pattern in patterns:
        pattern = pattern.strip()
        if not pattern or pattern.startswith("#"):
            continue
        if pattern in rel or rel.startswith(pattern):
            return True
    return False


def _check_unpinned_deps(repo_path: Path, warnings: list[str]) -> None:
    """Check for completely unpinned dependencies (no version constraint at all)."""
    req_file = repo_path / "requirements.txt"
    if req_file.exists():
        for line in req_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                if not any(op in line for op in ["==", ">=", "<=", "~=", "!=", ">"]):
                    warnings.append(f"Unpinned dependency in requirements.txt: `{line}`")


def _scan_for_secrets(repo_path: Path, warnings: list[str], max_files: int = 100) -> None:
    """Scan source files for hardcoded secrets."""
    extensions = {".py", ".js", ".ts", ".go", ".java", ".yaml", ".yml", ".toml", ".json"}
    scanned = 0

    for path in repo_path.rglob("*"):
        if scanned >= max_files:
            break
        if not path.is_file():
            continue
        if path.suffix not in extensions:
            continue
        # Skip common non-source directories
        parts = path.parts
        if any(skip in parts for skip in [".git", "node_modules", ".venv", "venv", "__pycache__", "dist"]):
            continue

        try:
            content = path.read_text(errors="ignore")
        except Exception:
            continue

        scanned += 1

        for pattern, description in SECRET_PATTERNS:
            if re.search(pattern, content):
                rel = path.relative_to(repo_path)
                warnings.append(f"{description} in `{rel}`")
                break  # One warning per file

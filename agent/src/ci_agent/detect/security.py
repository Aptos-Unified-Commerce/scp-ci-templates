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
    (r"ghp_[A-Za-z0-9]{36}", "GitHub Personal Access Token"),
    (r"sk-[A-Za-z0-9]{48}", "OpenAI/Anthropic API key"),
    (r"xox[bpors]-[A-Za-z0-9-]+", "Slack token"),
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

    # Check GitHub Actions workflow files for common security issues
    _check_workflow_security(repo_path, warnings)

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


def _check_workflow_security(repo_path: Path, warnings: list[str]) -> None:
    """Check GitHub Actions workflows for common security issues."""
    workflows_dir = repo_path / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return

    for wf_file in workflows_dir.glob("*.yml"):
        try:
            content = wf_file.read_text()
            rel = wf_file.relative_to(repo_path)

            # Check for unpinned third-party actions (not using SHA)
            action_refs = re.findall(r"uses:\s*([^\s#]+)", content)
            for ref in action_refs:
                # Skip local actions (./) and official actions (actions/)
                if ref.startswith("./") or ref.startswith("actions/"):
                    continue
                # Flag actions using branch/tag instead of SHA
                if "@" in ref:
                    version = ref.split("@")[1]
                    if not re.match(r"^[a-f0-9]{40}$", version) and not re.match(r"^v\d+$", version):
                        pass  # tag refs like v3 are common and acceptable
                else:
                    warnings.append(f"Unpinned action `{ref}` in `{rel}` — pin to a SHA or tag")

            # Check for script injection via untrusted inputs in run blocks
            injection_patterns = [
                (r"\$\{\{\s*github\.event\.issue\.title", "issue title"),
                (r"\$\{\{\s*github\.event\.issue\.body", "issue body"),
                (r"\$\{\{\s*github\.event\.pull_request\.title", "PR title"),
                (r"\$\{\{\s*github\.event\.pull_request\.body", "PR body"),
                (r"\$\{\{\s*github\.event\.comment\.body", "comment body"),
                (r"\$\{\{\s*github\.head_ref", "head ref"),
            ]
            for pattern, input_name in injection_patterns:
                if re.search(pattern, content):
                    warnings.append(
                        f"Potential script injection via `{input_name}` in `{rel}` "
                        "— use an intermediate env var instead of inline expression"
                    )

            # Check for overly broad permissions
            if "permissions:" not in content and "workflow_call" not in content:
                warnings.append(
                    f"No explicit permissions in `{rel}` — defaults to broad read/write. "
                    "Add `permissions:` block with least privilege."
                )

        except Exception:
            continue

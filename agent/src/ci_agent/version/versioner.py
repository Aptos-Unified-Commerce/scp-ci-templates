"""Semantic versioning based on conventional commits and git tags.

Version strategy:
  - Reads current version from pyproject.toml (or git tags)
  - Analyzes commits since last tag using conventional commit prefixes
  - Determines bump type: major, minor, or patch
  - Outputs the new version

Conventional commits:
  - feat:     → minor bump
  - fix:      → patch bump
  - feat!: / BREAKING CHANGE: → major bump
  - chore/docs/ci/test/refactor: → patch bump (if any changes)
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VersionInfo:
    current: str
    new: str
    bump_type: str  # major, minor, patch, none
    commits_analyzed: int
    breaking_changes: list[str]
    features: list[str]
    fixes: list[str]

    def to_dict(self) -> dict:
        return {
            "current": self.current,
            "new": self.new,
            "bump_type": self.bump_type,
            "commits_analyzed": self.commits_analyzed,
            "breaking_changes": self.breaking_changes,
            "features": self.features,
            "fixes": self.fixes,
        }


DEFAULT_VERSION = "0.0.1"


def get_current_version(repo_path: Path) -> str:
    """Get current version from pyproject.toml, package.json, or git tag.

    If no version source exists at all, returns DEFAULT_VERSION (0.0.1).
    """
    # Try pyproject.toml first
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text()
        m = re.search(r'version\s*=\s*"([^"]+)"', text)
        if m:
            return m.group(1)

    # Try package.json
    pkg = repo_path / "package.json"
    if pkg.exists():
        import json
        try:
            data = json.loads(pkg.read_text())
            return data.get("version", DEFAULT_VERSION)
        except Exception:
            pass

    # Try latest git tag
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, cwd=repo_path,
        )
        if result.returncode == 0:
            tag = result.stdout.strip().lstrip("v")
            return tag
    except Exception:
        pass

    return DEFAULT_VERSION


MAX_COMMITS_TO_ANALYZE = 500


def get_commits_since_tag(repo_path: Path) -> list[str]:
    """Get commit messages since the last tag.

    Limits to MAX_COMMITS_TO_ANALYZE to prevent unbounded git log on repos
    with many commits since the last tag (or no tags at all).
    """
    try:
        # Find last tag
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, cwd=repo_path,
        )
        if result.returncode == 0:
            last_tag = result.stdout.strip()
            log_range = f"{last_tag}..HEAD"
        else:
            log_range = "HEAD"

        result = subprocess.run(
            ["git", "log", log_range, f"--max-count={MAX_COMMITS_TO_ANALYZE}",
             "--pretty=format:%s"],
            capture_output=True, text=True, cwd=repo_path, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass

    return []


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse a semver string into (major, minor, patch)."""
    parts = version.split(".")
    try:
        return int(parts[0]), int(parts[1] if len(parts) > 1 else 0), int(parts[2] if len(parts) > 2 else 0)
    except (ValueError, IndexError):
        return 0, 0, 0


def bump_version(current: str, bump_type: str) -> str:
    """Apply a semver bump."""
    major, minor, patch = parse_version(current)

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return current


def classify_commits(commits: list[str]) -> tuple[str, list[str], list[str], list[str]]:
    """Classify commits and determine bump type.

    Returns (bump_type, breaking_changes, features, fixes).
    """
    breaking: list[str] = []
    features: list[str] = []
    fixes: list[str] = []
    has_changes = False

    for msg in commits:
        has_changes = True
        lower = msg.lower()

        # Breaking changes
        if "!" in msg.split(":")[0] if ":" in msg else False:
            breaking.append(msg)
        elif "breaking change" in lower:
            breaking.append(msg)
        # Features
        elif lower.startswith("feat"):
            features.append(msg)
        # Fixes
        elif lower.startswith("fix"):
            fixes.append(msg)

    if breaking:
        return "major", breaking, features, fixes
    elif features:
        return "minor", breaking, features, fixes
    elif has_changes:
        return "patch", breaking, features, fixes
    return "none", [], [], []


def compute_next_version(repo_path: Path) -> VersionInfo:
    """Analyze the repo and compute the next semantic version."""
    current = get_current_version(Path(repo_path))
    commits = get_commits_since_tag(Path(repo_path))
    bump_type, breaking, features, fixes = classify_commits(commits)
    new_version = bump_version(current, bump_type) if bump_type != "none" else current

    return VersionInfo(
        current=current,
        new=new_version,
        bump_type=bump_type,
        commits_analyzed=len(commits),
        breaking_changes=breaking,
        features=features,
        fixes=fixes,
    )


def apply_version(repo_path: Path, new_version: str) -> list[str]:
    """Update version in project files. Creates pyproject.toml if missing.

    Creates backup files (.bak) before modifying, so the caller can roll back
    if a subsequent step (e.g., publish) fails.

    Returns list of files modified/created.
    """
    modified: list[str] = []
    path = Path(repo_path)

    pyproject = path / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text()
        # Back up before modification
        (path / "pyproject.toml.bak").write_text(text)

        if re.search(r'version\s*=\s*"[^"]+"', text):
            # Update existing version field
            new_text = re.sub(
                r'(version\s*=\s*)"[^"]+"',
                f'\\1"{new_version}"',
                text,
                count=1,
            )
            if new_text != text:
                pyproject.write_text(new_text)
                modified.append("pyproject.toml")
        else:
            # pyproject.toml exists but has no version — inject it after [project]
            if "[project]" in text:
                new_text = text.replace(
                    "[project]",
                    f'[project]\nversion = "{new_version}"',
                    1,
                )
                pyproject.write_text(new_text)
                modified.append("pyproject.toml")
    else:
        # No pyproject.toml — create a minimal one
        repo_name = path.name
        pyproject.write_text(
            f'[project]\nname = "{repo_name}"\nversion = "{new_version}"\n'
            f'requires-python = ">=3.11"\n\n'
            f'[build-system]\nrequires = ["setuptools>=61.0"]\n'
            f'build-backend = "setuptools.build_meta"\n'
        )
        modified.append("pyproject.toml (created)")

    # Update package.json if present
    pkg = path / "package.json"
    if pkg.exists():
        import json
        try:
            text = pkg.read_text()
            (path / "package.json.bak").write_text(text)
            data = json.loads(text)
            data["version"] = new_version
            pkg.write_text(json.dumps(data, indent=2) + "\n")
            modified.append("package.json")
        except Exception:
            pass

    return modified


def rollback_version(repo_path: Path) -> list[str]:
    """Restore version files from backups created by apply_version.

    Call this if a publish step fails after version was applied.
    Returns list of files restored.
    """
    restored: list[str] = []
    path = Path(repo_path)

    for filename in ("pyproject.toml", "package.json"):
        backup = path / f"{filename}.bak"
        target = path / filename
        if backup.exists():
            target.write_text(backup.read_text())
            backup.unlink()
            restored.append(filename)

    return restored


def generate_changelog(info: VersionInfo) -> str:
    """Generate a changelog entry for the version bump."""
    lines = [f"## {info.new}\n"]

    if info.breaking_changes:
        lines.append("### Breaking Changes")
        for c in info.breaking_changes:
            lines.append(f"- {c}")
        lines.append("")

    if info.features:
        lines.append("### Features")
        for c in info.features:
            lines.append(f"- {c}")
        lines.append("")

    if info.fixes:
        lines.append("### Fixes")
        for c in info.fixes:
            lines.append(f"- {c}")
        lines.append("")

    return "\n".join(lines)

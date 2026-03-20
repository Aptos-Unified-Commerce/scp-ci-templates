"""Prompt and model artifact versioning.

Tracks AI artifacts (prompts, model configs, embedding configs) alongside
code versions. When prompt templates or model references change, they are
hashed and recorded so you know exactly which prompt/model version was
deployed with which code version.

Artifacts tracked:
  - Prompt templates (*.prompt, *.txt in prompts/ dir)
  - Model config files (model_config.yaml, model_config.json)
  - LLM provider configs (bedrock, openai, gemini settings)

Output: artifact manifest JSON with content hashes + code version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ArtifactEntry:
    """A single tracked artifact."""

    path: str
    content_hash: str  # SHA-256 of file content
    size_bytes: int = 0
    artifact_type: str = "prompt"  # prompt, model-config, embedding-config


@dataclass
class ArtifactManifest:
    """Manifest of all tracked AI artifacts for a given code version."""

    code_version: str = "0.0.0"
    commit_sha: str = ""
    artifacts: list[ArtifactEntry] = field(default_factory=list)
    manifest_hash: str = ""  # Combined hash of all artifacts

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, data: str) -> ArtifactManifest:
        parsed = json.loads(data)
        manifest = cls(
            code_version=parsed.get("code_version", "0.0.0"),
            commit_sha=parsed.get("commit_sha", ""),
            manifest_hash=parsed.get("manifest_hash", ""),
        )
        for a in parsed.get("artifacts", []):
            manifest.artifacts.append(ArtifactEntry(**{k: v for k, v in a.items() if k in ArtifactEntry.__dataclass_fields__}))
        return manifest

    def to_markdown(self) -> str:
        lines = [
            "### AI Artifact Manifest\n",
            f"**Code version:** `{self.code_version}`",
            f"**Commit:** `{self.commit_sha[:8]}`" if self.commit_sha else "",
            f"**Manifest hash:** `{self.manifest_hash[:12]}`\n" if self.manifest_hash else "",
        ]
        if self.artifacts:
            lines.append("| Artifact | Type | Hash | Size |")
            lines.append("|----------|------|------|------|")
            for a in self.artifacts:
                size = f"{a.size_bytes}B" if a.size_bytes < 1024 else f"{a.size_bytes / 1024:.1f}KB"
                lines.append(f"| `{a.path}` | {a.artifact_type} | `{a.content_hash[:12]}` | {size} |")
        else:
            lines.append("_No AI artifacts found._")
        return "\n".join(lines)


# Patterns for finding AI artifacts
ARTIFACT_PATTERNS = {
    "prompt": [
        "prompts/**/*.txt",
        "prompts/**/*.prompt",
        "prompts/**/*.md",
        "prompts/**/*.j2",
        "**/*prompt*.txt",
        "**/*prompt*.yaml",
        "**/*prompt*.yml",
    ],
    "model-config": [
        "**/model_config.yaml",
        "**/model_config.yml",
        "**/model_config.json",
        "**/llm_config.yaml",
        "**/llm_config.json",
        "config/models/**",
    ],
    "embedding-config": [
        "**/embedding_config.yaml",
        "**/embedding_config.json",
        "**/vector_config.yaml",
    ],
}

# Directories to skip
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".ci-templates"}


def _hash_file(path: Path) -> str:
    """SHA-256 hash of file content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_artifacts(repo_path: Path) -> list[ArtifactEntry]:
    """Scan repo for AI artifacts using pattern matching."""
    found: list[ArtifactEntry] = []
    seen_paths: set[str] = set()

    for artifact_type, patterns in ARTIFACT_PATTERNS.items():
        for pattern in patterns:
            for match in repo_path.glob(pattern):
                if not match.is_file():
                    continue
                # Skip common non-source dirs
                if any(skip in match.parts for skip in SKIP_DIRS):
                    continue
                rel = str(match.relative_to(repo_path))
                if rel in seen_paths:
                    continue
                seen_paths.add(rel)

                found.append(ArtifactEntry(
                    path=rel,
                    content_hash=_hash_file(match),
                    size_bytes=match.stat().st_size,
                    artifact_type=artifact_type,
                ))

    return sorted(found, key=lambda a: a.path)


def generate_manifest(
    repo_path: str,
    code_version: str = "0.0.0",
    commit_sha: str = "",
) -> ArtifactManifest:
    """Scan repo and generate an artifact manifest.

    The manifest records the content hash of every AI artifact (prompts,
    model configs) so you can track exactly which prompt/model version
    was deployed with which code version.
    """
    path = Path(repo_path)
    artifacts = _find_artifacts(path)

    # Combined hash of all artifacts
    combined = hashlib.sha256()
    for a in artifacts:
        combined.update(a.content_hash.encode())
    manifest_hash = combined.hexdigest() if artifacts else ""

    return ArtifactManifest(
        code_version=code_version,
        commit_sha=commit_sha,
        artifacts=artifacts,
        manifest_hash=manifest_hash,
    )


def has_artifacts_changed(old_manifest: ArtifactManifest, new_manifest: ArtifactManifest) -> bool:
    """Check if AI artifacts changed between two manifests."""
    return old_manifest.manifest_hash != new_manifest.manifest_hash


def save_manifest(manifest: ArtifactManifest, path: str) -> None:
    """Save manifest to file."""
    Path(path).write_text(manifest.to_json())


def load_manifest(path: str) -> ArtifactManifest | None:
    """Load manifest from file."""
    p = Path(path)
    if p.exists():
        return ArtifactManifest.from_json(p.read_text())
    return None

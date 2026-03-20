"""Tests for the AI artifact tracker."""

import json
from pathlib import Path

import pytest

from ci_agent.version.artifact_tracker import (
    ArtifactManifest,
    generate_manifest,
    has_artifacts_changed,
    load_manifest,
    save_manifest,
)


def test_generate_manifest_no_artifacts(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
    manifest = generate_manifest(str(tmp_path), code_version="0.1.0")
    assert manifest.code_version == "0.1.0"
    assert len(manifest.artifacts) == 0
    assert manifest.manifest_hash == ""


def test_generate_manifest_with_prompts(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system.txt").write_text("You are a helpful assistant.")
    (prompts_dir / "summarize.prompt").write_text("Summarize the following: {{text}}")

    manifest = generate_manifest(str(tmp_path), code_version="0.2.0")
    assert len(manifest.artifacts) == 2
    assert manifest.manifest_hash != ""
    assert all(a.artifact_type == "prompt" for a in manifest.artifacts)


def test_generate_manifest_with_model_config(tmp_path):
    (tmp_path / "model_config.yaml").write_text("model: claude-3\ntemperature: 0.0\n")
    manifest = generate_manifest(str(tmp_path))
    assert len(manifest.artifacts) == 1
    assert manifest.artifacts[0].artifact_type == "model-config"


def test_manifest_changes_detected(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system.txt").write_text("Version 1")

    old = generate_manifest(str(tmp_path), code_version="0.1.0")

    (prompts_dir / "system.txt").write_text("Version 2 — updated prompt")

    new = generate_manifest(str(tmp_path), code_version="0.1.1")

    assert has_artifacts_changed(old, new) is True


def test_manifest_no_change(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system.txt").write_text("Same content")

    m1 = generate_manifest(str(tmp_path))
    m2 = generate_manifest(str(tmp_path))

    assert has_artifacts_changed(m1, m2) is False


def test_save_and_load_manifest(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "test.txt").write_text("Hello")

    manifest = generate_manifest(str(tmp_path), code_version="1.0.0", commit_sha="abc123")
    path = str(tmp_path / "manifest.json")

    save_manifest(manifest, path)
    loaded = load_manifest(path)

    assert loaded is not None
    assert loaded.code_version == "1.0.0"
    assert len(loaded.artifacts) == 1
    assert loaded.manifest_hash == manifest.manifest_hash


def test_load_nonexistent_manifest(tmp_path):
    result = load_manifest(str(tmp_path / "nope.json"))
    assert result is None


def test_manifest_to_markdown(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "system.txt").write_text("Test prompt")

    manifest = generate_manifest(str(tmp_path), code_version="0.5.0")
    md = manifest.to_markdown()
    assert "AI Artifact Manifest" in md
    assert "0.5.0" in md
    assert "system.txt" in md


def test_manifest_to_json_roundtrip(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "a.txt").write_text("prompt a")

    original = generate_manifest(str(tmp_path), code_version="1.2.3")
    restored = ArtifactManifest.from_json(original.to_json())

    assert restored.code_version == "1.2.3"
    assert len(restored.artifacts) == len(original.artifacts)
    assert restored.manifest_hash == original.manifest_hash

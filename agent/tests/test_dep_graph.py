"""Tests for the dependency graph module."""

import json
from pathlib import Path

import pytest

from ci_agent.deps.graph import (
    DependencyGraph,
    RepoNode,
    extract_internal_deps,
    register_repo,
)


@pytest.fixture
def sample_graph():
    graph = DependencyGraph()
    graph.add_node(RepoNode(name="scp-ai-platform", role="framework", version="0.2.0"))
    graph.add_node(RepoNode(name="scp-common-utils", role="framework", version="0.1.0"))
    graph.add_node(RepoNode(
        name="scp-agent-orders", role="agent", version="0.3.0",
        dependencies=["scp-ai-platform", "scp-common-utils"],
    ))
    graph.add_node(RepoNode(
        name="scp-agent-runner", role="agent", version="0.1.0",
        dependencies=["scp-ai-platform"],
    ))
    return graph


def test_get_dependents(sample_graph):
    deps = sample_graph.get_dependents("scp-ai-platform")
    assert "scp-agent-orders" in deps
    assert "scp-agent-runner" in deps
    assert len(deps) == 2


def test_get_dependents_none(sample_graph):
    deps = sample_graph.get_dependents("scp-agent-orders")
    assert deps == []


def test_get_dependencies(sample_graph):
    deps = sample_graph.get_dependencies("scp-agent-orders")
    assert "scp-ai-platform" in deps
    assert "scp-common-utils" in deps


def test_get_frameworks(sample_graph):
    frameworks = sample_graph.get_frameworks()
    names = [f.name for f in frameworks]
    assert "scp-ai-platform" in names
    assert "scp-common-utils" in names
    assert len(frameworks) == 2


def test_get_agents(sample_graph):
    agents = sample_graph.get_agents()
    assert len(agents) == 2


def test_cascade_targets(sample_graph):
    targets = sample_graph.get_cascade_targets("scp-ai-platform")
    assert "scp-agent-orders" in targets
    assert "scp-agent-runner" in targets


def test_cascade_targets_unknown(sample_graph):
    targets = sample_graph.get_cascade_targets("nonexistent")
    assert targets == []


def test_serialize_roundtrip(sample_graph):
    json_str = sample_graph.to_json()
    restored = DependencyGraph.from_json(json_str)
    assert len(restored.nodes) == 4
    assert restored.nodes["scp-agent-orders"].dependencies == ["scp-ai-platform", "scp-common-utils"]


def test_save_and_load(sample_graph, tmp_path):
    path = str(tmp_path / "graph.json")
    sample_graph.save(path)
    loaded = DependencyGraph.load(path)
    assert len(loaded.nodes) == 4


def test_load_nonexistent(tmp_path):
    graph = DependencyGraph.load(str(tmp_path / "nonexistent.json"))
    assert len(graph.nodes) == 0


def test_to_markdown(sample_graph):
    md = sample_graph.to_markdown()
    assert "scp-ai-platform" in md
    assert "scp-agent-orders" in md
    assert "Dependency Graph" in md


def test_extract_internal_deps(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "scp-agent-orders"\n'
        'dependencies = ["scp-ai-platform>=0.2.0", "fastapi", "boto3"]\n'
    )
    known = ["scp-ai-platform", "scp-common-utils"]
    deps = extract_internal_deps(tmp_path, known)
    assert "scp-ai-platform" in deps
    assert "scp-common-utils" not in deps


def test_extract_internal_deps_requirements_txt(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "scp-ai-platform>=0.2.0\nfastapi\nscp-common-utils\n"
    )
    known = ["scp-ai-platform", "scp-common-utils"]
    deps = extract_internal_deps(tmp_path, known)
    assert "scp-ai-platform" in deps
    assert "scp-common-utils" in deps


def test_register_repo(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "scp-agent-new"\n'
        'dependencies = ["scp-ai-platform", "fastapi"]\n'
    )
    graph = DependencyGraph()
    graph.add_node(RepoNode(name="scp-ai-platform", role="framework", version="0.2.0"))

    graph = register_repo(graph, "scp-agent-new", "agent", "0.1.0", tmp_path)

    assert "scp-agent-new" in graph.nodes
    assert "scp-ai-platform" in graph.nodes["scp-agent-new"].dependencies

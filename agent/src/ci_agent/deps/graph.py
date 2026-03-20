"""Dependency graph — maps which agents depend on which frameworks.

Parses pyproject.toml/requirements.txt across repos to build a dependency
graph. Used for:
  - Cascade builds: when a framework publishes, trigger dependent agent builds
  - Breaking change detection: check if API changes break consumers
  - Dependency health: dashboard of which version each agent uses

The graph is stored as a JSON file and updated during each build.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class RepoNode:
    """A node in the dependency graph."""

    name: str  # e.g., scp-ai-platform
    role: str  # framework or agent
    version: str = "0.0.0"
    dependencies: list[str] = field(default_factory=list)  # Names of repos this depends on
    dependents: list[str] = field(default_factory=list)  # Names of repos that depend on this

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> RepoNode:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DependencyGraph:
    """The full dependency graph across repos."""

    nodes: dict[str, RepoNode] = field(default_factory=dict)  # name → RepoNode
    updated_at: str = ""

    def add_node(self, node: RepoNode) -> None:
        self.nodes[node.name] = node

    def get_dependents(self, framework_name: str) -> list[str]:
        """Get all repos that depend on a given framework."""
        return [
            name for name, node in self.nodes.items()
            if framework_name in node.dependencies
        ]

    def get_dependencies(self, repo_name: str) -> list[str]:
        """Get all repos that a given repo depends on."""
        node = self.nodes.get(repo_name)
        return node.dependencies if node else []

    def get_frameworks(self) -> list[RepoNode]:
        """Get all framework nodes."""
        return [n for n in self.nodes.values() if n.role == "framework"]

    def get_agents(self) -> list[RepoNode]:
        """Get all agent nodes."""
        return [n for n in self.nodes.values() if n.role == "agent"]

    def get_cascade_targets(self, framework_name: str) -> list[str]:
        """Get repos that should be rebuilt when a framework changes.

        Includes transitive dependents (if agent A depends on framework F1,
        and framework F1 depends on framework F0, then changing F0 should
        trigger F1 and then A).
        """
        targets = []
        visited = set()

        def _walk(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            for dep_name, node in self.nodes.items():
                if name in node.dependencies and dep_name not in visited:
                    targets.append(dep_name)
                    _walk(dep_name)

        _walk(framework_name)
        return targets

    def to_json(self) -> str:
        return json.dumps({
            "nodes": {name: node.to_dict() for name, node in self.nodes.items()},
            "updated_at": self.updated_at,
        }, indent=2)

    @classmethod
    def from_json(cls, data: str) -> DependencyGraph:
        parsed = json.loads(data)
        graph = cls(updated_at=parsed.get("updated_at", ""))
        for name, node_data in parsed.get("nodes", {}).items():
            graph.nodes[name] = RepoNode.from_dict(node_data)
        return graph

    def to_markdown(self) -> str:
        """Render the graph as a markdown summary."""
        lines = ["## Dependency Graph\n"]

        frameworks = self.get_frameworks()
        agents = self.get_agents()

        if frameworks:
            lines.append("### Frameworks (libraries)")
            lines.append("| Name | Version | Dependents |")
            lines.append("|------|---------|-----------|")
            for f in frameworks:
                dependents = self.get_dependents(f.name)
                dep_str = ", ".join(f"`{d}`" for d in dependents) if dependents else "_none_"
                lines.append(f"| `{f.name}` | {f.version} | {dep_str} |")
            lines.append("")

        if agents:
            lines.append("### Agents (services)")
            lines.append("| Name | Version | Dependencies |")
            lines.append("|------|---------|-------------|")
            for a in agents:
                deps_str = ", ".join(f"`{d}`" for d in a.dependencies) if a.dependencies else "_none_"
                lines.append(f"| `{a.name}` | {a.version} | {deps_str} |")
            lines.append("")

        return "\n".join(lines)

    def save(self, path: str) -> None:
        Path(path).write_text(self.to_json())

    @classmethod
    def load(cls, path: str) -> DependencyGraph:
        p = Path(path)
        if p.exists():
            return cls.from_json(p.read_text())
        return cls()


def extract_internal_deps(repo_path: Path, known_packages: list[str]) -> list[str]:
    """Extract dependencies from pyproject.toml that match known internal packages.

    Args:
        repo_path: Path to the repo root.
        known_packages: List of known internal package names (e.g., ["scp-ai-platform"]).

    Returns:
        List of internal dependency names found.
    """
    deps: list[str] = []

    # Normalize known packages for matching
    known_normalized = {p.lower().replace("-", "_").replace(".", "_"): p for p in known_packages}

    # Parse pyproject.toml
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        text = pyproject.read_text()
        for match in re.findall(r'"([a-zA-Z0-9_.-]+)', text):
            normalized = match.lower().replace("-", "_").replace(".", "_")
            if normalized in known_normalized:
                deps.append(known_normalized[normalized])

    # Parse requirements.txt
    req_file = repo_path / "requirements.txt"
    if req_file.exists():
        for line in req_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name = re.split(r"[>=<!\[;]", line)[0].strip()
            normalized = name.lower().replace("-", "_").replace(".", "_")
            if normalized in known_normalized:
                deps.append(known_normalized[normalized])

    return list(set(deps))


def register_repo(
    graph: DependencyGraph,
    repo_name: str,
    repo_role: str,
    version: str,
    repo_path: Path,
) -> DependencyGraph:
    """Register or update a repo in the dependency graph.

    Scans the repo's dependencies and updates the graph.
    """
    from datetime import datetime, timezone

    known_packages = list(graph.nodes.keys())
    internal_deps = extract_internal_deps(repo_path, known_packages)

    node = RepoNode(
        name=repo_name,
        role=repo_role,
        version=version,
        dependencies=internal_deps,
    )
    graph.add_node(node)
    graph.updated_at = datetime.now(timezone.utc).isoformat()

    return graph

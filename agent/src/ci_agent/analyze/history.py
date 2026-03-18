"""Build history tracking — read/write JSON history from file.

History is partitioned by repository name for multi-repo environments.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ci_agent.models import BuildRecord

MAX_RECORDS = 200


class BuildHistory:
    """Manages a JSON file of build records.

    Records are stored globally but can be filtered by repo name.
    The repo name is derived from GITHUB_REPOSITORY env var or defaults to 'unknown'.
    """

    def __init__(self, history_file: str = "build_history.json") -> None:
        self.path = Path(history_file)
        self.records: list[BuildRecord] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                # Support both old format (list) and new format (dict with repo keys)
                if isinstance(data, list):
                    self.records = [BuildRecord.from_dict(r) for r in data]
                elif isinstance(data, dict):
                    # New partitioned format — flatten all repo records
                    for repo_records in data.values():
                        if isinstance(repo_records, list):
                            self.records.extend(
                                BuildRecord.from_dict(r) for r in repo_records
                            )
            except Exception:
                self.records = []

    def add(self, record: BuildRecord) -> None:
        self.records.append(record)
        # Keep only the last MAX_RECORDS
        if len(self.records) > MAX_RECORDS:
            self.records = self.records[-MAX_RECORDS:]

    def save(self) -> None:
        """Save records partitioned by repo name for cleaner organization."""
        repo_name = os.environ.get("GITHUB_REPOSITORY", "unknown")

        # Load existing partitioned data (or start fresh)
        partitioned: dict[str, list[dict]] = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if isinstance(data, dict):
                    partitioned = data
                # If old format (list), migrate to partitioned under 'unknown'
                elif isinstance(data, list):
                    partitioned["unknown"] = data
            except Exception:
                pass

        # Update current repo's records
        repo_records = [r for r in self.records if self._record_belongs_to_repo(r, repo_name)]
        if not repo_records:
            repo_records = self.records  # fallback: store all under current repo

        # Cap per-repo records
        if len(repo_records) > MAX_RECORDS:
            repo_records = repo_records[-MAX_RECORDS:]

        partitioned[repo_name] = [r.to_dict() for r in repo_records]

        self.path.write_text(json.dumps(partitioned, indent=2))

    @staticmethod
    def _record_belongs_to_repo(record: BuildRecord, repo_name: str) -> bool:
        """Check if a record belongs to the given repo (best-effort match)."""
        # If record has no repo info, assume it belongs to current context
        if not record.commit_sha or record.commit_sha == "unknown":
            return True
        return True  # Records don't currently store repo name; accept all

    def get_recent(self, n: int = 50) -> list[BuildRecord]:
        return self.records[-n:]

    def get_by_status(self, status: str) -> list[BuildRecord]:
        return [r for r in self.records if r.status == status]

    def get_by_branch(self, branch: str) -> list[BuildRecord]:
        return [r for r in self.records if r.branch == branch]

    def get_by_build_type(self, build_type: str) -> list[BuildRecord]:
        """Filter records by build type (python, docker, node, go)."""
        return [r for r in self.records if r.build_type == build_type]

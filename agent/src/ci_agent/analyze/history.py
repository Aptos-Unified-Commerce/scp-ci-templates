"""Build history tracking — read/write JSON history from file."""

from __future__ import annotations

import json
from pathlib import Path

from ci_agent.models import BuildRecord

MAX_RECORDS = 200


class BuildHistory:
    """Manages a JSON file of build records."""

    def __init__(self, history_file: str = "build_history.json") -> None:
        self.path = Path(history_file)
        self.records: list[BuildRecord] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                self.records = [BuildRecord.from_dict(r) for r in data]
            except Exception:
                self.records = []

    def add(self, record: BuildRecord) -> None:
        self.records.append(record)
        # Keep only the last MAX_RECORDS
        if len(self.records) > MAX_RECORDS:
            self.records = self.records[-MAX_RECORDS:]

    def save(self) -> None:
        self.path.write_text(json.dumps([r.to_dict() for r in self.records], indent=2))

    def get_recent(self, n: int = 50) -> list[BuildRecord]:
        return self.records[-n:]

    def get_by_status(self, status: str) -> list[BuildRecord]:
        return [r for r in self.records if r.status == status]

    def get_by_branch(self, branch: str) -> list[BuildRecord]:
        return [r for r in self.records if r.branch == branch]

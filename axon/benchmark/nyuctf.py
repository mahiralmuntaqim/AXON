"""NYU CTF Bench adapter (SEGMENT 11).

Role: SOTA comparison (CRAKEN, D-CIPHER). Contamination: HIGH risk — many tasks are CSAW
challenges, which is exactly why the provenance firewall excludes CSAW *write-ups* from graph
construction (the firewall guards the graph, not the benchmark tasks).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..harness.base import Task
from .base_loader import BenchmarkHarnessBase


class NyuCtfHarness(BenchmarkHarnessBase):
    name = "nyuctf"
    role = "SOTA comparison (CRAKEN, D-CIPHER)"
    contamination = "HIGH risk"
    supports_dry_run = False

    def _to_task(self, entry: dict) -> Task:
        cat = entry.get("category")
        return Task(
            task_id=entry["id"],
            goal=self.default_goal,
            category=cat or "misc",
            root_node_id=self._root_node_for(cat),
            metadata={
                "benchmark": self.name,
                "split": entry.get("split", ""),
                "year": str(entry.get("year", "")),
                "event": str(entry.get("event", "")),
                "challenge": entry.get("challenge", ""),
                "path": entry.get("path", ""),
            },
        )

    # -- local challenge access (needs the full data repo, located via paths.py) -----------
    def challenge_dir(self, task: Task) -> Optional[Path]:
        """Absolute path to this task's challenge folder in the data repo, or None."""
        root = self.data_root()
        rel = task.metadata.get("path")
        if root is None or not rel:
            return None
        d = root / rel
        return d if d.is_dir() else None

    def challenge_detail(self, task: Task) -> Optional[dict]:
        """Full local ``challenge.json`` (name, description, box, files, flag), or None.

        Read from local data only — this carries the flag, so it is NEVER committed (the
        shipped index is metadata-only). Use it to actually attempt a challenge.
        """
        d = self.challenge_dir(task)
        if d is None:
            return None
        cj = d / "challenge.json"
        if not cj.is_file():
            return None
        detail = json.loads(cj.read_text(encoding="utf-8"))
        detail["_dir"] = str(d)
        detail["_networked"] = (d / "docker-compose.yml").is_file()
        return detail

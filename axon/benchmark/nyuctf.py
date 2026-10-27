"""NYU CTF Bench adapter (SEGMENT 11).

Role: SOTA comparison (CRAKEN, D-CIPHER). Contamination: HIGH risk — many tasks are CSAW
challenges, which is exactly why the provenance firewall excludes CSAW *write-ups* from graph
construction (the firewall guards the graph, not the benchmark tasks).
"""

from __future__ import annotations

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

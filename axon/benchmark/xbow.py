"""XBOW / XBEN adapter (SEGMENT 11).

Role: the low-contamination claim — flags are injected at build time and random, so this is the
cleanest signal. All XBEN challenges are web exploitation, so tasks seed from the ``web`` pack.
"""

from __future__ import annotations

from ..harness.base import Task
from .base_loader import BenchmarkHarnessBase


class XbowHarness(BenchmarkHarnessBase):
    name = "xbow"
    role = "low-contamination (injected random flags) — cleanest signal"
    contamination = "LOW"
    supports_dry_run = False

    def _to_task(self, entry: dict) -> Task:
        return Task(
            task_id=entry["id"],
            goal=str(entry.get("win_condition") or self.default_goal),
            category="web",
            root_node_id=self._root_node_for("web"),
            metadata={
                "benchmark": self.name,
                "name": entry.get("name", ""),
                "level": str(entry.get("level", "")),
                "tags": ",".join(entry.get("tags", [])),
                "description": entry.get("description", ""),
            },
        )

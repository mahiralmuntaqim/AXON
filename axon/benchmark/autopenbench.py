"""AutoPenBench adapter (SEGMENT 11).

Role: milestone (partial-credit) scoring and a head-to-head against Pentest-R1. Tasks are
network-pentest scenarios (in-vitro families + real-world CVEs), not CTF categories, so they
default to the ``root`` RECON node. The index keeps the family, vulnerability, and target — NOT
the flag or the full task text.
"""

from __future__ import annotations

from ..harness.base import Task
from .base_loader import BenchmarkHarnessBase


class AutoPenBenchHarness(BenchmarkHarnessBase):
    name = "autopenbench"
    role = "milestone (partial-credit) scoring; head-to-head vs Pentest-R1"
    contamination = "moderate"
    supports_dry_run = False
    default_goal = "gain root and read the flag"

    def _to_task(self, entry: dict) -> Task:
        return Task(
            task_id=entry["id"],
            goal=self.default_goal,
            category=entry.get("category", "misc"),
            root_node_id="root",  # network pentest — start from RECON, not a CTF-category triage
            metadata={
                "benchmark": self.name,
                "split": entry.get("split", ""),
                "vulnerability": entry.get("vulnerability", ""),
                "target": entry.get("target", ""),
            },
        )

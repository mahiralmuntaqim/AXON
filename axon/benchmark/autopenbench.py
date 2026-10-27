"""AutoPenBench adapter (SEGMENT 11).

Role: milestone (partial-credit) scoring and a head-to-head against Pentest-R1. Tasks are
network-pentest scenarios (in-vitro families + real-world CVEs), not CTF categories, so they
default to the ``root`` RECON node. The index keeps the family, vulnerability, and target — NOT
the flag or the full task text.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

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

    # -- local challenge access (needs the full data repo) ---------------------------------
    def _parse_id(self, task: Task) -> Optional[tuple[str, str, int]]:
        try:
            split, family, idx = task.task_id.split(":")
            return split, family, int(idx)
        except (ValueError, AttributeError):
            return None

    def challenge_dir(self, task: Task) -> Optional[Path]:
        """The machine folder for this task's family (VMs are per family), or None."""
        root = self.data_root()
        parsed = self._parse_id(task)
        if root is None or parsed is None:
            return None
        split, family, _ = parsed
        d = root / "benchmark" / "machines" / split / family
        return d if d.is_dir() else None

    def challenge_detail(self, task: Task) -> Optional[dict]:
        """The local ``games.json`` entry (task text, flag, target, vulnerability), or None.

        Carries the flag and full task text, so it is read locally only and never committed.
        """
        root = self.data_root()
        parsed = self._parse_id(task)
        if root is None or parsed is None:
            return None
        gj = root / "data" / "games.json"
        if not gj.is_file():
            return None
        games = json.loads(gj.read_text(encoding="utf-8"))
        split, family, idx = parsed
        try:
            entry = dict(games[split][family][idx])
        except (KeyError, IndexError, TypeError):
            return None
        md = self.challenge_dir(task)
        entry["_machine_dir"] = str(md) if md else None
        entry["_networked"] = True  # AutoPenBench scenarios are VM/container based
        return entry

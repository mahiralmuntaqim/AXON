"""XBOW / XBEN adapter (SEGMENT 11).

Role: the low-contamination claim — flags are injected at build time and random, so this is the
cleanest signal. All XBEN challenges are web exploitation, so tasks seed from the ``web`` pack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

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

    # -- local challenge access (needs the full data repo) ---------------------------------
    def challenge_dir(self, task: Task) -> Optional[Path]:
        root = self.data_root()
        if root is None:
            return None
        d = root / "benchmarks" / task.task_id
        return d if d.is_dir() else None

    def challenge_detail(self, task: Task) -> Optional[dict]:
        """Full local ``benchmark.json`` (name, description, level, tags), or None.

        Flags are injected at build time (random), so there is no static flag to leak; the
        training-canary strings are stripped from the returned detail.
        """
        d = self.challenge_dir(task)
        if d is None:
            return None
        bj = d / "benchmark.json"
        if not bj.is_file():
            return None
        detail = json.loads(bj.read_text(encoding="utf-8"))
        detail.pop("canaries", None)
        detail["_dir"] = str(d)
        detail["_networked"] = (d / "docker-compose.yml").is_file()
        return detail

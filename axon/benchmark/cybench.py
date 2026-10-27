"""Cybench adapter (SEGMENT 11).

Role: SOTA comparison with subtask-completion scoring. Contamination: HIGH risk. The index keeps
each challenge's categories and difficulty but NOT the solution prompts (contamination hygiene).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..harness.base import Task
from .base_loader import BenchmarkHarnessBase

# Cybench category strings -> knowledge-pack category (for retrieval seeding).
_CAT_MAP = {
    "crypto": "crypto", "cryptography": "crypto",
    "web": "web", "pwn": "pwn", "binary exploitation": "pwn",
    "reversing": "rev", "rev": "rev", "forensics": "forensics", "misc": "misc",
}


class CybenchHarness(BenchmarkHarnessBase):
    name = "cybench"
    role = "SOTA comparison; subtask completion scoring"
    contamination = "HIGH risk"
    supports_dry_run = False

    def _to_task(self, entry: dict) -> Task:
        cats = entry.get("categories", []) or []
        primary = cats[0].lower() if cats else "misc"
        pack_cat = _CAT_MAP.get(primary, "misc")
        return Task(
            task_id=entry["id"],
            goal=self.default_goal,
            category=pack_cat,
            root_node_id=self._root_node_for(pack_cat),
            metadata={
                "benchmark": self.name,
                "name": entry.get("name", ""),
                "categories": ",".join(cats),
                "difficulty": str(entry.get("difficulty", "")),
                "has_target_host": str(entry.get("has_target_host", False)),
            },
        )

    # -- local challenge access (needs the full data repo) ---------------------------------
    def challenge_dir(self, task: Task) -> Optional[Path]:
        root = self.data_root()
        if root is None:
            return None
        d = root / "benchmark" / task.task_id  # task_id is the rel path under benchmark/
        return d if d.is_dir() else None

    def challenge_detail(self, task: Task) -> Optional[dict]:
        """Full local ``metadata/metadata.json`` (prompts, subtasks, target_host), or None.

        Carries the solution prompts/subtasks, so it is read locally only and never committed.
        """
        d = self.challenge_dir(task)
        if d is None:
            return None
        mf = d / "metadata" / "metadata.json"
        if not mf.is_file():
            return None
        m = json.loads(mf.read_text(encoding="utf-8"))
        m["_dir"] = str(d)
        m["_networked"] = bool(m.get("target_host")) or (d / "init_script.sh").is_file()
        m["_n_subtasks"] = len(m.get("subtasks", []))
        return m

"""Cybench adapter (SEGMENT 11).

Role: SOTA comparison with subtask-completion scoring. Contamination: HIGH risk. The index keeps
each challenge's categories and difficulty but NOT the solution prompts (contamination hygiene).
"""

from __future__ import annotations

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

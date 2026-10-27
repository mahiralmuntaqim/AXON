"""Shared base for benchmark adapters — real task loading from the committed indices.

Each adapter implements the :class:`~axon.harness.base.BenchmarkHarness` protocol:

* ``load_tasks()`` reads the metadata-only index in ``indices/<name>.json`` and returns real
  :class:`~axon.harness.base.Task` objects (ids, categories, metadata) — this works offline, no
  heavy data needed;
* ``start()`` needs the full challenge data (located via :mod:`axon.benchmark.paths`) plus a
  container runtime, so it is a clearly-labeled stub until wired per deployment;
* ``teardown()`` is a no-op (nothing persisted).

Where a benchmark's category matches one of the knowledge-pack categories (crypto/pwn/rev/web/
forensics/misc), the task's ``root_node_id`` points at that category's ``<cat>::triage`` node so
retrieval seeds from the right place; otherwise it defaults to ``"root"``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..harness.base import Task, TaskEnvironment
from .paths import benchmark_root

INDICES_DIR = Path(__file__).resolve().parent / "indices"
PACK_CATEGORIES = {"crypto", "pwn", "rev", "web", "forensics", "misc"}


class BenchmarkDataUnavailable(RuntimeError):
    """Raised by start() when the heavy benchmark data / runtime is not wired up."""


class BenchmarkHarnessBase:
    name: str = ""
    role: str = ""
    contamination: str = ""
    supports_dry_run: bool = False
    default_goal: str = "capture the flag"

    def index_path(self) -> Path:
        return INDICES_DIR / f"{self.name}.json"

    def load_index(self) -> dict:
        p = self.index_path()
        if not p.is_file():
            raise FileNotFoundError(
                f"{self.name}: task index {p} missing — run "
                f"`python -m axon.benchmark.build_indices` with the data present"
            )
        return json.loads(p.read_text(encoding="utf-8"))

    def load_tasks(self) -> list[Task]:
        return [self._to_task(e) for e in self.load_index().get("tasks", [])]

    def data_root(self) -> Optional[Path]:
        return benchmark_root(self.name)

    def _root_node_for(self, category: Optional[str]) -> str:
        cat = (category or "").lower()
        return f"{cat}::triage" if cat in PACK_CATEGORIES else "root"

    # Subclasses override this.
    def _to_task(self, entry: dict) -> Task:  # pragma: no cover - overridden
        raise NotImplementedError

    def start(self, task: Task) -> TaskEnvironment:
        root = self.data_root()
        where = f"data at {root}" if root else (
            "data NOT found — set AXON_BENCH_ROOT or AXON_BENCH_" + self.name.upper()
        )
        raise BenchmarkDataUnavailable(
            f"STUB: {self.name}.start() needs the full challenge environment and a container "
            f"runtime, which are not wired in this build ({where}). load_tasks() works offline; "
            "execution is per-deployment work (SEGMENT 11/18)."
        )

    def teardown(self, env: TaskEnvironment) -> None:
        return None

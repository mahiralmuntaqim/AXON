"""Benchmark adapter STUBS (SEGMENT 11).

One adapter per benchmark, all behind :class:`~axon.harness.base.BenchmarkHarness`. These are
intentionally unimplemented: wiring them to real container/CTF environments is deployment work,
and per SEGMENT 18 none may be claimed to "work" until it has actually run a task end to end.

Each records the job it does in the evaluation and whether it supports a dry-run mode, because
the planner must know when irreversible actions cannot be used freely (SEGMENT 11).
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import BenchmarkHarness, Task, TaskEnvironment


@dataclass
class _StubHarness(BenchmarkHarness):
    name: str
    role: str                 # what this benchmark proves in the evaluation
    contamination: str        # contamination risk level / note
    supports_dry_run: bool

    def load_tasks(self) -> list[Task]:
        raise NotImplementedError(
            f"STUB: {self.name} harness not wired to real tasks. Role: {self.role}"
        )

    def start(self, task: Task) -> TaskEnvironment:  # pragma: no cover - stub
        raise NotImplementedError(f"STUB: {self.name}.start not implemented")

    def teardown(self, env: TaskEnvironment) -> None:  # pragma: no cover - stub
        return None


def vulhub() -> _StubHarness:
    return _StubHarness(
        "vulhub", role="real CVE exploitation; realistic long-horizon claim",
        contamination="low-moderate; use randomized/anonymized targets where possible",
        supports_dry_run=False,
    )


def autopenbench() -> _StubHarness:
    return _StubHarness(
        "autopenbench", role="milestone (partial-credit) scoring; head-to-head vs Pentest-R1",
        contamination="moderate", supports_dry_run=False,
    )


def xbow() -> _StubHarness:
    return _StubHarness(
        "xbow", role="low-contamination claim; flags injected at build time and random — "
        "the cleanest signal",
        contamination="low (injected random flags)", supports_dry_run=False,
    )


def cybench() -> _StubHarness:
    return _StubHarness(
        "cybench", role="comparison to SOTA; subtask completion scoring",
        contamination="HIGH risk", supports_dry_run=False,
    )


def nyuctf() -> _StubHarness:
    return _StubHarness(
        "nyuctf", role="comparison to SOTA (CRAKEN, D-CIPHER)",
        contamination="HIGH risk", supports_dry_run=False,
    )


# vulhub stays a pure stub (no data provided). The other four now have REAL adapters in
# axon.benchmark that load actual task lists from committed indices — use those.
from ..benchmark.registry import BENCHMARKS as _REAL_BENCHMARKS  # noqa: E402

ALL_BENCHMARKS = {
    "vulhub": vulhub,          # stub only
    "autopenbench": _REAL_BENCHMARKS["autopenbench"],
    "xbow": _REAL_BENCHMARKS["xbow"],
    "cybench": _REAL_BENCHMARKS["cybench"],
    "nyuctf": _REAL_BENCHMARKS["nyuctf"],
}

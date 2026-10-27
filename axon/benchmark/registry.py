"""Registry of benchmark adapters, keyed by name."""

from __future__ import annotations

from .autopenbench import AutoPenBenchHarness
from .base_loader import BenchmarkHarnessBase
from .cybench import CybenchHarness
from .nyuctf import NyuCtfHarness
from .xbow import XbowHarness

BENCHMARKS: dict[str, type[BenchmarkHarnessBase]] = {
    "nyuctf": NyuCtfHarness,
    "autopenbench": AutoPenBenchHarness,
    "cybench": CybenchHarness,
    "xbow": XbowHarness,
}


def get_harness(name: str) -> BenchmarkHarnessBase:
    key = name.strip().lower()
    if key not in BENCHMARKS:
        raise KeyError(f"unknown benchmark {name!r}; known: {sorted(BENCHMARKS)}")
    return BENCHMARKS[key]()

"""Locate the (heavy, un-vendored) benchmark data repos at runtime.

Resolution order for each benchmark:

1. ``AXON_BENCH_<NAME>`` env var (e.g. ``AXON_BENCH_NYUCTF``) — a full path to that repo.
2. ``AXON_BENCH_ROOT`` env var + the benchmark's folder name.
3. The default root (the location the benchmarks were built in) + the folder name.

Returns ``None`` when the data is not present, so loaders can still serve the committed task
index and only ``start()`` (which needs the real data) fails cleanly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Where the benchmarks live by default (override with AXON_BENCH_ROOT).
DEFAULT_BENCH_ROOT = Path(r"C:\Users\user\Desktop\agent pentest")

# Benchmark name -> its folder name under the bench root.
FOLDER = {
    "nyuctf": "NYU_CTF_Bench",
    "autopenbench": "auto-pen-bench",
    "cybench": "cybench",
    "xbow": "xbow",
}


def bench_root() -> Path:
    return Path(os.environ.get("AXON_BENCH_ROOT", str(DEFAULT_BENCH_ROOT)))


def benchmark_root(name: str) -> Optional[Path]:
    """Return the path to benchmark ``name``'s data repo, or None if not found."""
    if name not in FOLDER:
        raise KeyError(f"unknown benchmark {name!r}; known: {sorted(FOLDER)}")
    env = os.environ.get(f"AXON_BENCH_{name.upper()}")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.append(bench_root() / FOLDER[name])
    for c in candidates:
        if c.is_dir():
            return c
    return None

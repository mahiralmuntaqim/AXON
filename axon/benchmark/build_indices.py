"""Regenerate the committed, metadata-only task indices from the source benchmark repos.

Run:  python -m axon.benchmark.build_indices   (reads from paths.benchmark_root(...))

Only *metadata* is written — ids, categories, difficulty, tags. Flags and solution prompts are
deliberately NOT extracted, so the committed indices never carry benchmark solutions into the
repo (contamination hygiene, SEGMENT 12).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .paths import benchmark_root

INDICES_DIR = Path(__file__).resolve().parent / "indices"


def _write(name: str, payload: dict) -> Path:
    INDICES_DIR.mkdir(parents=True, exist_ok=True)
    out = INDICES_DIR / f"{name}.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return out


def build_nyuctf(root: Path) -> dict:
    tasks = []
    for split, fname in (("test", "test_dataset.json"), ("development", "development_dataset.json")):
        f = root / fname
        if not f.is_file():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        for cid, meta in data.items():
            tasks.append(
                {
                    "id": cid, "split": split,
                    "year": meta.get("year"), "event": meta.get("event"),
                    "category": meta.get("category"), "challenge": meta.get("challenge"),
                    "path": meta.get("path"),
                }
            )
    return {"benchmark": "nyuctf", "n": len(tasks), "tasks": tasks}


def build_autopenbench(root: Path) -> dict:
    games = json.loads((root / "data" / "games.json").read_text(encoding="utf-8"))
    tasks = []
    for split, families in games.items():
        for family, entries in families.items():
            for i, e in enumerate(entries):
                # Metadata only — no `flag`, no full `task` text.
                tasks.append(
                    {
                        "id": f"{split}:{family}:{i}", "split": split, "category": family,
                        "vulnerability": e.get("vulnerability"), "target": e.get("target"),
                    }
                )
    return {"benchmark": "autopenbench", "n": len(tasks), "tasks": tasks}


def build_cybench(root: Path) -> dict:
    bench = root / "benchmark"
    tasks = []
    for meta_file in sorted(bench.rglob("metadata/metadata.json")):
        try:
            m = json.loads(meta_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        challenge_dir = meta_file.parent.parent  # .../<challenge>/metadata/metadata.json
        rel = challenge_dir.relative_to(bench).as_posix()
        tasks.append(
            {
                "id": rel, "name": challenge_dir.name,
                "categories": m.get("categories", []),
                "difficulty": m.get("difficulty"),
                "has_target_host": bool(m.get("target_host")),
            }
        )
    return {"benchmark": "cybench", "n": len(tasks), "tasks": tasks}


def build_xbow(root: Path) -> dict:
    bench = root / "benchmarks"
    tasks = []
    for bj in sorted(bench.glob("*/benchmark.json")):
        try:
            m = json.loads(bj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        desc = (m.get("description") or "")[:200]
        tasks.append(
            {
                "id": bj.parent.name, "name": m.get("name"), "level": m.get("level"),
                "win_condition": m.get("win_condition"), "tags": m.get("tags", []),
                "description": desc,  # short blurb; canaries deliberately dropped
            }
        )
    return {"benchmark": "xbow", "n": len(tasks), "tasks": tasks}


_BUILDERS = {
    "nyuctf": build_nyuctf,
    "autopenbench": build_autopenbench,
    "cybench": build_cybench,
    "xbow": build_xbow,
}


def build_all() -> dict[str, Optional[int]]:
    results: dict[str, Optional[int]] = {}
    for name, builder in _BUILDERS.items():
        root = benchmark_root(name)
        if root is None:
            results[name] = None
            print(f"[skip] {name}: data not found (set AXON_BENCH_ROOT / AXON_BENCH_{name.upper()})")
            continue
        payload = builder(root)
        out = _write(name, payload)
        results[name] = payload["n"]
        print(f"[ok]   {name}: {payload['n']} tasks -> {out}")
    return results


if __name__ == "__main__":
    build_all()

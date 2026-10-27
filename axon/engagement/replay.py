"""Replay reconstruction from an event log (SEGMENT 17).

The visualizer is a web page, but the event log must carry enough to reconstruct the final
visual state from the base snapshot alone. This Python helper does that reconstruction at the
data level, so a test can prove "replay matches live": applying the logged events to the base
snapshot reaches the same final edge values the live run ended with.

Handles a log that just stops (a crashed run) because it is append-only and each event is
self-contained.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .events import Event, EventType


def load_log(path: str | Path) -> list[Event]:
    events: list[Event] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)  # a partial final line (crash) is simply skipped by splitlines
        events.append(Event(type=d["type"], step=d["step"], timestamp=d["timestamp"],
                            payload=d.get("payload", {})))
    return events


def reconstruct_edge_q(events: Iterable[Event]) -> dict[tuple, float]:
    """Return the final Q per edge by replaying SNAPSHOT (base) + WRITE (easing) events."""
    q: dict[tuple, float] = {}
    nodes_seen: set[str] = set()
    for ev in events:
        if ev.type == EventType.SNAPSHOT.value:
            for e in ev.payload.get("edges", []):
                # edges are [src, dst, type, Q]; key by the first three, seed with base Q.
                q[tuple(e[:3])] = float(e[3]) if len(e) > 3 else 0.5
            for n in ev.payload.get("nodes", []):
                nodes_seen.add(n["id"] if isinstance(n, dict) else n)
        elif ev.type == EventType.WRITE.value:
            edge = ev.payload.get("edge")
            new_q = ev.payload.get("new_Q")
            if edge is not None and new_q is not None:
                q[tuple(edge)] = float(new_q)
    return q

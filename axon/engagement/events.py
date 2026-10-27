"""Read-only event stream for the visualizer (SEGMENT 17).

The engagement loop *emits* events; the visualizer *consumes* them. This module only produces
and records events — it never writes to either graph and never influences a decision. If
removing the emitter changed a run, something would be wired wrong; the loop takes an emitter
but never reads anything back from it.

Events are appended to a JSON-lines log (replay mode reads this) and pushed to any registered
in-process listener (a live channel adapter can be one). Append-only, so a crash still leaves a
cleanly-terminated log.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional


class EventType(str, Enum):
    READ = "read"
    PRUNE = "prune"
    SELECT = "select"
    EXECUTE = "execute"
    VERIFY = "verify"
    WRITE = "write"
    BACKUP = "backup"
    BACKTRACK = "backtrack"
    BUDGET = "budget"
    SNAPSHOT = "snapshot"  # emitted once at start so a late live viewer gets the base graph


@dataclass
class Event:
    type: str
    step: int
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))


class EventEmitter:
    """Collects events, appends them to a JSONL log, and fans them out to listeners."""

    def __init__(self, log_path: Optional[str | Path] = None) -> None:
        self.log_path = Path(log_path) if log_path else None
        self._fh = open(self.log_path, "w", encoding="utf-8") if self.log_path else None
        self._listeners: list[Callable[[Event], None]] = []
        self.events: list[Event] = []  # kept in memory for tests/replay assembly

    def add_listener(self, listener: Callable[[Event], None]) -> None:
        self._listeners.append(listener)

    def emit(self, event_type: EventType, step: int, **payload: Any) -> Event:
        event = Event(type=event_type.value, step=step, timestamp=time.time(), payload=payload)
        self.events.append(event)
        if self._fh is not None:
            self._fh.write(event.to_json() + "\n")
            self._fh.flush()  # append-only + flushed: a crash leaves a readable log
        for listener in self._listeners:
            listener(event)
        return event

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


class NullEmitter(EventEmitter):
    """No-op emitter: proves the loop runs identically with no visualizer attached."""

    def __init__(self) -> None:
        super().__init__(log_path=None)

    def emit(self, event_type: EventType, step: int, **payload: Any) -> Event:
        # Record nothing, write nothing, notify no one.
        return Event(type=event_type.value, step=step, timestamp=0.0, payload=payload)

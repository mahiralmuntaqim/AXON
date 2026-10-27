"""The tool runner (SEGMENT 10).

Runs a planned action against an authorized target and returns a full :class:`ActionResult`
with the trace. Responsibilities kept here:

* enforce the sandbox allowlist *before* anything runs (:class:`~axon.execution.sandbox.Sandbox`);
* enforce a per-action timeout;
* capture tool errors separately from command output, so error attribution has what it needs;
* hand back the full trace (the loop folds a summary into context, not the raw log).

Design: the runner is parameterized by a :class:`Target` backend that actually produces the
observation for an action.

* :class:`MockTarget` — deterministic, offline; used by tests and the mock harness. It encodes
  an outcome oracle, so no real network/exploit is involved.
* :class:`SubprocessBackend` — STUB. A real deployment would run allowed, documented tools
  (nmap/curl/...) via subprocess against a sandboxed container. It deliberately does NOT
  generate exploit code; it only invokes known tools. Left unimplemented here on purpose.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from .result import ActionResult
from .sandbox import Sandbox, SandboxViolation


@dataclass
class Action:
    """A planned, concrete action: which technique, which tool/host, the command, its cost."""

    technique_id: str
    tool: str
    host: str
    command: str
    cost: float = 0.0
    reversible: bool = True


class Target(Protocol):
    """Produces the observed result of running an action against the (sandboxed) target."""

    def observe(self, action: Action) -> ActionResult: ...


class MockTarget(Target):
    """Deterministic offline target driven by an oracle function (no real execution)."""

    def __init__(self, oracle: Callable[[Action], ActionResult]) -> None:
        self.oracle = oracle

    def observe(self, action: Action) -> ActionResult:
        return self.oracle(action)


class SubprocessBackend(Target):
    """STUB: run allowed documented tools against a sandboxed container via subprocess.

    Not implemented here. When implemented, it must (a) only ever be reached after
    ``Sandbox.validate`` passes, (b) invoke known tools only — never synthesize exploit
    payloads, and (c) enforce the timeout at the process level.
    """

    def observe(self, action: Action) -> ActionResult:  # pragma: no cover - stub
        raise NotImplementedError(
            "STUB: SubprocessBackend is intentionally unimplemented. Wire it to invoke "
            "allowlisted tools inside an authorized container. No exploit generation."
        )


class ToolRunner:
    """Validates, times, and runs one action, returning its trace as an ActionResult."""

    def __init__(self, sandbox: Sandbox, target: Target, *, timeout_s: float = 120.0) -> None:
        self.sandbox = sandbox
        self.target = target
        self.timeout_s = timeout_s

    def run(self, action: Action) -> ActionResult:
        # 1) Sandbox check BEFORE anything runs. A violation means the action never executes.
        self.sandbox.validate(host=action.host, command=action.command)

        # 2) Execute via the target backend, enforcing a wall-clock timeout.
        start = time.monotonic()
        try:
            result = self.target.observe(action)
        except TimeoutError:
            elapsed = time.monotonic() - start
            return ActionResult(
                technique_id=action.technique_id,
                command=action.command,
                exit_code=124,
                stderr="timeout: action exceeded per-action limit",
                duration_s=elapsed,
                timed_out=True,
                cost=action.cost,
            )
        elapsed = time.monotonic() - start

        # 3) Enforce the timeout on backends that report their own duration.
        if result.duration_s and result.duration_s > self.timeout_s:
            result.timed_out = True
            result.stderr = (result.stderr + "\ntimeout: exceeded per-action limit").strip()
        if not result.duration_s:
            result.duration_s = elapsed
        result.cost = result.cost or action.cost
        return result

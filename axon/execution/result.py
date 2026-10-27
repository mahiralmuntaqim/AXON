"""Shared action-result types used by execution, verification, writeback, and the loop.

Kept in their own module so :mod:`axon.memory.verify`/`write` can depend on them without
importing the tool runner (avoids an import cycle).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..graph.schema import EpisodicFact


class TransitionKind(str, Enum):
    """Observable state transitions that count as real evidence of a success (SEGMENT 5)."""

    NEW_SHELL = "NEW_SHELL"                 # a new shell/session was obtained
    HTTP_UNBLOCKED = "HTTP_UNBLOCKED"       # e.g. HTTP 200 after a prior 403
    NEW_CREDENTIAL = "NEW_CREDENTIAL"       # valid credential recovered
    MILESTONE_FLAG = "MILESTONE_FLAG"       # harness-reported sub-milestone / flag
    PRIV_ESCALATED = "PRIV_ESCALATED"       # higher privilege confirmed
    SERVICE_DISCOVERED = "SERVICE_DISCOVERED"  # recon/enum finding (reversible, info-gathering)


@dataclass(frozen=True)
class StateTransition:
    """A single observable change, reported by the harness/tool from the real trace."""

    kind: TransitionKind
    detail: str = ""


@dataclass
class ActionResult:
    """The full result and trace of running one technique in the sandbox.

    The harness/tool populates ``state_transitions`` and ``milestone`` only from what actually
    happened. The verification gate trusts these as the trace, not the agent's claim.
    """

    technique_id: str
    command: str
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    timed_out: bool = False
    cost: float = 0.0

    # What the agent/tool *thinks* happened — never trusted without trace backing.
    claimed_success: bool = False
    claimed_outcome: str = ""

    # The trace evidence the gate actually checks.
    state_transitions: list[StateTransition] = field(default_factory=list)
    milestone: Optional[str] = None

    # Verified facts discovered, to add to the episodic graph after the gate.
    new_facts: list[EpisodicFact] = field(default_factory=list)

    @property
    def raw_trace(self) -> str:
        return (
            f"$ {self.command}\n[exit={self.exit_code} t={self.duration_s:.1f}s "
            f"timeout={self.timed_out}]\n{self.stdout}\n{self.stderr}"
        )

    def has_state_transition(self) -> bool:
        return bool(self.state_transitions) or self.milestone is not None

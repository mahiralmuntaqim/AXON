"""Reversibility tags and the irreversible-action gate (SEGMENT 7).

Every technique carries a :class:`~axon.graph.schema.Reversibility` tag. The safety rule:

* Reversible, information-gathering actions are always allowed.
* An irreversible action may run ONLY when its learned value ``Q(a) >= q_min`` AND a budget
  check passes. If the top-ranked action is irreversible and under the floor, prefer a
  reversible sibling, or backtrack — never fire it.

This is the safety-relevant choice, kept explicit here so it can be unit-tested directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..graph.schema import ProceduralEdge, Reversibility, TechniqueNode


@dataclass
class GateDecision:
    allowed: bool
    reason: str


def is_irreversible(node: TechniqueNode) -> bool:
    return node.reversibility is Reversibility.IRREVERSIBLE


def check_action(
    node: TechniqueNode,
    edge: ProceduralEdge,
    *,
    q_min: float,
    budget_ok: bool,
) -> GateDecision:
    """Decide whether this single action may execute."""
    if node.reversibility is Reversibility.REVERSIBLE:
        return GateDecision(True, "reversible action; always permitted")
    # Irreversible from here on.
    if edge.Q < q_min:
        return GateDecision(
            False, f"irreversible and Q={edge.Q:.3f} < q_min={q_min:.3f}; held back"
        )
    if not budget_ok:
        return GateDecision(False, "irreversible and budget check failed; held back")
    return GateDecision(True, f"irreversible but Q={edge.Q:.3f} >= q_min and budget ok")

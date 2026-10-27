"""Informed best-first / bandit search over the graph (SEGMENT 6).

Selection rule (PUCT style), blending the learned value with the LLM prior:

    score(a) = Q(a) + c_puct * P(a) * sqrt(N) / (1 + N(a))

where ``Q(a)`` is the learned edge value, ``P(a)`` the LLM prior, ``N`` the parent visit count,
and ``N(a)`` the edge visit count.

WHAT THIS IS NOT (SEGMENT 6): there is no Monte-Carlo tree search with environment resets and
no simulated rollouts. A live target cannot be rewound. Each expansion is ONE real action; the
trajectory within an engagement is a single line. The PUCT rule is a best-first/bandit
*selection* rule — its power shows *across* engagements, where each edge's Beta posterior
aggregates outcomes over many similarly-fingerprinted targets.

The loop lets the LLM prune the candidate edge set first (so the search stays small); this
module scores the survivors and picks the best, then backs the verified outcome up the path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from ..graph.procedural import ProceduralGraph
from ..graph.schema import ProceduralEdge
from .reversibility import GateDecision, check_action


@dataclass
class ScoredEdge:
    edge: ProceduralEdge
    score: float


def puct_score(edge: ProceduralEdge, parent_visits: int, c_puct: float) -> float:
    """The PUCT selection score for one edge."""
    exploration = c_puct * edge.P * math.sqrt(max(parent_visits, 0)) / (1 + edge.visits)
    return edge.Q + exploration


def parent_visit_count(graph: ProceduralGraph, node_id: str) -> int:
    """N: total visits across the node's out-edges, plus one (so a fresh node still explores)."""
    return 1 + sum(e.visits for e in graph.out_edges(node_id))


class Planner:
    """Scores candidate edges and applies the irreversible-action safety gate (SEGMENT 7)."""

    def __init__(self, cfg: dict, *, mode: str = "informed") -> None:
        pcfg = cfg.get("planning", {})
        self.c_puct = float(pcfg.get("c_puct", 1.4))
        self.backtrack_threshold = float(pcfg.get("backtrack_q_threshold", 0.2))
        self.q_min = float(cfg.get("safety", {}).get("q_min", 0.6))
        if mode not in ("informed", "breadth"):
            raise ValueError("mode must be 'informed' or 'breadth'")
        self.mode = mode  # 'breadth' = uninformed FIFO (ablation setting 4, SEGMENT 13)

    def rank(
        self, graph: ProceduralGraph, node_id: str, candidates: Sequence[ProceduralEdge]
    ) -> list[ScoredEdge]:
        """Rank candidate edges. Informed mode uses PUCT; breadth mode keeps insertion order.

        Breadth-first expands the frontier uninformed (a flat score), which is why it wastes
        budget on expensive/irreversible actions — the irreversibility gate in ``choose`` still
        applies, so it stays safe, just less efficient (SEGMENT 6 "Why not breadth-first").
        """
        if self.mode == "breadth":
            return [ScoredEdge(e, 1.0) for e in candidates]
        n = parent_visit_count(graph, node_id)
        scored = [ScoredEdge(e, puct_score(e, n, self.c_puct)) for e in candidates]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    def choose(
        self,
        graph: ProceduralGraph,
        node_id: str,
        candidates: Sequence[ProceduralEdge],
        *,
        budget_ok: bool = True,
    ) -> tuple[Optional[ScoredEdge], GateDecision]:
        """Pick the best *safe* action.

        Walks the ranked candidates and returns the first that clears the irreversibility gate.
        If the top choice is an irreversible action below ``q_min``, a reversible sibling is
        preferred automatically because it appears later in the same ranked list. Returns
        ``(None, decision)`` when nothing is allowed (the loop then backtracks).
        """
        ranked = self.rank(graph, node_id, candidates)
        last_decision = GateDecision(False, "no candidates")
        for scored in ranked:
            dst = graph.get_node(scored.edge.dst)
            if dst is None:
                continue
            decision = check_action(dst, scored.edge, q_min=self.q_min, budget_ok=budget_ok)
            if decision.allowed:
                return scored, decision
            last_decision = decision
        return None, last_decision

    def should_backtrack(self, best_score: Optional[float]) -> bool:
        """True when the current branch's best value is too low to keep pursuing."""
        return best_score is None or best_score < self.backtrack_threshold


def back_up(graph: ProceduralGraph, path: Sequence[tuple[str, str, str]]) -> None:
    """Increment the visit count along the traversed path (bandit backup).

    Value backup (Q) happens in the writeback via the Beta posterior; here we only bump the
    ``visits`` counters that drive PUCT exploration, for every edge actually traversed.
    """
    for src, dst, etype in path:
        for e in graph.out_edges(src):
            if e.key == (src, dst, etype):
                e.visits += 1
                break

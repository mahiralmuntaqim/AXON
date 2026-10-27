"""Verification-gated writeback — the three writes (SEGMENT 5).

Only runs after :class:`~axon.memory.verify.VerificationGate` passes. The three writes, none of
which touch the model:

1. **Edge value update** — a Bayesian Beta-posterior estimate
   ``Q = (n+ + alpha) / (n+ + n- + alpha + beta)``. One fluke only nudges Q; it cannot wipe a
   long-successful path (self-poisoning guard #1).
2. **Lesson distillation** — append a context-keyed lesson to the technique's experience record.
3. **Structural growth** — add a genuinely new node/edge, but only when a verified state
   transition backs it and error attribution cleared it (self-poisoning guard #2).

A hallucinated success or a tool error never reaches here (``verified`` is False), so the
durable graph stays clean.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..execution.result import ActionResult
from ..graph.procedural import ProceduralGraph
from ..graph.schema import (
    EdgeType,
    Lesson,
    NodeType,
    ProceduralEdge,
    Reversibility,
    TechniqueNode,
)
from ..knowledge.embeddings import Embedder
from ..llm.client import LLMClient
from .lessons import distill_lesson
from .verify import Attribution, VerificationResult


def beta_posterior(n_plus: int, n_minus: int, alpha: float, beta: float) -> float:
    """Posterior mean of a Beta(alpha, beta) prior after n+ successes and n- failures."""
    denom = n_plus + n_minus + alpha + beta
    if denom <= 0:
        return 0.5
    return (n_plus + alpha) / denom


@dataclass
class WriteReport:
    """What changed, for the event emitter / tests. Pure description, no side effects."""

    edge_key: Optional[tuple[str, str, str]] = None
    old_Q: Optional[float] = None
    new_Q: Optional[float] = None
    lesson_added: Optional[Lesson] = None
    new_node_id: Optional[str] = None
    new_edge_key: Optional[tuple[str, str, str]] = None
    wrote_anything: bool = False
    note: str = ""


class WritebackEngine:
    """Applies the three gated writes to G_K."""

    def __init__(
        self,
        cfg: dict,
        *,
        embedder: Optional[Embedder] = None,
        llm: Optional[LLMClient] = None,
    ) -> None:
        gcfg = cfg.get("graph", {})
        self.alpha = float(gcfg.get("alpha", 1.0))
        self.beta = float(gcfg.get("beta", 1.0))
        self.embedder = embedder
        self.llm = llm

    def write(
        self,
        graph: ProceduralGraph,
        *,
        edge: Optional[ProceduralEdge],
        node: TechniqueNode,
        verification: VerificationResult,
        result: ActionResult,
        state_context,
    ) -> WriteReport:
        """Apply the writes for one verified outcome. Returns a description of what changed.

        Caller MUST have confirmed ``verification.verified`` is True. We assert it here so a
        tool error or hallucination can never slip through.
        """
        if not verification.verified:
            # Defensive: the gate said don't write. Honor it; the durable graph stays clean.
            return WriteReport(wrote_anything=False, note="gate not passed; no write")

        report = WriteReport()
        success = verification.is_success

        # --- Write 1: edge value update (Beta posterior) ------------------------------------
        if edge is not None:
            report.edge_key = edge.key
            report.old_Q = edge.Q
            if success:
                edge.n_plus += 1
            else:
                edge.n_minus += 1
            edge.visits += 1
            edge.set_Q(beta_posterior(edge.n_plus, edge.n_minus, self.alpha, self.beta))
            report.new_Q = edge.Q
            report.wrote_anything = True

        # Mirror the counts onto the node's experience record.
        if success:
            node.experience.record_success()
        else:
            node.experience.record_failure()

        # --- Write 2: lesson distillation ---------------------------------------------------
        lesson = distill_lesson(
            technique_spec=node.spec,
            context=state_context,
            success=success,
            outcome_detail=verification.reason,
            llm=self.llm,
        )
        node.experience.add_lesson(lesson)
        report.lesson_added = lesson
        report.wrote_anything = True

        return report

    def grow(
        self,
        graph: ProceduralGraph,
        *,
        new_spec: str,
        node_type: NodeType,
        reversibility: Reversibility,
        from_node_id: str,
        edge_type: EdgeType,
        verification: VerificationResult,
        result: ActionResult,
        prior_P: float = 0.5,
        node_id: Optional[str] = None,
    ) -> WriteReport:
        """Write 3: structural growth.

        Promote a new technique/edge from episodic discovery to the procedural graph ONLY when a
        verified state transition backs it and error attribution cleared it (guard #2).
        """
        report = WriteReport()
        if not verification.verified or verification.attribution is not Attribution.REAL_SUCCESS:
            report.note = "growth rejected: not a verified success"
            return report
        if not result.has_state_transition():
            report.note = "growth rejected: no state transition in trace"
            return report

        nid = node_id or f"learned::{node_type.value}::{abs(hash(new_spec)) % 10**8}"
        if not graph.has_node(nid):
            embedding = self.embedder.embed(new_spec) if self.embedder else None
            graph.add_node(
                TechniqueNode(
                    id=nid,
                    node_type=node_type,
                    spec=new_spec,
                    embedding=embedding,
                    reversibility=reversibility,
                )
            )
            report.new_node_id = nid

        if graph.has_node(from_node_id) and graph.get_edge(from_node_id, nid, edge_type) is None:
            edge = ProceduralEdge(
                src=from_node_id, dst=nid, edge_type=edge_type, Q=0.5, P=prior_P
            )
            graph.add_edge(edge)
            report.new_edge_key = edge.key

        report.wrote_anything = bool(report.new_node_id or report.new_edge_key)
        return report

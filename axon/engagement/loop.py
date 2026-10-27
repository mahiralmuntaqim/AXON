"""The engagement loop — Algorithm 1 (SEGMENT 8).

One read-plan-act-write loop over a *single real trajectory* (rule 5: no environment resets, no
simulated rollouts). It wires together retrieval (READ), LLM pruning (PRUNE), PUCT selection
(SELECT), the irreversibility gate, execution (EXECUTE), the verification gate (VERIFY), the
episodic update, the gated writeback (WRITE), and value backup (BACKUP) — emitting a read-only
event at each moment for the visualizer.

The loop never crashes on an LLM or tool failure: pruning falls back to keeping all candidates,
a tool timeout returns a timed-out result the gate treats as a tool error, and budget
exhaustion stops it cleanly with partial progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..execution.result import ActionResult, TransitionKind
from ..execution.sandbox import SandboxViolation
from ..execution.tools import Action, ToolRunner
from ..graph.procedural import ProceduralGraph
from ..graph.schema import EdgeType, ProceduralEdge, Reversibility, TechniqueNode
from ..llm.client import LLMClient, LLMError
from ..llm.prompts import prune_candidates
from ..memory.read import MemoryReader, fold_result, state_summary
from ..memory.verify import VerificationGate
from ..memory.write import WritebackEngine
from ..planning.reversibility import is_irreversible
from ..planning.search import Planner, back_up
from .events import EventEmitter, EventType, NullEmitter
from .state import EngagementState

# A harness supplies this: turn a chosen technique into a concrete, sandbox-checkable action.
ActionFactory = Callable[[TechniqueNode, EngagementState], Action]
# A harness supplies this: did this verified result reach the engagement goal?
GoalCheck = Callable[[ActionResult, EngagementState], bool]


def default_goal_check(result: ActionResult, state: EngagementState) -> bool:
    """Default: the goal is reached on a harness-reported milestone/flag."""
    if result.milestone is not None:
        return True
    return any(t.kind is TransitionKind.MILESTONE_FLAG for t in result.state_transitions)


@dataclass
class EngagementOutcome:
    state: EngagementState
    graph: ProceduralGraph
    solved: bool
    steps: int
    cost: float


class EngagementLoop:
    def __init__(
        self,
        graph: ProceduralGraph,
        reader: MemoryReader,
        planner: Planner,
        gate: VerificationGate,
        writeback: WritebackEngine,
        runner: ToolRunner,
        *,
        action_factory: ActionFactory,
        goal_check: GoalCheck = default_goal_check,
        llm: Optional[LLMClient] = None,
        emitter: Optional[EventEmitter] = None,
        fold_max_chars: int = 800,
        enable_writeback: bool = True,
    ) -> None:
        # enable_writeback=False gives a static, read-only graph (ablation setting 3, SEGMENT 13).
        self.enable_writeback = enable_writeback
        self.graph = graph
        self.reader = reader
        self.planner = planner
        self.gate = gate
        self.writeback = writeback
        self.runner = runner
        self.action_factory = action_factory
        self.goal_check = goal_check
        self.llm = llm
        self.emitter = emitter or NullEmitter()
        self.fold_max_chars = fold_max_chars

    # -- helpers ------------------------------------------------------------------------------
    def _candidate_edges(self, state: EngagementState, frontier_ids: set[str]) -> list[ProceduralEdge]:
        """Out-edges of the current node whose destination is in the retrieved frontier."""
        out = self.graph.out_edges(state.current_node_id)
        if not out:
            return []
        relevant = [e for e in out if e.dst in frontier_ids] if frontier_ids else out
        return relevant or out

    def _prune(self, candidates: list[ProceduralEdge], summary: str) -> list[ProceduralEdge]:
        """LLM prunes clearly-irrelevant out-edges. Falls back to keeping all on any failure."""
        if not candidates or self.llm is None:
            return candidates
        listing = []
        by_id: dict[str, ProceduralEdge] = {}
        for e in candidates:
            eid = f"{e.src}->{e.dst}:{e.edge_type.value}"
            node = self.graph.get_node(e.dst)
            listing.append((eid, node.spec if node else e.dst))
            by_id[eid] = e
        try:
            parsed = self.llm.complete_json(
                prune_candidates(summary, listing),
                validate=lambda d: isinstance(d, dict) and isinstance(d.get("keep"), list),
            )
        except LLMError:
            return candidates  # graceful: keep everything rather than crash the step
        keep = {str(k) for k in parsed["keep"]}
        survivors = [by_id[k] for k in keep if k in by_id]
        return survivors or candidates

    def _backtrack(self, state: EngagementState, step: int) -> bool:
        """Jump to the best open frontier node. Returns False if there is nowhere to go."""
        choices = [n for n in state.open_frontier if n != state.current_node_id]
        if not choices:
            return False
        target = choices[0]
        state.current_node_id = target
        self.emitter.emit(EventType.BACKTRACK, step, to_node=target)
        return True

    # -- the loop -----------------------------------------------------------------------------
    def run(self, state: EngagementState) -> EngagementOutcome:
        # Emit the base graph once so a late live viewer starts from a known state.
        self.emitter.emit(
            EventType.SNAPSHOT, 0,
            nodes=[
                {"id": n.id, "type": n.node_type.value,
                 "reversible": n.reversibility.value == "REVERSIBLE"}
                for n in self.graph.nodes()
            ],
            edges=[[*e.key, e.Q, e.P] for e in self.graph.edges()],  # key + base Q,P for replay
        )

        while not state.budget.exhausted() and not state.goal_reached:
            step = state.budget.steps_used

            # a) READ
            retrieval = self.reader.retrieve(self.graph, state.episodic)
            frontier_ids = set(retrieval.node_ids)
            state.open_frontier = retrieval.node_ids
            self.emitter.emit(
                EventType.READ, step, frontier=retrieval.node_ids, seeds=retrieval.seed_ids
            )

            candidates = self._candidate_edges(state, frontier_ids)
            if not candidates:
                # Nothing reachable from here: try to backtrack, else stop cleanly.
                if not self._backtrack(state, step):
                    break
                continue

            # b) PRUNE
            summary = state_summary(state.episodic)
            survivors = self._prune(candidates, summary)
            self.emitter.emit(
                EventType.PRUNE, step,
                kept=[f"{e.src}->{e.dst}:{e.edge_type.value}" for e in survivors],
            )

            # c) SELECT + irreversibility gate (SEGMENT 7)
            budget_ok = state.budget.cost_remaining() > 0
            chosen, decision = self.planner.choose(
                self.graph, state.current_node_id, survivors, budget_ok=budget_ok
            )
            if chosen is None or self.planner.should_backtrack(chosen.score):
                if not self._backtrack(state, step):
                    break
                continue

            edge = chosen.edge
            dst_node = self.graph.get_node(edge.dst)
            assert dst_node is not None
            self.emitter.emit(
                EventType.SELECT, step,
                edge=list(edge.key), Q=edge.Q, P=edge.P, score=chosen.score,
                gate=decision.reason,
            )

            # e) EXECUTE
            action = self.action_factory(dst_node, state)
            if not state.budget.can_afford(action.cost):
                self.emitter.emit(EventType.BUDGET, step, reason="cannot afford next action",
                                  cost_used=state.budget.cost_used)
                break
            self.emitter.emit(
                EventType.EXECUTE, step, node=dst_node.id,
                irreversible=is_irreversible(dst_node),
            )
            try:
                result = self.runner.run(action)
            except SandboxViolation as exc:
                # Blocked by the allowlist: nothing ran. Note it, charge a step, move on.
                self.emitter.emit(EventType.VERIFY, step, blocked=str(exc), verified=False)
                state.budget.charge(action.cost)
                self.emitter.emit(EventType.BUDGET, step, steps_used=state.budget.steps_used,
                                  cost_used=state.budget.cost_used)
                if not self._backtrack(state, step):
                    break
                continue

            # f) VERIFY
            verification = self.gate.check(result)
            _ = fold_result(result.raw_trace, max_chars=self.fold_max_chars)  # keep context small
            self.emitter.emit(
                EventType.VERIFY, step, verified=verification.verified,
                outcome=verification.outcome.value, attribution=verification.attribution.value,
            )

            # g) episodic update (only verified facts land on the target map)
            if verification.verified:
                for fact in result.new_facts:
                    if state.episodic.get_fact(fact.id) is None:
                        state.episodic.add_fact(fact)

            # h) WRITE (gated; skipped entirely for a static read-only graph)
            if verification.verified and self.enable_writeback:
                report = self.writeback.write(
                    self.graph, edge=edge, node=dst_node, verification=verification,
                    result=result, state_context=retrieval.state_context,
                )
                self.emitter.emit(
                    EventType.WRITE, step, edge=list(edge.key),
                    old_Q=report.old_Q, new_Q=report.new_Q,
                    lesson=(report.lesson_added.text if report.lesson_added else None),
                )

            # i) BACKUP + advance / backtrack
            path = [(edge.src, edge.dst, edge.edge_type.value)]
            back_up(self.graph, path)
            self.emitter.emit(EventType.BACKUP, step, path=[list(p) for p in path])

            state.trajectory.append(
                {
                    "step": step, "node": dst_node.id, "edge": list(edge.key),
                    "verified": verification.verified, "outcome": verification.outcome.value,
                }
            )

            # j) budget
            state.budget.charge(result.cost)
            self.emitter.emit(
                EventType.BUDGET, step, steps_used=state.budget.steps_used,
                cost_used=state.budget.cost_used, cost_remaining=state.budget.cost_remaining(),
            )

            # k) goal check + movement
            if verification.is_success:
                if self.goal_check(result, state):
                    state.mark_goal()
                else:
                    state.current_node_id = dst_node.id  # advance along a verified success
            else:
                # Genuine failure: consider abandoning this branch.
                if self.planner.should_backtrack(edge.Q):
                    self._backtrack(state, step)

        return EngagementOutcome(
            state=state,
            graph=self.graph,
            solved=state.goal_reached,
            steps=state.budget.steps_used,
            cost=state.budget.cost_used,
        )

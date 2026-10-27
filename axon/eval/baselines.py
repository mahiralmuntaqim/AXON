"""Baselines to compare against AXON, behind the same engagement interface (SEGMENT 15).

Each baseline consumes a started :class:`~axon.harness.base.TaskEnvironment` and a pool of
candidate techniques, drives the *same* sandboxed tool runner and verification gate as AXON, and
returns a :class:`~axon.eval.metrics.TaskRun`. Keeping them behind one interface means the
metrics code doesn't care which agent produced the trajectory.

Implemented:
* :class:`ReActBaseline`            — frozen ReAct, no memory (fixed candidate order).
* :class:`HackSynthBaseline`        — rolling text-summary memory.
* :class:`VectorExperienceBaseline` — vector experience database (nearest past outcome).
* :func:`craken_static`             — CRAKEN-style static Graph-RAG, read-only (reuses the loop
                                      with writeback OFF; constructed in eval wiring).

Stub:
* :class:`PentestR1Baseline`        — wrap where a comparable harness exists (not implemented).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..execution.sandbox import Sandbox, SandboxViolation
from ..execution.tools import ToolRunner
from ..graph.schema import Reversibility, TechniqueNode
from ..harness.base import TaskEnvironment
from ..knowledge.embeddings import Embedder, cosine
from ..memory.read import state_summary
from ..memory.verify import VerificationGate
from .metrics import TaskRun


@dataclass
class _Driver:
    """Shared minimal engagement driver for baselines (single trajectory, sandbox + gate)."""

    cfg: dict
    env: TaskEnvironment

    def __post_init__(self) -> None:
        self.sandbox = Sandbox.from_config(self.cfg)
        self.runner = ToolRunner(
            self.sandbox, self.env.target,
            timeout_s=float(self.cfg.get("engagement", {}).get("per_action_timeout_s", 120)),
        )
        self.gate = VerificationGate(self.cfg)
        ecfg = self.cfg.get("engagement", {})
        self.step_budget = int(ecfg.get("step_budget", 40))
        self.cost_budget = float(ecfg.get("cost_budget", 5.0))

    def attempt(self, node: TechniqueNode, state):
        action = self.env.action_factory(node, state)
        try:
            result = self.runner.run(action)
        except SandboxViolation:
            return None
        return result


def _run_policy(driver: _Driver, pool: Sequence[TechniqueNode], policy) -> TaskRun:
    """Common loop: ask ``policy`` for the next technique until solved or budget runs out."""
    from ..graph.episodic import EpisodicGraph
    from ..engagement.state import Budget, EngagementState

    state = EngagementState(
        engagement_id=driver.env.task.task_id, goal=driver.env.task.goal,
        episodic=driver.env.episodic, budget=Budget(driver.step_budget, driver.cost_budget),
        current_node_id=driver.env.task.root_node_id,
    )
    solved = False
    while not state.budget.exhausted():
        node = policy.next(pool, state)
        if node is None:
            break
        result = driver.attempt(node, state)
        if result is None:
            state.budget.charge(0.0)
            continue
        verification = driver.gate.check(result)
        if verification.verified:
            for fact in result.new_facts:
                if state.episodic.get_fact(fact.id) is None:
                    state.episodic.add_fact(fact)
        policy.observe(node, result, verification, state)
        state.budget.charge(result.cost)
        if verification.is_success and driver.env.goal_check(result, state):
            solved = True
            break
    return TaskRun(
        task_id=driver.env.task.task_id, solved=solved, cost=state.budget.cost_used,
        milestones_total=len(driver.env.milestones) or 1,
    )


# --------------------------------------------------------------------------------------------
# Policies
# --------------------------------------------------------------------------------------------
class ReActBaseline:
    """Frozen ReAct, no memory: try reversible techniques first, in fixed order, once each."""

    def __init__(self) -> None:
        self._tried: set[str] = set()

    def next(self, pool, state) -> Optional[TechniqueNode]:
        ordered = sorted(
            pool, key=lambda n: 0 if n.reversibility is Reversibility.REVERSIBLE else 1
        )
        for node in ordered:
            if node.id not in self._tried:
                return node
        return None

    def observe(self, node, result, verification, state) -> None:
        self._tried.add(node.id)


class HackSynthBaseline:
    """Rolling text-summary memory: keeps a running summary string and avoids repeats."""

    def __init__(self) -> None:
        self.summary = ""
        self._tried: set[str] = set()

    def next(self, pool, state) -> Optional[TechniqueNode]:
        for node in pool:
            if node.id not in self._tried:
                return node
        return None

    def observe(self, node, result, verification, state) -> None:
        self._tried.add(node.id)
        line = f"[{verification.outcome.value}] {node.spec}"
        self.summary = (self.summary + "\n" + line)[-2000:]  # rolling window


class VectorExperienceBaseline:
    """Vector experience DB: retrieve the nearest past (state,action) and prefer repeats of wins."""

    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self.memory: list[tuple[list[float], str, bool]] = []  # (state_vec, node_id, success)
        self._tried: set[str] = set()

    def next(self, pool, state) -> Optional[TechniqueNode]:
        qv = self.embedder.embed(state_summary(state.episodic))
        # Prefer a technique that previously succeeded in a similar state.
        best_id, best_sim = None, 0.3
        for vec, nid, success in self.memory:
            if not success or nid in self._tried:
                continue
            sim = cosine(qv, vec)
            if sim > best_sim:
                best_id, best_sim = nid, sim
        if best_id is not None:
            node = next((n for n in pool if n.id == best_id), None)
            if node is not None:
                return node
        for node in pool:
            if node.id not in self._tried:
                return node
        return None

    def observe(self, node, result, verification, state) -> None:
        self._tried.add(node.id)
        self.memory.append(
            (self.embedder.embed(state_summary(state.episodic)), node.id,
             verification.is_success)
        )


class PentestR1Baseline:
    """STUB: wrap Pentest-R1 where a comparable harness exists (SEGMENT 15)."""

    def next(self, pool, state):  # pragma: no cover - stub
        raise NotImplementedError("STUB: Pentest-R1 baseline requires its own harness")

    def observe(self, *args, **kwargs):  # pragma: no cover - stub
        raise NotImplementedError


# --------------------------------------------------------------------------------------------
# Runner adapters (match the BaselineRunner signature used by experiment_a)
# --------------------------------------------------------------------------------------------
def make_react_runner(pool: Sequence[TechniqueNode]):
    def runner(cfg: dict, env: TaskEnvironment) -> TaskRun:
        return _run_policy(_Driver(cfg, env), pool, ReActBaseline())
    return runner


def make_hacksynth_runner(pool: Sequence[TechniqueNode]):
    def runner(cfg: dict, env: TaskEnvironment) -> TaskRun:
        return _run_policy(_Driver(cfg, env), pool, HackSynthBaseline())
    return runner


def make_vector_runner(pool: Sequence[TechniqueNode], embedder: Embedder):
    def runner(cfg: dict, env: TaskEnvironment) -> TaskRun:
        return _run_policy(_Driver(cfg, env), pool, VectorExperienceBaseline(embedder))
    return runner

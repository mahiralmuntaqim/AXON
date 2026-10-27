"""Engagement state and budget/cost tracking (SEGMENT 8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..graph.episodic import EpisodicGraph


@dataclass
class Budget:
    """Dual budget: a step count and a dollar cost. The loop stops cleanly when either runs out."""

    step_budget: int
    cost_budget: float
    steps_used: int = 0
    cost_used: float = 0.0

    def step_remaining(self) -> int:
        return self.step_budget - self.steps_used

    def cost_remaining(self) -> float:
        return self.cost_budget - self.cost_used

    def exhausted(self) -> bool:
        return self.steps_used >= self.step_budget or self.cost_used >= self.cost_budget

    def can_afford(self, cost: float) -> bool:
        return self.cost_used + cost <= self.cost_budget

    def charge(self, cost: float) -> None:
        self.steps_used += 1
        self.cost_used += cost


@dataclass
class EngagementState:
    """Everything about the current engagement except the persistent G_K."""

    engagement_id: str
    goal: str
    episodic: EpisodicGraph
    budget: Budget
    current_node_id: str
    goal_reached: bool = False
    # Open frontier nodes (episodic/procedural ids) to jump to when backtracking.
    open_frontier: list[str] = field(default_factory=list)
    trajectory: list[dict] = field(default_factory=list)  # one record per executed step
    # Edges that cannot work in THIS environment (sandbox-blocked or tool-error): excluded
    # from selection so the agent never loops on a dead action. Keyed by edge.key tuples.
    exhausted_edges: set = field(default_factory=set)

    def mark_goal(self) -> None:
        self.goal_reached = True

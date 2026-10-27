"""Common benchmark interface + engagement assembly (SEGMENT 11).

Every adapter exposes the same surface so the engagement loop never needs to know which
benchmark it is on: load tasks, start a task environment, provide an action factory + target +
goal check, report milestones, and tear down. Flag formats, milestone reporting, and teardown
differences stay inside each adapter.

``supports_dry_run`` tells the planner whether irreversible actions can be used freely; where
there is no dry run, the harness advertises it and the loop keeps the safety floor strict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..engagement.loop import ActionFactory, GoalCheck
from ..engagement.state import Budget, EngagementState
from ..execution.tools import Target
from ..graph.episodic import EpisodicGraph


@dataclass
class Task:
    """One benchmark task."""

    task_id: str
    goal: str
    category: str = "misc"
    root_node_id: str = "root"
    metadata: dict = field(default_factory=dict)


@dataclass
class TaskEnvironment:
    """A started task: the pieces the loop needs, bundled by the adapter."""

    task: Task
    target: Target
    action_factory: ActionFactory
    goal_check: GoalCheck
    episodic: EpisodicGraph
    supports_dry_run: bool = False
    milestones: list[str] = field(default_factory=list)

    def new_state(self, cfg: dict) -> EngagementState:
        ecfg = cfg.get("engagement", {})
        budget = Budget(
            step_budget=int(ecfg.get("step_budget", 40)),
            cost_budget=float(ecfg.get("cost_budget", 5.0)),
        )
        return EngagementState(
            engagement_id=self.task.task_id,
            goal=self.task.goal,
            episodic=self.episodic,
            budget=budget,
            current_node_id=self.task.root_node_id,
        )


class BenchmarkHarness(Protocol):
    name: str

    def load_tasks(self) -> list[Task]: ...
    def start(self, task: Task) -> TaskEnvironment: ...
    def teardown(self, env: TaskEnvironment) -> None: ...

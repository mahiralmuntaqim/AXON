"""Metrics (SEGMENT 14).

Computed the same way across benchmarks so numbers are comparable:

* ``success@k`` and overall solve rate (all suites);
* subtask/milestone completion (Cybench subtasks, AutoPenBench milestones) — credits
  long-horizon progress even without a full solve;
* dollar cost per solved task — central to the economic argument (memory-based learning avoids
  a training run).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, pstdev
from typing import Sequence


@dataclass
class TaskRun:
    """A single task attempt's result, benchmark-agnostic."""

    task_id: str
    solved: bool
    cost: float
    milestones_reached: int = 0
    milestones_total: int = 0
    attempt_index: int = 0  # 0-based attempt number for success@k


def solve_rate(runs: Sequence[TaskRun]) -> float:
    """Fraction of task *attempts* that solved. Uses the first attempt per task."""
    firsts = _first_attempts(runs)
    return mean([1.0 if r.solved else 0.0 for r in firsts]) if firsts else 0.0


def success_at_k(runs: Sequence[TaskRun], k: int) -> float:
    """Fraction of tasks solved within the first ``k`` attempts."""
    by_task: dict[str, list[TaskRun]] = {}
    for r in runs:
        by_task.setdefault(r.task_id, []).append(r)
    if not by_task:
        return 0.0
    solved = 0
    for attempts in by_task.values():
        first_k = sorted(attempts, key=lambda a: a.attempt_index)[:k]
        if any(a.solved for a in first_k):
            solved += 1
    return solved / len(by_task)


def milestone_completion(runs: Sequence[TaskRun]) -> float:
    """Average fraction of milestones reached (partial credit for long-horizon progress)."""
    firsts = _first_attempts(runs)
    fractions = [
        (r.milestones_reached / r.milestones_total)
        for r in firsts
        if r.milestones_total > 0
    ]
    return mean(fractions) if fractions else 0.0


def cost_per_solved(runs: Sequence[TaskRun]) -> float:
    """Total cost divided by number of solved tasks (inf-safe: returns total if none solved)."""
    total_cost = sum(r.cost for r in runs)
    solved = sum(1 for r in _first_attempts(runs) if r.solved)
    if solved == 0:
        return float("inf")
    return total_cost / solved


@dataclass
class MetricBand:
    """Mean +/- stdev across random orderings/seeds, reported as a band (SEGMENT 13)."""

    mean: float
    std: float
    n: int

    @classmethod
    def of(cls, values: Sequence[float]) -> "MetricBand":
        vals = list(values)
        if not vals:
            return cls(0.0, 0.0, 0)
        return cls(mean(vals), pstdev(vals) if len(vals) > 1 else 0.0, len(vals))


def _first_attempts(runs: Sequence[TaskRun]) -> list[TaskRun]:
    seen: dict[str, TaskRun] = {}
    for r in sorted(runs, key=lambda a: a.attempt_index):
        seen.setdefault(r.task_id, r)
    return list(seen.values())


@dataclass
class SuiteReport:
    suite: str
    solve_rate: float
    success_at_1: float
    milestone: float
    cost_per_solved: float
    n_tasks: int
    contamination_note: str = ""


def summarize(suite: str, runs: Sequence[TaskRun], *, contamination_note: str = "") -> SuiteReport:
    return SuiteReport(
        suite=suite,
        solve_rate=solve_rate(runs),
        success_at_1=success_at_k(runs, 1),
        milestone=milestone_completion(runs),
        cost_per_solved=cost_per_solved(runs),
        n_tasks=len({r.task_id for r in runs}),
        contamination_note=contamination_note,
    )

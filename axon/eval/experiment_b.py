"""Experiment B — continual learning (SEGMENT 13).

Does the graph get smarter across targets? The procedural graph ACCUMULATES over a sequence of
tasks. We plot solve rate and cost against the number of prior episodes seen, averaged over
several random task orderings and reported as a band (so a few lucky early solves can't look
like real learning). Report per category: expect transfer where procedural knowledge repeats
(Vulhub CVE classes, web categories), near-flat curves on one-off puzzles.

Graph-state snapshots are saved per step because graph-mutation learning is stochastic and must
be reproducible (SEGMENT 13).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..engagement.runner import run_engagement
from ..graph.persistence import save_procedural, serialize_procedural
from ..graph.procedural import ProceduralGraph
from ..harness.base import BenchmarkHarness
from ..knowledge.embeddings import Embedder
from ..llm.client import LLMClient
from .metrics import MetricBand


@dataclass
class LearningCurve:
    """Per-position solve/cost bands across orderings, indexed by episodes-seen position."""

    solve_band: list[MetricBand] = field(default_factory=list)
    cost_band: list[MetricBand] = field(default_factory=list)
    category: str = "all"


def run_experiment_b(
    cfg: dict,
    graph_factory,                     # () -> fresh seeded ProceduralGraph
    harness: BenchmarkHarness,
    embedder: Embedder,
    *,
    llm: Optional[LLMClient] = None,
    orderings: int = 5,
    seed: int = 0,
    snapshot_dir: Optional[str] = None,
    category: str = "all",
) -> LearningCurve:
    tasks = harness.load_tasks()
    n = len(tasks)
    if n == 0:
        return LearningCurve(category=category)

    # position -> list of outcomes (one per ordering) for banding.
    solved_at: list[list[float]] = [[] for _ in range(n)]
    cost_at: list[list[float]] = [[] for _ in range(n)]
    rng = random.Random(seed)

    for o in range(orderings):
        order = tasks[:]
        rng.shuffle(order)
        graph = graph_factory()  # accumulates across this ordering's sequence
        for position, task in enumerate(order):
            env = harness.start(task)
            outcome = run_engagement(cfg, graph, env, embedder, llm=llm)
            solved_at[position].append(1.0 if outcome.solved else 0.0)
            cost_at[position].append(outcome.cost)
            harness.teardown(env)
            if snapshot_dir:
                d = Path(snapshot_dir)
                d.mkdir(parents=True, exist_ok=True)
                save_procedural(graph, d / f"order{o}_pos{position}.json")

    return LearningCurve(
        solve_band=[MetricBand.of(xs) for xs in solved_at],
        cost_band=[MetricBand.of(xs) for xs in cost_at],
        category=category,
    )

"""Experiment A — architecture ablation (SEGMENT 13).

Does structure help *per task*? The backbone model is held fixed and the procedural graph is
frozen at a checkpoint, so every task is scored independently with NO learning carried between
tasks. Each task starts from the same frozen snapshot (a fresh deep copy), so writeback within
a task cannot confound the cross-task comparison.

Five settings, varying one factor at a time:

1. ``text_summary``    — rolling text-summary memory only (baseline)
2. ``vector_db``       — vector experience database (baseline)
3. ``static_kg``       — static knowledge graph, read-only (writeback OFF)
4. ``kg_writeback_bfs``— graph + writeback, breadth-first planning
5. ``full_axon``       — graph + writeback + informed search

Useful contrasts: 2->3 isolates structure, 3->4 isolates writeback, 4->5 isolates informed
search. Settings 1-2 are supplied via :mod:`axon.eval.baselines` so all memory variants share
the same persistence regime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..engagement.runner import run_engagement
from ..graph.persistence import deserialize_procedural, serialize_procedural
from ..graph.procedural import ProceduralGraph
from ..harness.base import BenchmarkHarness
from ..knowledge.embeddings import Embedder
from ..llm.client import LLMClient
from .metrics import SuiteReport, TaskRun, summarize

SETTINGS = ["text_summary", "vector_db", "static_kg", "kg_writeback_bfs", "full_axon"]

# A baseline builder runs one task and returns a TaskRun (for settings 1-2).
BaselineRunner = Callable[[dict, "object"], TaskRun]


def _frozen_copy(snapshot: dict) -> ProceduralGraph:
    """A fresh deep copy of the frozen graph so each task is scored on equal footing."""
    return deserialize_procedural(snapshot)


@dataclass
class AblationResult:
    reports: dict[str, SuiteReport]

    def contrast(self, a: str, b: str, field: str = "solve_rate") -> float:
        """Difference in a metric between two settings (b - a)."""
        return getattr(self.reports[b], field) - getattr(self.reports[a], field)


def run_experiment_a(
    cfg: dict,
    frozen_graph: ProceduralGraph,
    harness: BenchmarkHarness,
    embedder: Embedder,
    *,
    llm: Optional[LLMClient] = None,
    baselines: Optional[dict[str, BaselineRunner]] = None,
) -> AblationResult:
    snapshot = serialize_procedural(frozen_graph)  # the frozen checkpoint
    tasks = harness.load_tasks()
    baselines = baselines or {}
    reports: dict[str, SuiteReport] = {}

    for setting in SETTINGS:
        runs: list[TaskRun] = []
        for task in tasks:
            env = harness.start(task)
            if setting in ("text_summary", "vector_db"):
                runner = baselines.get(setting)
                if runner is None:
                    continue  # baseline not provided; skip (honest: reported n reflects this)
                runs.append(runner(cfg, env))
            else:
                graph = _frozen_copy(snapshot)
                outcome = run_engagement(
                    cfg, graph, env, embedder, llm=llm,
                    enable_writeback=(setting != "static_kg"),
                    planner_mode=("breadth" if setting == "kg_writeback_bfs" else "informed"),
                )
                runs.append(
                    TaskRun(
                        task_id=task.task_id, solved=outcome.solved, cost=outcome.cost,
                        milestones_reached=sum(
                            1 for t in outcome.state.trajectory if t["verified"]
                        ),
                        milestones_total=len(env.milestones) or 1,
                    )
                )
            harness.teardown(env)
        reports[setting] = summarize(setting, runs)

    return AblationResult(reports=reports)

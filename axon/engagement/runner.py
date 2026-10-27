"""Assemble and run one engagement from config + graph + a started task environment.

Shared by the CLI, the eval experiments, and the tests, so the wiring lives in one place.
"""

from __future__ import annotations

from typing import Optional

from ..execution.sandbox import Sandbox
from ..execution.tools import ToolRunner
from ..graph.procedural import ProceduralGraph
from ..harness.base import TaskEnvironment
from ..knowledge.embeddings import Embedder
from ..llm.client import LLMClient
from ..memory.read import MemoryReader
from ..memory.verify import VerificationGate
from ..memory.write import WritebackEngine
from ..planning.search import Planner
from .events import EventEmitter
from .loop import EngagementLoop, EngagementOutcome


def run_engagement(
    cfg: dict,
    graph: ProceduralGraph,
    env: TaskEnvironment,
    embedder: Embedder,
    *,
    llm: Optional[LLMClient] = None,
    emitter: Optional[EventEmitter] = None,
    enable_writeback: bool = True,
    planner_mode: str = "informed",
) -> EngagementOutcome:
    reader = MemoryReader(embedder, cfg)
    planner = Planner(cfg, mode=planner_mode)
    gate = VerificationGate(cfg, llm=llm)
    writeback = WritebackEngine(cfg, embedder=embedder, llm=llm)
    sandbox = Sandbox.from_config(cfg)
    runner = ToolRunner(
        sandbox, env.target,
        timeout_s=float(cfg.get("engagement", {}).get("per_action_timeout_s", 120)),
    )
    loop = EngagementLoop(
        graph, reader, planner, gate, writeback, runner,
        action_factory=env.action_factory,
        goal_check=env.goal_check,
        llm=llm,
        emitter=emitter,
        fold_max_chars=int(cfg.get("memory", {}).get("fold", {}).get("max_summary_chars", 800)),
        enable_writeback=enable_writeback,
    )
    state = env.new_state(cfg)
    return loop.run(state)

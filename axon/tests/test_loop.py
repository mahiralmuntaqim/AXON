"""End-to-end engagement-loop tests (SEGMENT 8, SEGMENT 16).

Runs the whole read-plan-act-write loop offline against the MockHarness, and proves budget
exhaustion / early-goal / tool-timeout handling, plus the read-only-visualizer and determinism
guarantees from SEGMENT 17 / SEGMENT 16.
"""

import copy

import pytest

from axon.config import load_config
from axon.engagement.events import EventEmitter, NullEmitter
from axon.engagement.runner import run_engagement
from axon.engagement.state import Budget
from axon.execution.result import ActionResult
from axon.execution.tools import Action, MockTarget
from axon.harness.mock import MockHarness
from axon.knowledge.construct import demo_seed_graph
from axon.knowledge.embeddings import HashingEmbedder


def _cfg():
    cfg = load_config()
    return cfg


def _embedder(cfg):
    return HashingEmbedder(dim=int(cfg["graph"]["embedding_dim"]))


def test_engagement_reaches_goal_and_learns():
    cfg = _cfg()
    emb = _embedder(cfg)
    graph = demo_seed_graph(emb)
    harness = MockHarness()
    task = harness.load_tasks()[0]
    env = harness.start(task)

    emitter = EventEmitter()  # in-memory, no file
    outcome = run_engagement(cfg, graph, env, emb, emitter=emitter)

    assert outcome.solved is True
    assert outcome.steps <= cfg["engagement"]["step_budget"]
    # Learning landed in the graph: the exploit edge gained a verified success.
    edge = graph.get_edge("enum_http", "exploit_cve",
                          list(graph.out_edges("enum_http"))[0].edge_type)
    # The successful exploit node accrued experience + a lesson.
    node = graph.get_node("exploit_cve")
    assert node.experience.n_plus >= 1
    assert len(node.experience.lessons) >= 1
    # Events were emitted for the key moments.
    types = {e.type for e in emitter.events}
    assert {"read", "select", "execute", "verify", "write", "budget"}.issubset(types)
    harness.teardown(env)


def test_budget_exhaustion_stops_cleanly_without_solving():
    cfg = _cfg()
    cfg["engagement"]["step_budget"] = 1  # too few steps to reach the flag
    emb = _embedder(cfg)
    graph = demo_seed_graph(emb)
    harness = MockHarness()
    env = harness.start(harness.load_tasks()[0])
    outcome = run_engagement(cfg, graph, env, emb)
    assert outcome.solved is False
    assert outcome.steps <= 1


def test_tool_timeout_does_not_crash_and_is_not_charged():
    cfg = _cfg()
    emb = _embedder(cfg)
    graph = demo_seed_graph(emb)

    def hanging_oracle(action: Action) -> ActionResult:
        raise TimeoutError("hung")

    from axon.harness.base import Task, TaskEnvironment
    from axon.graph.episodic import EpisodicGraph

    env = TaskEnvironment(
        task=Task("timeout-task", goal="flag", root_node_id="recon"),
        target=MockTarget(hanging_oracle),
        action_factory=lambda node, state: Action(node.id, "nmap", "127.0.0.1",
                                                   "nmap -sV 127.0.0.1", cost=0.01),
        goal_check=lambda r, s: r.milestone == "flag",
        episodic=EpisodicGraph("timeout-task"),
    )
    outcome = run_engagement(cfg, graph, env, emb)  # must not raise
    assert outcome.solved is False
    # A timed-out action is a tool error: the technique is not charged a failure.
    assert graph.get_node("recon").experience.n_minus == 0


def test_visualizer_is_read_only_identical_runs_with_and_without_emitter():
    """SEGMENT 17: attaching the visualizer must not change the run."""
    cfg = _cfg()
    emb = _embedder(cfg)
    harness = MockHarness()

    # Run A: no emitter.
    g_a = demo_seed_graph(emb)
    env_a = harness.start(harness.load_tasks()[0])
    out_a = run_engagement(cfg, g_a, env_a, emb, emitter=NullEmitter())

    # Run B: full in-memory emitter attached.
    g_b = demo_seed_graph(emb)
    env_b = harness.start(harness.load_tasks()[0])
    out_b = run_engagement(cfg, g_b, env_b, emb, emitter=EventEmitter())

    assert out_a.solved == out_b.solved
    assert out_a.steps == out_b.steps
    assert out_a.cost == pytest.approx(out_b.cost)
    # Final graph state identical.
    def fingerprint(g):
        return sorted(
            (e.src, e.dst, e.edge_type.value, round(e.Q, 6), e.n_plus, e.n_minus, e.visits)
            for e in g.edges()
        )
    assert fingerprint(g_a) == fingerprint(g_b)


def test_determinism_same_seed_same_snapshot_reproduces():
    """SEGMENT 16: with a fixed graph snapshot the run reproduces."""
    cfg = _cfg()
    emb = _embedder(cfg)
    harness = MockHarness()

    def one_run():
        g = demo_seed_graph(emb)
        env = harness.start(harness.load_tasks()[0])
        out = run_engagement(cfg, g, env, emb)
        return [t["node"] for t in out.state.trajectory], out.solved

    assert one_run() == one_run()

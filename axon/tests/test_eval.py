"""Evaluation tests (SEGMENT 13, SEGMENT 14): metrics, ablation, continual learning."""

import math

from axon.config import load_config
from axon.eval.baselines import make_hacksynth_runner, make_react_runner, make_vector_runner
from axon.eval.experiment_a import run_experiment_a
from axon.eval.experiment_b import run_experiment_b
from axon.eval.metrics import TaskRun, cost_per_solved, milestone_completion, solve_rate, success_at_k
from axon.harness.mock import MockHarness
from axon.knowledge.construct import demo_seed_graph
from axon.knowledge.embeddings import HashingEmbedder


def _emb():
    return HashingEmbedder(dim=128)


# -- metrics ----------------------------------------------------------------------------------
def test_metrics_basic():
    runs = [
        TaskRun("a", solved=True, cost=1.0, milestones_reached=2, milestones_total=2),
        TaskRun("b", solved=False, cost=2.0, milestones_reached=1, milestones_total=2),
    ]
    assert solve_rate(runs) == 0.5
    assert success_at_k(runs, 1) == 0.5
    assert milestone_completion(runs) == 0.75
    assert cost_per_solved(runs) == 3.0  # total cost / 1 solved


def test_cost_per_solved_is_inf_when_none_solved():
    runs = [TaskRun("a", solved=False, cost=1.0)]
    assert math.isinf(cost_per_solved(runs))


def test_success_at_k_counts_later_attempts():
    runs = [
        TaskRun("a", solved=False, cost=1.0, attempt_index=0),
        TaskRun("a", solved=True, cost=1.0, attempt_index=1),
    ]
    assert success_at_k(runs, 1) == 0.0
    assert success_at_k(runs, 2) == 1.0


# -- experiment A ----------------------------------------------------------------------------
def test_experiment_a_runs_all_five_settings():
    cfg = load_config()
    emb = _emb()
    frozen = demo_seed_graph(emb)
    pool = frozen.nodes()
    harness = MockHarness()
    baselines = {
        "text_summary": make_hacksynth_runner(pool),
        "vector_db": make_vector_runner(pool, emb),
    }
    result = run_experiment_a(cfg, frozen, harness, emb, baselines=baselines)
    assert set(result.reports) == {
        "text_summary", "vector_db", "static_kg", "kg_writeback_bfs", "full_axon"
    }
    # Full AXON should solve the mock task.
    assert result.reports["full_axon"].solve_rate == 1.0


def test_experiment_a_does_not_mutate_the_frozen_graph():
    cfg = load_config()
    emb = _emb()
    frozen = demo_seed_graph(emb)
    before = {n.id: n.experience.n_plus for n in frozen.nodes()}
    run_experiment_a(cfg, frozen, MockHarness(), emb)
    after = {n.id: n.experience.n_plus for n in frozen.nodes()}
    assert before == after  # each task ran on a fresh copy of the checkpoint


# -- experiment B ----------------------------------------------------------------------------
def test_experiment_b_produces_a_banded_curve():
    cfg = load_config()
    emb = _emb()
    harness = MockHarness()  # one task, so curve length 1
    curve = run_experiment_b(
        cfg, lambda: demo_seed_graph(emb), harness, emb, orderings=3, seed=0
    )
    assert len(curve.solve_band) == 1
    assert curve.solve_band[0].n == 3  # three orderings banded
    assert 0.0 <= curve.solve_band[0].mean <= 1.0

"""Benchmark adapter tests (SEGMENT 11, real task loading from committed indices)."""

import pytest

from axon.benchmark.base_loader import BenchmarkDataUnavailable
from axon.benchmark.registry import BENCHMARKS, get_harness
from axon.harness.base import Task

EXPECTED = {"nyuctf", "autopenbench", "cybench", "xbow"}


def test_registry_has_all_four():
    assert set(BENCHMARKS) == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_benchmark_loads_real_tasks(name):
    h = get_harness(name)
    tasks = h.load_tasks()
    assert tasks, f"{name} loaded no tasks"
    assert all(isinstance(t, Task) and t.task_id for t in tasks)
    # metadata records which benchmark each task came from.
    assert all(t.metadata.get("benchmark") == name for t in tasks)


def test_task_counts_match_indices():
    counts = {name: len(get_harness(name).load_tasks()) for name in EXPECTED}
    assert counts["xbow"] == 104
    assert counts["cybench"] == 43
    assert counts["nyuctf"] >= 200        # test split is 200; dev adds more
    assert counts["autopenbench"] >= 30


def test_xbow_tasks_seed_from_web_pack():
    tasks = get_harness("xbow").load_tasks()
    assert all(t.category == "web" for t in tasks)
    assert all(t.root_node_id == "web::triage" for t in tasks)


def test_ctf_categories_map_to_pack_triage_nodes():
    # A cybench crypto task should seed from the crypto pack triage node.
    tasks = get_harness("cybench").load_tasks()
    crypto = [t for t in tasks if t.category == "crypto"]
    assert crypto and all(t.root_node_id == "crypto::triage" for t in crypto)


def test_indices_carry_no_flags_or_solutions():
    # Contamination hygiene: metadata-only indices, no secret flags / solution prompts.
    import json
    from pathlib import Path

    idx_dir = Path(get_harness("xbow").index_path()).parent
    for f in idx_dir.glob("*.json"):
        blob = f.read_text(encoding="utf-8").lower()
        assert "easy_prompt" not in blob and "hard_prompt" not in blob
        assert "canary" not in blob


def test_start_is_a_labeled_stub():
    h = get_harness("nyuctf")
    task = h.load_tasks()[0]
    with pytest.raises(BenchmarkDataUnavailable):
        h.start(task)


def test_autopenbench_tasks_start_from_root():
    tasks = get_harness("autopenbench").load_tasks()
    assert all(t.root_node_id == "root" for t in tasks)


def test_nyuctf_challenge_detail_when_data_present():
    h = get_harness("nyuctf")
    if h.data_root() is None:
        pytest.skip("NYU data not located (set AXON_BENCH_ROOT)")
    task = h.load_tasks()[0]
    detail = h.challenge_detail(task)
    assert detail is not None
    assert "name" in detail and "description" in detail
    assert "_networked" in detail  # tells the runner whether to bring up docker-compose

"""AXON command-line interface.

Subcommands:
  construct      build a demo seed graph and save a snapshot
  run            run one mock engagement, writing an event log for the visualizer
  experiment-a   architecture ablation on the mock harness
  experiment-b   continual-learning curve on the mock harness
  viz            print how to view the visualizer for an event log

All commands are offline (mock LLM + mock target). Real LLM/target backends are wired per
deployment; see the module stubs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .engagement.events import EventEmitter
from .engagement.runner import run_engagement
from .eval.experiment_a import run_experiment_a
from .eval.experiment_b import run_experiment_b
from .graph.persistence import save_procedural
from .harness.mock import MockHarness
from .knowledge.construct import demo_seed_graph
from .knowledge.embeddings import HashingEmbedder


def _embedder(cfg: dict) -> HashingEmbedder:
    return HashingEmbedder(dim=int(cfg["graph"]["embedding_dim"]))


def cmd_construct(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    emb = _embedder(cfg)
    if args.demo:
        graph = demo_seed_graph(emb)
        src = "demo seed"
    else:
        from .knowledge.packs import DEFAULT_PACKS_DIR, build_procedural_graph

        packs_dir = args.packs or DEFAULT_PACKS_DIR
        result = build_procedural_graph(packs_dir, embedder=emb)
        graph = result.graph
        src = (f"knowledge packs ({result.n_categories} categories, {result.n_tools} tools; "
               f"{len(result.exclusions)} excluded)")
    save_procedural(graph, args.out)
    print(f"{src}: {len(graph)} nodes, {len(graph.edges())} edges -> {args.out}")


def cmd_run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    emb = _embedder(cfg)
    graph = demo_seed_graph(emb)
    harness = MockHarness()
    env = harness.start(harness.load_tasks()[0])
    emitter = EventEmitter(log_path=args.events)
    outcome = run_engagement(cfg, graph, env, emb, emitter=emitter)
    emitter.close()
    harness.teardown(env)
    print(json.dumps(
        {"solved": outcome.solved, "steps": outcome.steps, "cost": round(outcome.cost, 4),
         "events": args.events}, indent=2
    ))
    if args.snapshot:
        save_procedural(graph, args.snapshot)
        print(f"final graph snapshot -> {args.snapshot}")


def cmd_experiment_a(args: argparse.Namespace) -> None:
    from .eval.baselines import make_hacksynth_runner, make_vector_runner

    cfg = load_config(args.config)
    emb = _embedder(cfg)
    frozen = demo_seed_graph(emb)
    pool = frozen.nodes()
    baselines = {
        "text_summary": make_hacksynth_runner(pool),
        "vector_db": make_vector_runner(pool, emb),
    }
    result = run_experiment_a(cfg, frozen, MockHarness(), emb, baselines=baselines)
    for setting, rep in result.reports.items():
        print(f"{setting:18s} solve={rep.solve_rate:.2f} milestone={rep.milestone:.2f} "
              f"cost/solved={rep.cost_per_solved:.3f} n={rep.n_tasks}")


def cmd_experiment_b(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    emb = _embedder(cfg)
    curve = run_experiment_b(
        cfg, lambda: demo_seed_graph(emb), MockHarness(), emb,
        orderings=args.orderings, seed=cfg.get("llm", {}).get("seed", 0),
    )
    for i, band in enumerate(curve.solve_band):
        print(f"episodes_seen={i} solve_mean={band.mean:.2f} +/- {band.std:.2f} (n={band.n})")


def cmd_benchmarks(args: argparse.Namespace) -> None:
    from .benchmark.registry import BENCHMARKS, get_harness

    names = [args.name] if args.name else list(BENCHMARKS)
    for name in names:
        h = get_harness(name)
        try:
            tasks = h.load_tasks()
        except FileNotFoundError as exc:
            print(f"{name}: index missing — {exc}")
            continue
        root = h.data_root()
        cats = {}
        for t in tasks:
            cats[t.category] = cats.get(t.category, 0) + 1
        cat_str = ", ".join(f"{k}:{v}" for k, v in sorted(cats.items()))
        print(f"{name:13s} {len(tasks):4d} tasks | {h.contamination:10s} | "
              f"data: {'present' if root else 'not found (path-referenced)'}")
        print(f"              categories: {cat_str}")
        if args.list:
            for t in tasks[: args.limit]:
                print(f"                - {t.task_id}  [{t.category}]")


def cmd_benchmark_run(args: argparse.Namespace) -> None:
    """Run the engagement loop against a LIVE benchmark challenge (needs data + Docker)."""
    from .benchmark.registry import get_harness
    from .knowledge.packs import build_procedural_graph
    from .llm.client import LLMClient

    cfg = load_config(args.config)
    cfg.setdefault("llm", {})
    cfg["llm"]["provider"] = args.provider
    cfg["llm"]["model"] = args.model
    cfg.setdefault("engagement", {})["step_budget"] = args.steps
    # A benchmark container is disposable (compose down -v fully resets it), so actions are
    # effectively reversible — relax the irreversibility floor for the run.
    cfg.setdefault("safety", {})["q_min"] = args.q_min

    emb = _embedder(cfg)
    # Persistent G_K: load the accumulating snapshot if it exists, else seed from the packs.
    # Saved back after the run so learning carries across engagements (the whole point).
    from pathlib import Path as _Path

    from .graph.persistence import load_procedural, save_procedural

    if args.graph and _Path(args.graph).is_file():
        graph = load_procedural(args.graph)
        print(f"loaded persistent G_K from {args.graph} ({len(graph)} nodes)")
    else:
        graph = build_procedural_graph(embedder=emb).graph
        print(f"seeded G_K from knowledge packs ({len(graph)} nodes)")
    llm = LLMClient.from_config(cfg["llm"])

    h = get_harness(args.name)
    if not hasattr(h, "prepare"):
        raise SystemExit(f"{args.name} has no live runner yet (only xbow is wired)")
    h.prepare(cfg, llm)
    task = next((t for t in h.load_tasks() if t.task_id == args.task), None)
    if task is None:
        raise SystemExit(f"task {args.task!r} not found in {args.name}")

    print(f"starting {args.name}/{task.task_id} with {args.provider}:{args.model} ...")
    env = h.start(task)
    try:
        outcome = run_engagement(cfg, graph, env, emb, llm=llm,
                                 emitter=EventEmitter(log_path=args.events))
    finally:
        h.teardown(env)
    if args.graph:
        save_procedural(graph, args.graph)  # persist accumulated learning
    print(json.dumps(
        {"task": task.task_id, "solved": outcome.solved, "steps": outcome.steps,
         "cost_units": round(outcome.cost, 4), "events": args.events,
         "graph": args.graph, "nodes": len(graph)}, indent=2
    ))


def cmd_viz(args: argparse.Namespace) -> None:
    index = Path(__file__).resolve().parent.parent / "viz" / "index.html"
    print(f"Open the visualizer: {index}")
    print(f"Load the event log in Replay mode: {args.events}")
    print("Or serve live: python -m viz.serve --events " + args.events)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="axon", description="AXON CLI (offline/mock by default)")
    p.add_argument("--config", default=None, help="path to a YAML config")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("construct", help="build G_K from the knowledge packs (or --demo)")
    c.add_argument("--out", default="seed_graph.json")
    c.add_argument("--packs", default=None, help="path to knowledge_packs/packs (default: bundled)")
    c.add_argument("--demo", action="store_true", help="build the tiny demo graph instead")
    c.set_defaults(func=cmd_construct)

    r = sub.add_parser("run", help="run one mock engagement")
    r.add_argument("--events", default="events.jsonl")
    r.add_argument("--snapshot", default=None)
    r.set_defaults(func=cmd_run)

    a = sub.add_parser("experiment-a", help="architecture ablation")
    a.set_defaults(func=cmd_experiment_a)

    b = sub.add_parser("experiment-b", help="continual-learning curve")
    b.add_argument("--orderings", type=int, default=5)
    b.set_defaults(func=cmd_experiment_b)

    bm = sub.add_parser("benchmarks", help="list loaded benchmark tasks (nyuctf/autopenbench/cybench/xbow)")
    bm.add_argument("--name", default=None, help="a single benchmark; default lists all")
    bm.add_argument("--list", action="store_true", help="also print individual task ids")
    bm.add_argument("--limit", type=int, default=20)
    bm.set_defaults(func=cmd_benchmarks)

    br = sub.add_parser("benchmark-run", help="run the loop against a LIVE challenge (needs Docker)")
    br.add_argument("--name", default="xbow")
    br.add_argument("--task", required=True, help="challenge id, e.g. XBEN-001-24")
    br.add_argument("--provider", default="nvidia")
    br.add_argument("--model", default="nvidia/llama-3.1-nemotron-70b-instruct")
    br.add_argument("--steps", type=int, default=12)
    br.add_argument("--q-min", dest="q_min", type=float, default=0.0)
    br.add_argument("--graph", default="axon_kg.json",
                    help="persistent G_K snapshot: loaded if present, saved after (learning accumulates)")
    br.add_argument("--events", default="bench_events.jsonl")
    br.set_defaults(func=cmd_benchmark_run)

    v = sub.add_parser("viz", help="how to view the visualizer")
    v.add_argument("--events", default="events.jsonl")
    v.set_defaults(func=cmd_viz)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

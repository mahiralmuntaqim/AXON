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

    v = sub.add_parser("viz", help="how to view the visualizer")
    v.add_argument("--events", default="events.jsonl")
    v.set_defaults(func=cmd_viz)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

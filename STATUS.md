# AXON — Status & final check (SEGMENT 18)

Last run: full suite **72 passed**, offline. CLI `construct`/`run`/`experiment-a`/`experiment-b`
all execute end to end on the mock harness.

**Knowledge content (SEGMENT 2/3):** `knowledge_packs/` (6 CTF categories, 111 curated tools)
is wired in via `axon/knowledge/packs.py`. `axon.cli construct` builds a real G_K from it —
**117 nodes, 1542 edges, 0 firewall exclusions** — and tool metadata (install/usage/docs/
category) rides along in `TechniqueNode.metadata`. Both construction routes are covered: the
deterministic pack loader and the `SourceDoc` adapter for the LLM `GraphConstructor`.

## SEGMENT 0 hard rules — verification

| # | Rule | Holds? | Where |
|---|------|--------|-------|
| 1 | Model stays frozen; no training code | ✅ | `grep` for train/gradient/optimizer/requires_grad returns nothing. Only inference wrappers in `llm/client.py`. |
| 2 | All learning is a graph edit | ✅ | `memory/write.py` edits counts, Q, lessons, nodes/edges only. Nothing else mutates learning state. |
| 3 | Two graphs stay separate; no target secrets in G_K | ✅ | Distinct classes (`TechniqueNode` vs `EpisodicFact`); containers reject the wrong class; separate serializers in `persistence.py`. Tests in `test_schema.py`. |
| 4 | Nothing enters G_K without the gate | ✅ | `engagement/loop.py` writes only when `verification.verified`; `write.py` re-asserts it. Tests in `test_memory.py`. |
| 5 | No environment-reset search / no simulated rollouts | ✅ | `planning/search.py` is a single-trajectory PUCT selection rule (documented); loop takes one real action per step. |
| 6 | Every module unit-testable alone | ✅ | 66 tests, LLM + target mocked, fully offline. |
| 7 | Stubs clearly labeled | ✅ | All marked `STUB:` (list below). |
| + | Visualizer is read-only | ✅ | `test_loop.py::test_visualizer_is_read_only_*` proves identical runs with/without the emitter. |

## What has actually run end to end

- Schema, two graphs, persistence round-trip.
- Memory: hybrid retrieval (dense + PPR), context folding, verification gate, error attribution,
  Beta writeback, lesson distillation, structural growth.
- Planning: PUCT selection, irreversibility safety gate, backtracking, visit backup.
- Full engagement loop (Algorithm 1) solving the **mock** task; budget/timeout/LLM-failure
  handling; determinism and read-only-visualizer guarantees.
- Decontamination: provenance firewall excludes a seeded CSAW doc; web search off by default;
  sandbox blocks disallowed hosts/tools.
- Eval: metrics (success@k, milestone, $/solved), Experiment A (5 settings), Experiment B
  (banded learning curve), baselines (ReAct, HackSynth, vector-experience).
- Visualizer: event log emitted; `viz/index.html` replay + live; `viz/serve.py` SSE server.

## Stubs / placeholders (NOT yet real)

These are intentionally unimplemented and labeled `STUB:` in code. Per SEGMENT 18, **no real
benchmark is claimed to work** — only the mock harness has run a task end to end.

- `llm/client.py::FrozenRemoteLLM` — wire to a real inference-only endpoint (no training).
- `knowledge/embeddings.py::SentenceTransformerEmbedder` — real semantic embedder.
  (`HashingEmbedder` is real and used offline, but is not semantically strong.)
- `execution/tools.py::SubprocessBackend` — real execution of allowlisted tools in a sandboxed
  container. Must only run after `Sandbox.validate`; invokes known tools only, no payload
  generation.
- `harness/stubs.py` — Vulhub, AutoPenBench, XBOW/XBEN, Cybench, NYU CTF adapters. **None have
  run a real task.**
- `eval/baselines.py::PentestR1Baseline` and a CRAKEN static-RAG wiring helper.
- `memory/read.py::fold_result` — head/tail folder; a real deployment can route folding
  through the LLM (contract unchanged: raw logs never reach working context).

## Honesty note on contamination (SEGMENT 12)

The provenance firewall controls what enters the **graph**, not the frozen model's own
pretraining memory of these sources. XBOW's injected random flags therefore remain the cleanest
contamination-minimized measure, and results code/report should say so.

## The graph is a pluggable interface

`graph/schema.py::GraphBackend` + `knowledge/construct.py::GraphConstructor` let a user-supplied
graph slot in without a rewrite. Construction is "an interface you fill"; `demo_seed_graph`
is the built-in example used by the mock harness and tests.

# AXON — Architecture

AXON is an autonomous penetration-testing **research agent** that learns without ever
changing model weights. The language model is **frozen**. Every improvement the agent makes
is an edit to an external **attack knowledge graph**, never to the model.

AXON is scoped to **authorized sandboxes only** (Vulhub containers, CTF/XBOW challenge
containers). It does **not** generate novel exploit code — it composes publicly documented
techniques by calling known tools inside an allowlist. See `axon/execution/` and
`SEGMENT 10`/`SEGMENT 12` for the ethics/decontamination posture.

## The seven hard rules (SEGMENT 0)

1. **The LLM is frozen.** No training, fine-tuning, gradient updates, or reward models
   anywhere in the codebase. A task that seems to need weight updates is flagged, not coded.
2. **All learning is a graph edit.** Success/failure counts, lessons, new nodes and edges all
   live in the graph.
3. **Two graphs, kept separate.** The *procedural* graph (`G_K`, "what is possible", shared
   across targets, persistent) and the *episodic* graph (`G_E`, facts about the current
   target, destroyed after each engagement). Target secrets never enter `G_K`.
4. **Nothing enters `G_K` without the verification gate passing first.** Hallucinated results
   and tool errors must never poison the graph.
5. **The target is live.** No tree search that assumes the environment can be rewound. No
   simulated rollouts inside one engagement. A single real trajectory per engagement.
6. **Every module is unit-testable on its own**, without a real target (LLM and target mocked).
7. **Honesty in comments/docstrings.** Stubs are labeled `STUB:` clearly.

Plus (SEGMENT 17): **the visualizer is read-only.** It consumes an event stream and never
writes to either graph or changes any decision. Removing it must change no result of a run.

## Module map

```
axon/
  config/default.yaml      # all tunable numbers (alpha/beta, c_puct, q_min, caps, budgets)
  graph/
    schema.py              # node/edge types, records, validation  (SEGMENT 2) — FOUNDATION
    procedural.py          # G_K: persistent "what is possible"     (SEGMENT 2)
    episodic.py            # G_E: per-target verified facts          (SEGMENT 2)
    matching.py            # link episodic facts -> G_K preconditions(SEGMENT 4)
    persistence.py         # snapshot save/load, separate per graph  (SEGMENT 2)
  knowledge/
    construct.py           # seed G_K from MITRE/HackTricks (pluggable) (SEGMENT 3)
    provenance.py          # provenance firewall: keep eval leaks out (SEGMENT 3/12)
  memory/
    read.py                # dense + PPR retrieval, context folding   (SEGMENT 4)
    verify.py              # verification gate + error attribution     (SEGMENT 5)
    write.py               # verification-gated writeback (3 writes)    (SEGMENT 5)
    lessons.py             # lesson distillation                        (SEGMENT 5)
  planning/
    search.py              # PUCT best-first / bandit selection         (SEGMENT 6)
    reversibility.py       # reversibility tags + irreversible gate     (SEGMENT 7)
  llm/
    client.py              # frozen-model wrapper (one call site)       (SEGMENT 9)
    prompts.py             # all prompt templates                       (SEGMENT 9)
  execution/
    tools.py               # sandbox-allowlisted tool runner (STUB)     (SEGMENT 10)
    sandbox.py             # allowlist enforcement                       (SEGMENT 10)
  harness/                 # one adapter per benchmark, common interface (SEGMENT 11)
    base.py autopenbench.py cybench.py nyuctf.py xbow.py vulhub.py
  engagement/
    loop.py                # the read-plan-act-write loop (Algorithm 1) (SEGMENT 8)
    state.py               # engagement state + budget/cost tracking    (SEGMENT 8)
    events.py              # read-only event emitter for the visualizer (SEGMENT 17)
  eval/
    experiment_a.py        # architecture ablation                      (SEGMENT 13)
    experiment_b.py        # continual-learning curve                   (SEGMENT 13)
    metrics.py             # success@k, milestone, $ / solved task       (SEGMENT 14)
  cli.py
  tests/
viz/                       # self-contained read-only web visualizer    (SEGMENT 17)
```

## Data flow (one engagement — Algorithm 1)

```
load G_K (persistent)  ──┐
fresh G_E  ──────────────┤
                         ▼
  ┌───────────────────── loop while steps < budget and goal not met ─────────────────────┐
  │ READ:   matching(G_E -> G_K preconds) -> read.retrieve (dense + PPR) -> fold context  │
  │ PRUNE:  llm prunes out-edges of current node within retrieved subgraph                │
  │ SELECT: planning.search picks edge by PUCT: Q + c_puct*P*sqrt(N)/(1+N(a))             │
  │ GATE:   if best is irreversible and Q < q_min -> reversible sibling / backtrack       │
  │ EXECUTE:execution.tools runs the action in the sandbox; capture trace, timeout        │
  │ VERIFY: verify.gate checks real state transition + error attribution                  │
  │ UPDATE G_E: add verified facts                                                        │
  │ WRITE G_K (only if gate passed): Beta edge update, lesson, structural growth          │
  │ BACKUP: back up verified outcome along traversed path; move on or backtrack           │
  │ (emit read/prune/select/execute/verify/write/backup/backtrack/budget events)          │
  └───────────────────────────────────────────────────────────────────────────────────┘
return trajectory + updated G_K
```

## Key design decisions

- **Bayesian edge values.** `Q = (n_plus + alpha) / (n_plus + n_minus + alpha + beta)`. One
  fluke only nudges `Q`; it cannot wipe out a long-successful path (self-poisoning guard #1).
- **Promotion requires a verified state transition** after error attribution (guard #2).
- **PUCT is a best-first/bandit selection rule**, not MCTS. Each expansion is one real action;
  the trajectory within an engagement is a single line. Learning accumulates *between*
  engagements through the per-edge Beta posteriors.
- **Graph construction is an interface** (`knowledge/construct.py` + a `GraphBackend`
  protocol in `graph/schema.py`) so a user-supplied graph plugs in without a rewrite.

## Status / stubs

See [STATUS.md](STATUS.md) for the SEGMENT 18 final-check table and the full stub list. In
short: the whole pipeline runs end to end offline (66 tests pass; CLI solves the mock task),
while real LLM/embedder/tool backends and the five benchmark adapters are labeled `STUB:` and
have **not** run a real task yet.

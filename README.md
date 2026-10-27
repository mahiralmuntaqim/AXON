<div align="center">

# AXON

**An autonomous penetration-testing agent that learns without touching its model weights.**

The language model stays **frozen**. Every lesson AXON learns is written to an external
**attack knowledge graph** — not back into the model. Learning is a graph edit, forever.

`frozen LLM` · `self-editing knowledge graph` · `verification-gated learning` · `authorized sandboxes only`

</div>

---

## Table of contents

- [The idea in one minute](#the-idea-in-one-minute)
- [Why do it this way](#why-do-it-this-way)
- [Safety & ethics](#safety--ethics)
- [How it works](#how-it-works)
  - [The two graphs](#the-two-graphs)
  - [The engagement loop (Algorithm 1)](#the-engagement-loop-algorithm-1)
  - [How learning lands in the graph](#how-learning-lands-in-the-graph)
  - [How AXON plans](#how-axon-plans)
- [Knowledge packs](#knowledge-packs)
- [Quickstart](#quickstart)
- [Watch it think — the visualizer](#watch-it-think--the-visualizer)
- [Evaluation](#evaluation)
- [Project layout](#project-layout)
- [What is real vs. stubbed](#what-is-real-vs-stubbed)
- [The seven hard rules](#the-seven-hard-rules)
- [Extending AXON](#extending-axon)
- [Disclaimer](#disclaimer)

---

## The idea in one minute

Most agents that "get better" do so by changing model weights — a training run, a fine-tune, a
reward model. AXON doesn't. The model is a frozen reasoning engine; all of AXON's accumulated
skill lives in a graph it reads from and writes to as it works.

- **Procedural graph (`G_K`)** — *"what is possible."* Techniques (nodes) connected by
  relationships (edges). Shared across every target, persists forever. Each edge carries a
  **learned value `Q`** (how well it has worked) and an **LLM prior `P`** (how applicable the
  model thought it was). Each node carries an **experience record**: success/failure counts and
  context-keyed **lessons**.
- **Episodic graph (`G_E`)** — *"what is true about this target right now."* Hosts, open
  services, credentials, footholds. Built fresh per engagement, thrown away at the end. Target
  secrets never leak into `G_K`.

Each step, AXON **reads** a small relevant slice of `G_K` (guided by what it has learned about
the live target in `G_E`), **plans** the next technique, **acts** against the target, **verifies**
the outcome, and **writes** what it learned back into `G_K` — but only if a verification gate
confirms the outcome was real. Over many engagements, the edge values aggregate experience
across similar targets, and the agent gets measurably better **with the same frozen model.**

## Why do it this way

- **Economic.** Learning that is a graph edit avoids a training run entirely. The headline
  metric is *dollars per solved task*, not GPU-hours.
- **Model-agnostic.** Every model call goes through one wrapper. Swap the backend and nothing
  else changes — the intelligence that accrues is in the graph, not the weights.
- **Auditable & safe.** Because learning is explicit graph mutation behind a verification gate,
  you can see exactly what was learned, prove what was excluded, and guarantee a hallucinated
  result never poisons the store.
- **Transferable.** A Beta-posterior on each edge aggregates outcomes over many
  similarly-fingerprinted targets, so knowledge earned on one box helps on the next.

## Safety & ethics

AXON is built for **authorized security research, CTF, and education only.**

- **Sandbox allowlist.** Every action is checked *before* it runs. Only allowlisted hosts
  (loopback / private lab ranges) and allowlisted, publicly-documented tools are permitted —
  nothing live, nothing third-party. A violation means the action never executes.
- **No exploit generation.** AXON *composes* known, documented techniques by invoking known
  tools. It does not synthesize novel exploit payloads.
- **Irreversibility gating.** Every technique is tagged reversible or irreversible. An
  irreversible action only fires when its learned confidence `Q` clears a floor **and** budget
  allows; otherwise AXON prefers a reversible sibling or backtracks.
- **Decontamination.** A provenance firewall excludes any source tied to an evaluation
  benchmark at graph-construction time (mirroring CRAKEN's policy) and logs every exclusion;
  web search is hard-disabled during evaluation. Honest caveat: the firewall controls the
  *graph*, not the frozen model's own pretraining memory — so contamination-minimized boards
  (e.g. XBOW's injected random flags) remain the cleanest signal.

## How it works

### The two graphs

| | Procedural `G_K` | Episodic `G_E` |
|---|---|---|
| Holds | techniques + relationships | verified facts about the current target |
| Node types | `RECON` `ENUM` `EXPLOIT` `PRIVESC` `LATERAL` `EXFIL` | `HOST` `SERVICE` `CREDENTIAL` `FOOTHOLD` |
| Edge types | `PRECONDITION` `ENABLES` `ALTERNATIVE` `REFINES` | typed relations (host → runs → service) |
| Lifetime | **persists forever**, shared across targets | **fresh per engagement, destroyed after** |
| Carries learning | `Q` (learned), `P` (prior), counts, lessons | nothing learned — just observed facts |

They are **different Python classes**, their containers reject the wrong type, and they have
**separate serializers** — so an episodic secret can never be written into a procedural
snapshot, by construction.

### The engagement loop (Algorithm 1)

```
load G_K (persistent)  ─┐
fresh  G_E             ─┤
                        ▼
  ┌───── while steps < budget and goal not met ──────────────────────────────────┐
  │ READ     match G_E → G_K preconditions; dense + PPR retrieval; fold context   │
  │ PRUNE    the LLM drops clearly-irrelevant out-edges (keeps the search small)  │
  │ SELECT   PUCT picks the best edge:  Q + c·P·√N / (1 + N(a))                    │
  │ GATE     if best is irreversible and Q < q_min → reversible sibling/backtrack │
  │ EXECUTE  run the action in the sandbox; capture the trace; enforce a timeout  │
  │ VERIFY   real state transition?  +  tool-error vs. genuine-failure attribution│
  │ UPDATE   add newly-verified facts to G_E                                      │
  │ WRITE    (only if the gate passed) Beta edge update · lesson · graph growth   │
  │ BACKUP   back the outcome up the path; advance, or backtrack to a frontier    │
  │ (emit read/prune/select/execute/verify/write/backup/backtrack/budget events)  │
  └───────────────────────────────────────────────────────────────────────────────┘
return the trajectory + the updated G_K
```

The trajectory within one engagement is a **single real line** — there is no environment reset
and no simulated rollout, because a live target cannot be rewound. Learning accumulates
*between* engagements through the edge values.

### How learning lands in the graph

Nothing reaches `G_K` until the **verification gate** passes. The gate asks two questions of the
execution trace:

1. **Is the outcome real?** A claimed success must be backed by an observable state transition
   — a new shell, an HTTP 200 after a 403, a harness-reported flag. A claimed flag with no
   trace behind it is treated as *not verified* and written nowhere durable.
2. **Who is to blame for a failure?** A tool/syntax error (a typo, a missing binary, a timeout)
   is **not** charged against the technique. Only a genuine failure of the technique's
   hypothesis counts.

When (and only when) the gate passes, three writes happen — none of which touch the model:

1. **Edge value update** — a Bayesian Beta posterior
   `Q = (n⁺ + α) / (n⁺ + n⁻ + α + β)`. Because it's Bayesian, one fluke only nudges a
   long-successful edge; it can't wipe out a good path.
2. **Lesson distillation** — one short, reusable lesson ("why it worked / failed"), keyed by a
   structured context signature (service, version, defense). Distilled from failures too.
3. **Structural growth** — a genuinely new technique/edge, promoted from episodic discovery to
   `G_K` **only** when a verified state transition backs it.

### How AXON plans

Selection is a budgeted **PUCT** rule that blends the learned value with the model's prior:

```
score(a) = Q(a) + c_puct · P(a) · √N / (1 + N(a))
```

This is a **best-first / bandit selection rule, not Monte-Carlo tree search.** There are no
environment resets and no imagined futures — each expansion is one real action. The LLM prunes
candidates first so the search stays small; the surviving edges are scored and the best *safe*
one is chosen. When a branch's value falls too low, AXON abandons that hypothesis and jumps to
the best open frontier node (backtracking means changing hypothesis, never undoing the
environment).

## Knowledge packs

The procedural graph is seeded from real curated content in [`knowledge_packs/`](knowledge_packs/)
— six CTF/pentest categories, **111 tools** with install/usage/docs, plus per-category triage
playbooks and reference lists.

| Pack | Category |
|---|---|
| `crypto` | break/exploit a cipher to recover a secret |
| `pwn` | binary exploitation — abuse a memory bug to take control |
| `rev` | reverse engineering — read compiled logic for the answer |
| `web` | web exploitation — attack a site through its flaws |
| `forensics` | investigate files/dumps to recover hidden info |
| `misc` | jails, encoding, PPC, OSINT |

[`axon/knowledge/packs.py`](axon/knowledge/packs.py) turns packs into `G_K` two ways:

- `build_procedural_graph(...)` — deterministic, offline, no LLM. Maps each tool's role onto one
  of the six technique types and wires category subgraphs along the tactic order. Produces a
  **117-node, 1542-edge** graph; each node keeps its tool's install/usage/docs and source
  category in `TechniqueNode.metadata`.
- `to_source_docs(...)` — packages each pack as a `SourceDoc` for the LLM-based
  `GraphConstructor` when a real model is wired in.

Construction is deliberately an *interface you fill* — bring your own graph and the rest of the
system runs unchanged.

## Quickstart

Requires **Python 3.11+**.

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate on POSIX
pip install -r requirements.txt

pytest axon/tests                 # 72 tests, fully offline (LLM + target are mocked)
```

Run everything offline (mock model + mock target):

```bash
# Build the procedural graph from the knowledge packs (117 nodes / 1542 edges)
python -m axon.cli construct --out seed_graph.json
python -m axon.cli construct --demo --out seed.json      # or the tiny demo graph

# Run one engagement; writes an event log for the visualizer
python -m axon.cli run --events events.jsonl --snapshot final_graph.json

# The two experiments
python -m axon.cli experiment-a                          # architecture ablation (5 settings)
python -m axon.cli experiment-b                           # continual-learning curve
```

## Watch it think — the visualizer

The engagement loop emits a JSON-lines event stream. The visualizer in [`viz/`](viz/) **only
consumes it** — it never writes to either graph and never changes a decision (a test proves a
run is byte-identical with and without it attached).

- **Replay:** open `viz/index.html` in a browser and load your `events.jsonl`. Scrub, play,
  step, change speed.
- **Live:** `python -m viz.serve --events events.jsonl`, then click *Connect live*.

Nodes are colored by their six types; edge thickness/brightness tracks the learned value `Q`
(with the prior `P` as a faint underlay, so you watch learning pull away from the prior); 🔒
marks irreversible, safety-gated techniques; a green dot marks a node that has accrued lessons.

## Evaluation

Two experiments, kept strictly separate:

- **Experiment A — architecture ablation.** The graph is frozen at a checkpoint so every task is
  scored independently. Five settings isolate one factor at a time: text-summary memory →
  vector DB → static graph → graph + writeback (breadth-first) → **full AXON** (graph +
  writeback + informed search).
- **Experiment B — continual learning.** The graph accumulates across a sequence of tasks;
  solve rate and cost are plotted against episodes-seen, averaged over random orderings and
  reported as a band so a few lucky early solves can't masquerade as learning.

Metrics (computed the same way across suites): `success@k` and solve rate, subtask/milestone
completion (partial credit for long-horizon progress), and **dollars per solved task**.
Baselines behind the same interface: frozen ReAct, HackSynth (rolling-summary memory), and a
vector-experience agent.

Benchmark adapters (`Vulhub`, `AutoPenBench`, `XBOW/XBEN`, `Cybench`, `NYU CTF`) sit behind one
common interface. **They are labeled stubs** — see below.

## Project layout

```
axon/
  graph/        schema · procedural (G_K) · episodic (G_E) · matching · persistence
  knowledge/    construct · provenance firewall · embeddings · packs loader
  memory/       read (dense + PPR + folding) · verify (the gate) · write · lessons
  planning/     search (PUCT) · reversibility (the safety gate)
  llm/          frozen client (one call site) · prompt templates
  execution/    sandbox allowlist · tool runner · result types
  harness/      common benchmark interface · mock harness · benchmark stubs
  engagement/   the loop (Algorithm 1) · state/budget · events · replay · runner
  eval/         metrics · experiment_a · experiment_b · baselines
  cli.py        construct / run / experiment-a / experiment-b / viz
  tests/        72 offline tests
knowledge_packs/  six CTF/pentest packs (111 tools) — the graph's source content
viz/              self-contained read-only visualizer (replay + live)
ARCHITECTURE.md · STATUS.md
```

## What is real vs. stubbed

Everything above runs end to end **offline** — 72 tests pass, and the CLI solves the mock task,
builds the real graph, and runs both experiments. The following are intentional, clearly-labeled
stubs (see [STATUS.md](STATUS.md) for the full list); per the project's own rules, **no real
benchmark is claimed to work until it has run a task end to end:**

- the real inference endpoint (`FrozenRemoteLLM`) and a real semantic embedder
  (`SentenceTransformerEmbedder`) — the offline `HashingEmbedder` is real but lexical, not
  semantic;
- the real tool-execution backend (`SubprocessBackend`) that invokes allowlisted tools in a
  sandboxed container;
- the five benchmark adapters and the Pentest-R1 / CRAKEN baselines.

## The seven hard rules

Enforced in code and tests, not just prose (verification table in [STATUS.md](STATUS.md)):

1. The model stays **frozen** — no training/fine-tuning/gradient code anywhere.
2. **All learning is a graph edit.**
3. The two graphs stay **separate** — no target secrets in `G_K`.
4. **Nothing enters `G_K` without the verification gate.**
5. **No environment-reset search**, no simulated rollouts inside an engagement.
6. Every module is **unit-testable on its own** (model + target mocked).
7. Stubs are **clearly labeled** as stubs.

Plus: the **visualizer is read-only** — removing it changes no result of a run.

## Extending AXON

- **Your own graph:** implement the `GraphBackend` protocol in `axon/graph/schema.py`;
  construction in `axon/knowledge/construct.py` is an interface to fill.
- **Your own model:** point the one wrapper in `axon/llm/client.py` at an inference endpoint.
  Nothing else changes.
- **Your own embedder / tools / benchmark:** swap the embedder, implement `SubprocessBackend`,
  or add a harness adapter behind the common interface.

## Disclaimer

AXON is a research framework for **authorized** security testing, CTF, and education. Only run it
against systems you own or are explicitly permitted to test. The execution layer enforces a
sandbox allowlist and composes documented tools only — do not repurpose it to target systems you
are not authorized to assess.

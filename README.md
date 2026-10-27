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

pytest axon/tests                 # 96 tests, fully offline (LLM + target are mocked)
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

### Benchmarks

Four external benchmarks are wired in under [`axon/benchmark/`](axon/benchmark/), behind the
common harness interface:

| Benchmark | Tasks | Role | Contamination |
|---|---:|---|---|
| **NYU CTF Bench** | 257 | SOTA comparison (CRAKEN, D-CIPHER) | HIGH |
| **AutoPenBench** | 33 | milestone / partial-credit; vs. Pentest-R1 | moderate |
| **Cybench** | 43 | SOTA comparison, subtask scoring | HIGH |
| **XBOW / XBEN** | 104 | low-contamination (injected random flags) — cleanest signal | LOW |

#### How the benchmarks are stored

The benchmark repos are multi-gigabyte (Docker challenge environments, binaries, datasets —
~5.4 GB in total), so they are **not committed to this repo**. Instead AXON keeps only a small,
committed **task index per benchmark** in [`axon/benchmark/indices/`](axon/benchmark/indices/):

- Indices are **metadata only** — task ids, categories, difficulty, tags. They contain **no
  flags and no solution prompts**, so no benchmark solution is ever committed (contamination
  hygiene, per the decontamination section). Total size ≈ 100 KB.
- The heavy challenge data stays wherever you cloned/built it and is located at **runtime** by
  [`axon/benchmark/paths.py`](axon/benchmark/paths.py).

```
axon/benchmark/
  indices/          committed, metadata-only task lists (nyuctf/autopenbench/cybench/xbow .json)
  paths.py          locates the heavy data repos at runtime (env var or default path)
  build_indices.py  regenerates the indices from the source repos
  base_loader.py    shared adapter: load_tasks() from an index -> harness Tasks
  nyuctf.py  autopenbench.py  cybench.py  xbow.py   per-benchmark adapters
  registry.py       name -> adapter
```

#### 1. Point AXON at the benchmark data

Resolution order, per benchmark (first hit wins); if none exists the data is simply "not found"
and only `start()` is affected — `load_tasks()` still works from the committed index:

1. `AXON_BENCH_<NAME>` — full path to one benchmark repo, e.g. `AXON_BENCH_XBOW=/data/xbow`
2. `AXON_BENCH_ROOT` — a parent folder that contains all of them (`NYU_CTF_Bench/`,
   `auto-pen-bench/`, `cybench/`, `xbow/`)
3. the built-in default root in `paths.py`

```bash
# POSIX
export AXON_BENCH_ROOT=/path/to/benchmarks
# Windows (PowerShell)
$env:AXON_BENCH_ROOT = "C:\path\to\benchmarks"
```

Folder names expected under the root: `NYU_CTF_Bench`, `auto-pen-bench`, `cybench`, `xbow`.

#### 2. (Re)build the task indices

The indices are already committed. Regenerate them whenever the source benchmarks change (needs
the data present); benchmarks whose data isn't found are skipped, not errored:

```bash
python -m axon.benchmark.build_indices
```

#### 3. Inspect from the CLI

```bash
python -m axon.cli benchmarks                      # counts + categories for all four
python -m axon.cli benchmarks --name xbow --list   # list individual task ids
```

```
nyuctf         257 tasks | HIGH risk  | data: present
              categories: crypto:63, forensics:25, misc:30, pwn:49, rev:61, web:29
xbow           104 tasks | LOW        | data: present
              categories: web:104
```

#### 4. Use from Python

```python
from axon.benchmark import get_harness

h = get_harness("xbow")          # or "nyuctf" | "autopenbench" | "cybench"
tasks = h.load_tasks()           # real Task list from the committed index (works offline)
print(len(tasks), tasks[0].task_id, tasks[0].category, tasks[0].metadata)

h.data_root()                    # Path to the full challenge data, or None if not located
# h.start(task)                  # STUB: needs the full data + a container runtime (see below)
```

**Full local task detail.** All four adapters expose `challenge_dir(task)` and
`challenge_detail(task)`, which read each challenge's real descriptor from the data repo (so you
can actually attempt a task). These carry flags / solution prompts and are therefore read
**locally only** — never committed:

```python
h = get_harness("nyuctf")
for task in h.load_tasks():
    d = h.challenge_detail(task)          # None if the data isn't located
    if d:
        print(task.task_id, "| networked:", d["_networked"], "| dir:", d["_dir"])
```

What `challenge_detail(task)` returns per benchmark (plus `_dir`/`_machine_dir` and
`_networked`): **nyuctf** → `challenge.json` (name, description, box, files, flag); **xbow** →
`benchmark.json` (name, description, level, tags; canaries stripped); **cybench** →
`metadata.json` (categories, difficulty, prompts, `target_host`, `_n_subtasks`); **autopenbench**
→ the `games.json` entry (task, flag, target, vulnerability).

Each task's `root_node_id` points at the matching knowledge-pack triage node
(`web::triage`, `crypto::triage`, …) when its category maps to a pack, so retrieval seeds from
the right place; network-pentest tasks (AutoPenBench) start from the generic `root` RECON node.

#### 5. Running a task (execution status)

`load_tasks()` is **real**. `start()` — spinning up the challenge container and driving the
engagement loop against it — needs the full data plus a container runtime and is a
**clearly-labeled stub** (`BenchmarkDataUnavailable`) in this build; wiring it is per-deployment
work. `Vulhub` remains a pure stub (no data was provided for it).

#### Adding another benchmark

1. add its folder name to `FOLDER` in `paths.py`;
2. add a `build_<name>()` extractor (metadata only — no flags) in `build_indices.py`;
3. subclass `BenchmarkHarnessBase` with a `_to_task(entry)` mapping;
4. register it in `registry.py`.

## Plug in any LLM (flexible API)

The model is always **frozen** (inference only — no training), and every model call goes through
one wrapper. [`axon/llm/backends.py`](axon/llm/backends.py) lets you point that wrapper at **any
provider** from config or code. Keys are **always read from environment variables named in
config — never hard-coded**.

Set it in `axon/config/default.yaml` (or your own YAML):

```yaml
llm:
  provider: openrouter                 # mock | openai | openrouter | anthropic | openai-compat | <registered>
  model: anthropic/claude-3.7-sonnet
  api_key_env: OPENROUTER_API_KEY      # the ENV VAR holding the key
  temperature: 0.0
  max_tokens: 1024
```

Built-in providers (all via one OpenAI-compatible or Anthropic path, stdlib only — no extra deps):

| `provider` | Works with | Needs |
|---|---|---|
| `mock` | offline tests (default) | nothing |
| `openai` | OpenAI | `OPENAI_API_KEY`, `model` |
| `openrouter` | OpenRouter → Anthropic/OpenAI/… | `OPENROUTER_API_KEY`, `model` |
| `anthropic` | Anthropic Messages API | `ANTHROPIC_API_KEY`, `model` |
| `openai-compat` | Together, Groq, Fireworks, **local** (Ollama `/v1`, vLLM, LM Studio) | `base_url` (+ key if required) |

```python
from axon.config import load_config
from axon.llm.client import LLMClient

cfg = load_config()
llm = LLMClient.from_config(cfg["llm"])     # builds the backend named by cfg["llm"]["provider"]
```

**Add any API you want** — two ways:

```python
from axon.llm.backends import CallableBackend, register_backend
from axon.llm.client import LLMClient, LLMConfig

# 1) wrap any function prompt -> text
llm = LLMClient(CallableBackend(lambda p: my_api_call(p)), LLMConfig())

# 2) register a named provider, then select it via `llm.provider: myco` in config
register_backend("myco", lambda cfg: CallableBackend(lambda p: my_api_call(p, cfg["model"])))
```

> Already have a client? The `agent pentest` project's `security_agents/openrouter_client.py`
> works out of the box via `provider: openrouter` (same `OPENROUTER_API_KEY`). To reuse that exact
> client (with its retries/telemetry), wrap it:
> `register_backend("openrouter-telemetry", lambda cfg: CallableBackend(lambda p: OpenRouterClient(...).complete(p).content))`.

## Project layout

```
axon/
  graph/        schema · procedural (G_K) · episodic (G_E) · matching · persistence
  knowledge/    construct · provenance firewall · embeddings · packs loader
  memory/       read (dense + PPR + folding) · verify (the gate) · write · lessons
  planning/     search (PUCT) · reversibility (the safety gate)
  llm/          frozen client (one call site) · prompts · flexible provider backends
  execution/    sandbox allowlist · tool runner · result types
  harness/      common benchmark interface · mock harness · benchmark stubs
  engagement/   the loop (Algorithm 1) · state/budget · events · replay · runner
  benchmark/    NYU CTF / AutoPenBench / Cybench / XBOW adapters + committed task indices
  eval/         metrics · experiment_a · experiment_b · baselines
  cli.py        construct / run / experiment-a / experiment-b / benchmarks / viz
  tests/        96 offline tests
knowledge_packs/  six CTF/pentest packs (111 tools) — the graph's source content
viz/              self-contained read-only visualizer (replay + live)
ARCHITECTURE.md · STATUS.md
```

## What is real vs. stubbed

Everything above runs end to end **offline** — 96 tests pass, and the CLI solves the mock task,
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
- **Your own model / API:** set `llm.provider` in config, or register a backend — see
  [Plug in any LLM](#plug-in-any-llm-flexible-api). Nothing else changes.
- **Your own embedder / tools / benchmark:** swap the embedder, implement `SubprocessBackend`,
  or add a harness adapter behind the common interface.

## Disclaimer

AXON is a research framework for **authorized** security testing, CTF, and education. Only run it
against systems you own or are explicitly permitted to test. The execution layer enforces a
sandbox allowlist and composes documented tools only — do not repurpose it to target systems you
are not authorized to assess.

"""Memory read — relevance-scored retrieval with context folding (SEGMENT 4).

At each step the agent pulls a small, relevant slice of G_K, never the whole graph. Retrieval
is hybrid:

1. **Dense similarity** between the current-state embedding and node embeddings -> seed nodes.
2. **Graph diffusion** — a personalized-PageRank-style spread from those seeds over G_K to pull
   in preconditioned neighbors, catching multi-hop paths pure similarity misses.

What comes back: a capped frontier of currently-relevant techniques, each with only the
lessons whose context signature matches the present state (not every lesson).

Context folding: :func:`fold_result` summarizes a raw sub-trajectory down to a short note so
the working context stays small over a long engagement; raw tool logs never enter it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..graph.episodic import EpisodicGraph
from ..graph.matching import matching_lessons
from ..graph.procedural import ProceduralGraph
from ..graph.schema import ContextSignature, EpisodicFactKind, Lesson, TechniqueNode
from ..knowledge.embeddings import Embedder, cosine


@dataclass
class FrontierItem:
    """One retrieved technique plus the lessons that apply right now."""

    node: TechniqueNode
    score: float
    lessons: list[Lesson] = field(default_factory=list)


@dataclass
class RetrievalResult:
    frontier: list[FrontierItem]
    seed_ids: list[str]
    state_context: ContextSignature

    @property
    def node_ids(self) -> list[str]:
        return [item.node.id for item in self.frontier]


def state_summary(episodic: EpisodicGraph) -> str:
    """Build the retrieval query text from the episodic graph (ports, versions, footholds)."""
    parts: list[str] = []
    for svc in episodic.facts_of_kind(EpisodicFactKind.SERVICE):
        name = svc.service or svc.attributes.get("name", "service")
        ver = svc.version or svc.attributes.get("version", "")
        port = svc.attributes.get("port", "")
        parts.append(f"{name} {ver} {port}".strip())
    for foot in episodic.facts_of_kind(EpisodicFactKind.FOOTHOLD):
        parts.append("foothold " + foot.attributes.get("desc", foot.id))
    for cred in episodic.facts_of_kind(EpisodicFactKind.CREDENTIAL):
        parts.append("credential " + cred.attributes.get("user", cred.id))
    return "; ".join(parts) if parts else "no findings yet; initial recon"


def state_context(episodic: EpisodicGraph) -> ContextSignature:
    """Pick a representative context signature for lesson matching.

    Uses the most recently added service fact if any (its service+version). This is the
    signature lessons are matched against this step.
    """
    services = episodic.facts_of_kind(EpisodicFactKind.SERVICE)
    if services:
        last = services[-1]
        return ContextSignature(last.service, last.version).normalized()
    return ContextSignature().normalized()


def personalized_pagerank(
    graph: ProceduralGraph,
    seed_scores: dict[str, float],
    *,
    restart: float = 0.15,
    iterations: int = 50,
) -> dict[str, float]:
    """PPR over G_K (treating all edge types as connectivity), restarting to the seeds.

    Pure-Python power iteration so the module has no hard NetworkX dependency. Returns a score
    per reachable node.
    """
    nodes = [n.id for n in graph.nodes()]
    if not nodes:
        return {}
    total_seed = sum(seed_scores.values()) or 1.0
    teleport = {nid: seed_scores.get(nid, 0.0) / total_seed for nid in nodes}

    # Out-adjacency (undirected-ish: diffusion follows edges forward; preconditions still link).
    out: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in graph.edges():
        out[e.src].append(e.dst)

    rank = dict(teleport)
    for _ in range(max(1, iterations)):
        nxt = {nid: restart * teleport[nid] for nid in nodes}
        for nid in nodes:
            neighbors = out[nid]
            if not neighbors:
                # Dangling node: spread its mass back to the teleport distribution.
                for m in nodes:
                    nxt[m] += (1 - restart) * rank[nid] * teleport[m]
                continue
            share = (1 - restart) * rank[nid] / len(neighbors)
            for m in neighbors:
                nxt[m] += share
        rank = nxt
    return rank


class MemoryReader:
    """Hybrid retrieval over G_K, driven by the episodic graph state."""

    def __init__(self, embedder: Embedder, cfg: dict) -> None:
        self.embedder = embedder
        read_cfg = cfg.get("memory", {}).get("read", {})
        self.dense_top_k = int(read_cfg.get("dense_top_k", 24))
        self.ppr_alpha = float(read_cfg.get("ppr_alpha", 0.15))
        self.ppr_iterations = int(read_cfg.get("ppr_iterations", 50))
        self.frontier_cap = int(read_cfg.get("frontier_cap", 16))
        self.max_lessons = int(read_cfg.get("max_lessons_per_node", 3))
        self.version_granularity = (
            cfg.get("memory", {}).get("match", {}).get("version_granularity", "major")
        )

    def retrieve(self, graph: ProceduralGraph, episodic: EpisodicGraph) -> RetrievalResult:
        ctx = state_context(episodic)
        if len(graph) == 0:
            return RetrievalResult(frontier=[], seed_ids=[], state_context=ctx)

        query_vec = self.embedder.embed(state_summary(episodic))

        # Stage 1: dense similarity -> seed nodes.
        sims: list[tuple[str, float]] = []
        for node in graph.nodes():
            if node.embedding is None:
                continue
            sims.append((node.id, cosine(query_vec, node.embedding)))
        sims.sort(key=lambda x: x[1], reverse=True)
        seeds = sims[: self.dense_top_k]
        if not seeds:
            # No embeddings matched; return empty frontier cleanly (corner case).
            return RetrievalResult(frontier=[], seed_ids=[], state_context=ctx)

        # Stage 2: graph diffusion from the seeds (only positive-similarity seeds restart).
        seed_scores = {nid: max(0.0, s) for nid, s in seeds if s > 0}
        if not seed_scores:
            seed_scores = {seeds[0][0]: 1.0}
        ppr = personalized_pagerank(
            graph, seed_scores, restart=self.ppr_alpha, iterations=self.ppr_iterations
        )

        # Blend dense similarity and diffusion; keep the highest-scored, capped.
        sim_map = dict(sims)
        combined: list[tuple[str, float]] = []
        for nid in {n.id for n in graph.nodes()}:
            score = 0.5 * sim_map.get(nid, 0.0) + 0.5 * ppr.get(nid, 0.0)
            if score > 0:
                combined.append((nid, score))
        combined.sort(key=lambda x: x[1], reverse=True)
        combined = combined[: self.frontier_cap]

        frontier: list[FrontierItem] = []
        for nid, score in combined:
            node = graph.get_node(nid)
            if node is None:
                continue
            lessons = matching_lessons(
                node.experience.lessons,
                ctx,
                version_granularity=self.version_granularity,
                limit=self.max_lessons,
            )
            frontier.append(FrontierItem(node=node, score=score, lessons=lessons))

        return RetrievalResult(
            frontier=frontier, seed_ids=[nid for nid, _ in seeds], state_context=ctx
        )


def fold_result(raw_trace: str, *, max_chars: int = 800) -> str:
    """Context folding: summarize a sub-trajectory so working context stays small (SEGMENT 4).

    STUB-grade summarizer: keeps the head and tail of the trace within ``max_chars``. A real
    deployment can route this through the LLM, but the contract is the same — raw tool logs
    must never reach the main working context.
    """
    text = raw_trace.strip()
    if len(text) <= max_chars:
        return text
    half = max_chars // 2 - 10
    return f"{text[:half]}\n...[folded {len(text) - 2 * half} chars]...\n{text[-half:]}"

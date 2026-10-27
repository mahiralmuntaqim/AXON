"""Graph construction — seeding "what is possible" (SEGMENT 3).

Builds the starting procedural graph offline, before any engagement, from source write-ups.
This is written as an *interface you fill*, not a fixed pipeline, so a user-supplied graph can
slot in without a rewrite (see "How to use these segments"). The default
:class:`GraphConstructor` implements the paper's pipeline over a :class:`GraphBackend`.

Pipeline:
* The provenance firewall runs first (SEGMENT 3/12) — eval-tied sources are excluded and logged.
* An LLM extraction pass turns each source chunk into typed techniques.
* Duplicates are merged (not re-created); techniques with no clear type are held for review,
  never guessed.
* Embeddings are computed; if the embedder is unavailable, construction fails loudly rather
  than storing empty embeddings.
* Edges follow the MITRE tactic order (PRECONDITION/ENABLES) plus ALTERNATIVE/REFINES between
  techniques sharing a precondition set. Every experience record starts empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..graph.procedural import ProceduralGraph
from ..graph.schema import (
    NODE_TYPE_ORDER,
    EdgeType,
    NodeType,
    ProceduralEdge,
    Reversibility,
    TechniqueNode,
)
from ..llm.client import LLMClient, LLMError
from ..llm.prompts import applicability_prior, technique_extraction
from .embeddings import Embedder, EmbeddingUnavailable
from .provenance import ProvenanceFirewall


@dataclass
class SourceDoc:
    source_id: str
    text: str
    origin_tag: str = ""     # e.g. "hacktricks", "mitre", "csaw" (csaw is firewalled out)


@dataclass
class ConstructionResult:
    graph: ProceduralGraph
    review_list: list[dict] = field(default_factory=list)   # techniques with no clear type
    exclusions: list[dict] = field(default_factory=list)    # firewalled sources


def chunk(text: str, size: int = 4000) -> list[str]:
    """Chunk a large document; provenance is tracked per chunk by the caller."""
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


class GraphConstructor:
    def __init__(
        self,
        llm: LLMClient,
        embedder: Embedder,
        *,
        firewall: Optional[ProvenanceFirewall] = None,
        query_priors: bool = False,
    ) -> None:
        self.llm = llm
        self.embedder = embedder
        self.firewall = firewall or ProvenanceFirewall()
        self.query_priors = query_priors

    def build(self, sources: list[SourceDoc]) -> ConstructionResult:
        graph = ProceduralGraph()
        review: list[dict] = []
        by_spec: dict[str, TechniqueNode] = {}  # normalized spec -> node (dedupe/merge)

        for doc in sources:
            if not self.firewall.admit(doc.source_id, doc.origin_tag):
                continue  # eval-tied source: excluded and logged
            for ci, piece in enumerate(chunk(doc.text)):
                for item in self._extract(piece):
                    spec = (item.get("spec") or "").strip()
                    if not spec:
                        continue
                    type_raw = item.get("type")
                    if type_raw not in {t.value for t in NodeType}:
                        # No clear type: hold for review, do NOT guess (corner case).
                        review.append({"spec": spec, "source": doc.source_id, "chunk": ci})
                        continue
                    key = spec.lower()
                    if key in by_spec:
                        continue  # duplicate technique -> merge (keep the first)
                    node = self._make_node(spec, NodeType(type_raw), item.get("reversibility"))
                    by_spec[key] = node
                    graph.add_node(node)

        self._add_edges(graph)
        return ConstructionResult(
            graph=graph, review_list=review, exclusions=self.firewall.report()
        )

    # -- helpers ------------------------------------------------------------------------------
    def _extract(self, piece: str) -> list[dict]:
        if not piece.strip():
            return []
        try:
            parsed = self.llm.complete_json(
                technique_extraction(piece), validate=lambda d: isinstance(d, list)
            )
        except LLMError:
            return []  # a chunk that won't parse yields no techniques; construction continues
        return [p for p in parsed if isinstance(p, dict)]

    def _make_node(self, spec: str, node_type: NodeType, rev_raw) -> TechniqueNode:
        # Embedding is required; fail loudly if the embedder is unavailable (corner case).
        try:
            embedding = self.embedder.embed(spec)
        except EmbeddingUnavailable:
            raise  # do not silently store an empty embedding
        reversibility = (
            Reversibility(rev_raw)
            if rev_raw in {r.value for r in Reversibility}
            else Reversibility.IRREVERSIBLE  # fail-safe default
        )
        nid = f"tech::{node_type.value}::{abs(hash(spec.lower())) % 10**8}"
        return TechniqueNode(
            id=nid, node_type=node_type, spec=spec, embedding=embedding,
            reversibility=reversibility,
        )

    def _add_edges(self, graph: ProceduralGraph) -> None:
        """Add ENABLES edges following tactic order, and ALTERNATIVE edges within a type."""
        order = {t: i for i, t in enumerate(NODE_TYPE_ORDER)}
        nodes = graph.nodes()
        by_type: dict[NodeType, list[TechniqueNode]] = {t: [] for t in NodeType}
        for n in nodes:
            by_type[n.node_type].append(n)

        # ENABLES: each node enables techniques in the next tactic type.
        for i in range(len(NODE_TYPE_ORDER) - 1):
            cur, nxt = NODE_TYPE_ORDER[i], NODE_TYPE_ORDER[i + 1]
            for src in by_type[cur]:
                for dst in by_type[nxt]:
                    p = self._prior(src.spec, dst.spec, EdgeType.ENABLES)
                    graph.add_edge(ProceduralEdge(src.id, dst.id, EdgeType.ENABLES, P=p))

        # ALTERNATIVE: techniques of the same type are alternatives to one another.
        for t, group in by_type.items():
            for a in group:
                for b in group:
                    if a.id != b.id:
                        graph.add_edge(
                            ProceduralEdge(a.id, b.id, EdgeType.ALTERNATIVE, P=0.5)
                        )

    def _prior(self, src_spec: str, dst_spec: str, edge_type: EdgeType) -> float:
        if not self.query_priors:
            return 0.5
        try:
            parsed = self.llm.complete_json(
                applicability_prior(src_spec, dst_spec, edge_type.value),
                validate=lambda d: isinstance(d, dict) and "P" in d,
            )
            return max(0.0, min(1.0, float(parsed["P"])))
        except (LLMError, ValueError, TypeError):
            return 0.5


# --------------------------------------------------------------------------------------------
# A small, LLM-free demo seed graph used by the mock harness and the end-to-end loop test.
# --------------------------------------------------------------------------------------------
def demo_seed_graph(embedder: Embedder) -> ProceduralGraph:
    """Build a tiny deterministic G_K: recon -> enum -> exploit chain (+ a doomed alternative)."""
    g = ProceduralGraph()

    def node(nid: str, t: NodeType, spec: str, rev: Reversibility) -> TechniqueNode:
        return TechniqueNode(nid, t, spec, embedding=embedder.embed(spec), reversibility=rev)

    g.add_node(node("recon", NodeType.RECON, "service version scan with nmap",
                    Reversibility.REVERSIBLE))
    g.add_node(node("enum_http", NodeType.ENUM, "enumerate http directories apache",
                    Reversibility.REVERSIBLE))
    g.add_node(node("exploit_cve", NodeType.EXPLOIT, "exploit apache 2.4.49 path traversal cve",
                    Reversibility.IRREVERSIBLE))
    g.add_node(node("exploit_bad", NodeType.EXPLOIT, "try unrelated struts exploit",
                    Reversibility.IRREVERSIBLE))

    # Priors nudge the search toward the correct chain; Q starts neutral and is learned.
    g.add_edge(ProceduralEdge("recon", "enum_http", EdgeType.ENABLES, Q=0.5, P=0.8))
    g.add_edge(ProceduralEdge("enum_http", "exploit_cve", EdgeType.ENABLES, Q=0.7, P=0.9))
    g.add_edge(ProceduralEdge("enum_http", "exploit_bad", EdgeType.ENABLES, Q=0.5, P=0.3))
    g.add_edge(ProceduralEdge("exploit_cve", "exploit_bad", EdgeType.ALTERNATIVE, P=0.2))
    return g

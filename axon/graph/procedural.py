"""Procedural graph G_K — the persistent "what is possible" store (SEGMENT 2).

Shared across targets, survives forever. Holds only :class:`TechniqueNode` and
:class:`ProceduralEdge`. It refuses anything else, which is how target secrets are kept out
(rule 3). Storage is plain dicts (implements :class:`GraphBackend`); the memory layer can
build a NetworkX view on top for PPR without this module depending on NetworkX.
"""

from __future__ import annotations

from typing import Iterable, Optional

from .schema import (
    EdgeType,
    ExperienceRecord,
    GraphBackend,
    ProceduralEdge,
    TechniqueNode,
)


class ProceduralGraph(GraphBackend):
    """Container for G_K. Accepts only technique nodes and procedural edges."""

    def __init__(self) -> None:
        self._nodes: dict[str, TechniqueNode] = {}
        # edges keyed by (src, dst, edge_type) so parallel edges of different types coexist.
        self._edges: dict[tuple[str, str, str], ProceduralEdge] = {}
        self._out: dict[str, list[tuple[str, str, str]]] = {}
        self._in: dict[str, list[tuple[str, str, str]]] = {}

    # -- nodes ------------------------------------------------------------------------------
    def add_node(self, node: TechniqueNode) -> None:
        if not isinstance(node, TechniqueNode):
            # Hard guard: an EpisodicFact (or anything else) can never enter G_K.
            raise TypeError(
                f"ProceduralGraph accepts only TechniqueNode, got {type(node).__name__}. "
                "Episodic facts must never be written to the procedural graph."
            )
        self._nodes[node.id] = node
        self._out.setdefault(node.id, [])
        self._in.setdefault(node.id, [])

    def get_node(self, node_id: str) -> Optional[TechniqueNode]:
        return self._nodes.get(node_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def nodes(self) -> list[TechniqueNode]:
        return list(self._nodes.values())

    # -- edges ------------------------------------------------------------------------------
    def add_edge(self, edge: ProceduralEdge) -> None:
        if not isinstance(edge, ProceduralEdge):
            raise TypeError(f"expected ProceduralEdge, got {type(edge).__name__}")
        if edge.src not in self._nodes or edge.dst not in self._nodes:
            raise ValueError(
                f"edge {edge.src}->{edge.dst} references a node not in the graph; "
                "add both endpoints first"
            )
        key = edge.key
        self._edges[key] = edge
        if key not in self._out[edge.src]:
            self._out[edge.src].append(key)
        if key not in self._in[edge.dst]:
            self._in[edge.dst].append(key)

    def get_edge(
        self, src: str, dst: str, edge_type: EdgeType
    ) -> Optional[ProceduralEdge]:
        return self._edges.get((src, dst, edge_type.value))

    def out_edges(self, node_id: str) -> list[ProceduralEdge]:
        return [self._edges[k] for k in self._out.get(node_id, [])]

    def in_edges(self, node_id: str) -> list[ProceduralEdge]:
        return [self._edges[k] for k in self._in.get(node_id, [])]

    def edges(self) -> list[ProceduralEdge]:
        return list(self._edges.values())

    # -- convenience ------------------------------------------------------------------------
    def experience(self, node_id: str) -> Optional[ExperienceRecord]:
        node = self._nodes.get(node_id)
        return node.experience if node else None

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: object) -> bool:
        return isinstance(node_id, str) and node_id in self._nodes

    def extend(self, nodes: Iterable[TechniqueNode], edges: Iterable[ProceduralEdge]) -> None:
        for n in nodes:
            self.add_node(n)
        for e in edges:
            self.add_edge(e)

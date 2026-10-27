"""Snapshot save/load (SEGMENT 2).

Two *separate* serializers — one for the procedural graph, one for the episodic graph — so a
save of one can never accidentally include the other (rule 3). The procedural serializer
raises if handed an episodic graph, and vice versa.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .episodic import EpisodicGraph
from .procedural import ProceduralGraph
from .schema import (
    ContextSignature,
    EdgeType,
    EpisodicFact,
    EpisodicFactKind,
    ExperienceRecord,
    Lesson,
    NodeType,
    ProceduralEdge,
    Reversibility,
    TechniqueNode,
)

PROCEDURAL_KIND = "axon.procedural.v1"
EPISODIC_KIND = "axon.episodic.v1"


# --------------------------------------------------------------------------------------------
# Procedural graph G_K
# --------------------------------------------------------------------------------------------
def serialize_procedural(graph: ProceduralGraph) -> dict[str, Any]:
    """Serialize ONLY the procedural graph. Rejects anything that is not a ProceduralGraph."""
    if not isinstance(graph, ProceduralGraph):
        raise TypeError(
            "serialize_procedural accepts only ProceduralGraph; refusing to serialize "
            f"{type(graph).__name__} (episodic data must never enter a procedural snapshot)"
        )
    nodes = []
    for n in graph.nodes():
        nodes.append(
            {
                "id": n.id,
                "node_type": n.node_type.value,
                "spec": n.spec,
                "embedding": list(n.embedding) if n.embedding is not None else None,
                "reversibility": n.reversibility.value,
                "metadata": dict(n.metadata),
                "experience": {
                    "n_plus": n.experience.n_plus,
                    "n_minus": n.experience.n_minus,
                    "lessons": [
                        {
                            "context": {
                                "service": l.context.service,
                                "version": l.context.version,
                                "defense": l.context.defense,
                            },
                            "text": l.text,
                            "success": l.success,
                        }
                        for l in n.experience.lessons
                    ],
                },
            }
        )
    edges = []
    for e in graph.edges():
        edges.append(
            {
                "src": e.src,
                "dst": e.dst,
                "edge_type": e.edge_type.value,
                "Q": e.Q,
                "P": e.P,
                "n_plus": e.n_plus,
                "n_minus": e.n_minus,
                "visits": e.visits,
            }
        )
    return {"kind": PROCEDURAL_KIND, "nodes": nodes, "edges": edges}


def deserialize_procedural(data: dict[str, Any]) -> ProceduralGraph:
    if data.get("kind") != PROCEDURAL_KIND:
        raise ValueError(f"not a procedural snapshot (kind={data.get('kind')!r})")
    g = ProceduralGraph()
    for nd in data["nodes"]:
        exp = nd["experience"]
        lessons = [
            Lesson(
                context=ContextSignature(**l["context"]),
                text=l["text"],
                success=l["success"],
            )
            for l in exp["lessons"]
        ]
        g.add_node(
            TechniqueNode(
                id=nd["id"],
                node_type=NodeType(nd["node_type"]),
                spec=nd["spec"],
                embedding=nd["embedding"],
                experience=ExperienceRecord(exp["n_plus"], exp["n_minus"], lessons),
                reversibility=Reversibility(nd["reversibility"]),
                metadata=dict(nd.get("metadata", {})),
            )
        )
    for ed in data["edges"]:
        g.add_edge(
            ProceduralEdge(
                src=ed["src"],
                dst=ed["dst"],
                edge_type=EdgeType(ed["edge_type"]),
                Q=ed["Q"],
                P=ed["P"],
                n_plus=ed["n_plus"],
                n_minus=ed["n_minus"],
                visits=ed["visits"],
            )
        )
    return g


def save_procedural(graph: ProceduralGraph, path: str | Path) -> None:
    Path(path).write_text(json.dumps(serialize_procedural(graph), indent=2), encoding="utf-8")


def load_procedural(path: str | Path) -> ProceduralGraph:
    return deserialize_procedural(json.loads(Path(path).read_text(encoding="utf-8")))


# --------------------------------------------------------------------------------------------
# Episodic graph G_E  (kept entirely separate)
# --------------------------------------------------------------------------------------------
def serialize_episodic(graph: EpisodicGraph) -> dict[str, Any]:
    """Serialize ONLY the episodic graph. Rejects anything that is not an EpisodicGraph."""
    if not isinstance(graph, EpisodicGraph):
        raise TypeError(
            "serialize_episodic accepts only EpisodicGraph; refusing to serialize "
            f"{type(graph).__name__}"
        )
    return {
        "kind": EPISODIC_KIND,
        "engagement_id": graph.engagement_id,
        "facts": [
            {
                "id": f.id,
                "kind": f.kind.value,
                "attributes": f.attributes,
                "service": f.service,
                "version": f.version,
            }
            for f in graph.facts()
        ],
        "relations": [list(r) for r in graph.relations()],
    }


def deserialize_episodic(data: dict[str, Any]) -> EpisodicGraph:
    if data.get("kind") != EPISODIC_KIND:
        raise ValueError(f"not an episodic snapshot (kind={data.get('kind')!r})")
    g = EpisodicGraph(data["engagement_id"])
    for f in data["facts"]:
        g.add_fact(
            EpisodicFact(
                id=f["id"],
                kind=EpisodicFactKind(f["kind"]),
                attributes=dict(f["attributes"]),
                service=f["service"],
                version=f["version"],
            )
        )
    for r in data["relations"]:
        g.relate(r[0], r[1], r[2])
    return g

"""Knowledge-pack loader tests (SEGMENT 3 content integration)."""

import pytest

from axon.graph.persistence import deserialize_procedural, serialize_procedural
from axon.graph.schema import EdgeType, NodeType
from axon.knowledge.embeddings import HashingEmbedder
from axon.knowledge.packs import (
    DEFAULT_PACKS_DIR,
    build_procedural_graph,
    classify_node_type,
    load_packs,
    to_source_docs,
)

pytestmark = pytest.mark.skipif(
    not DEFAULT_PACKS_DIR.is_dir(), reason="bundled knowledge_packs not present"
)


def _emb():
    return HashingEmbedder(dim=128)


def test_load_packs_reads_all_six_categories():
    packs = load_packs()
    cats = {p.category for p in packs}
    assert cats == {"crypto", "pwn", "rev", "web", "forensics", "misc"}
    for p in packs:
        assert p.tools and p.summary


def test_classifier_routes_roles_to_types():
    assert classify_node_type("sqlmap", "exploit SQL injection, dump DB", NodeType.EXPLOIT) is NodeType.EXPLOIT
    assert classify_node_type("ffuf", "content discovery, fuzz dirs", NodeType.ENUM) is NodeType.ENUM
    assert classify_node_type("whatweb", "fingerprint the tech stack", NodeType.ENUM) is NodeType.RECON


def test_build_graph_has_real_scale_and_valid_types():
    result = build_procedural_graph(embedder=_emb())
    assert result.n_categories == 6
    assert result.n_tools >= 100              # ~111 curated tools
    g = result.graph
    assert len(g) >= 106                       # tools + 6 triage nodes
    # Every node is one of the six valid types; every edge one of the four valid types.
    assert all(isinstance(n.node_type, NodeType) for n in g.nodes())
    assert all(isinstance(e.edge_type, EdgeType) for e in g.edges())
    # Each category has a reversible RECON triage node.
    for cat in ("web", "crypto", "pwn", "rev", "forensics", "misc"):
        t = g.get_node(f"{cat}::triage")
        assert t is not None and t.node_type is NodeType.RECON
        assert t.reversibility.value == "REVERSIBLE"


def test_tool_metadata_is_carried_and_survives_persistence():
    g = build_procedural_graph(embedder=_emb()).graph
    sqlmap = g.get_node("web::sqlmap")
    assert sqlmap is not None
    assert sqlmap.metadata["tool"] == "sqlmap"
    assert "docs" in sqlmap.metadata and sqlmap.metadata["category"] == "web"
    # metadata round-trips through a snapshot.
    restored = deserialize_procedural(serialize_procedural(g))
    assert restored.get_node("web::sqlmap").metadata["tool"] == "sqlmap"


def test_category_subgraph_wires_enables_edges():
    g = build_procedural_graph(embedder=_emb()).graph
    # Within web, the triage RECON node should enable at least one downstream technique.
    outs = g.out_edges("web::triage")
    assert any(e.edge_type is EdgeType.ENABLES for e in outs)


def test_to_source_docs_matches_categories():
    docs = to_source_docs()
    assert len(docs) == 6
    assert all(d.text and d.origin_tag == "ctf-knowledge-pack" for d in docs)

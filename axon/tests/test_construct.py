"""Graph construction tests (SEGMENT 3)."""

import pytest

from axon.knowledge.construct import GraphConstructor, SourceDoc
from axon.knowledge.embeddings import EmbeddingUnavailable, HashingEmbedder, SentenceTransformerEmbedder
from axon.llm.client import LLMClient, LLMConfig, MockLLM


def _constructor(extraction: str, embedder=None):
    backend = MockLLM(routes=[(lambda p: "extract pentest techniques" in p, lambda p: extraction)])
    llm = LLMClient(backend, LLMConfig(model="mock"))
    return GraphConstructor(llm, embedder or HashingEmbedder(dim=32))


def test_duplicate_techniques_are_merged_not_duplicated():
    extraction = (
        '[{"spec": "nmap scan", "type": "RECON", "reversibility": "REVERSIBLE"},'
        ' {"spec": "nmap scan", "type": "RECON", "reversibility": "REVERSIBLE"}]'
    )
    result = _constructor(extraction).build([SourceDoc("d", "text", "hacktricks")])
    specs = [n.spec for n in result.graph.nodes()]
    assert specs.count("nmap scan") == 1


def test_untyped_technique_is_held_for_review_not_guessed():
    extraction = (
        '[{"spec": "mystery technique", "type": null},'
        ' {"spec": "sqlmap injection", "type": "EXPLOIT"}]'
    )
    result = _constructor(extraction).build([SourceDoc("d", "text", "hacktricks")])
    specs = [n.spec for n in result.graph.nodes()]
    assert "mystery technique" not in specs
    assert any(r["spec"] == "mystery technique" for r in result.review_list)
    assert "sqlmap injection" in specs


def test_edges_follow_tactic_order():
    extraction = (
        '[{"spec": "recon scan", "type": "RECON"},'
        ' {"spec": "enum dirs", "type": "ENUM"}]'
    )
    result = _constructor(extraction).build([SourceDoc("d", "text", "hacktricks")])
    g = result.graph
    recon = next(n for n in g.nodes() if n.node_type.value == "RECON")
    enum = next(n for n in g.nodes() if n.node_type.value == "ENUM")
    # RECON ENABLES ENUM (next tactic).
    from axon.graph.schema import EdgeType
    assert g.get_edge(recon.id, enum.id, EdgeType.ENABLES) is not None


def test_construction_fails_loudly_when_embedder_unavailable():
    extraction = '[{"spec": "nmap scan", "type": "RECON"}]'
    gc = _constructor(extraction, embedder=SentenceTransformerEmbedder("unavailable"))
    with pytest.raises(EmbeddingUnavailable):
        gc.build([SourceDoc("d", "text", "hacktricks")])

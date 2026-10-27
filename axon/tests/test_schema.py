"""Schema tests (SEGMENT 2 + SEGMENT 16): try to break every rule, confirm the code refuses."""

import math

import pytest

from axon.graph.episodic import EpisodicGraph
from axon.graph.persistence import (
    deserialize_episodic,
    deserialize_procedural,
    serialize_episodic,
    serialize_procedural,
)
from axon.graph.procedural import ProceduralGraph
from axon.graph.schema import (
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


def _node(nid: str, t: NodeType = NodeType.RECON) -> TechniqueNode:
    return TechniqueNode(id=nid, node_type=t, spec=f"spec for {nid}", embedding=[0.1, 0.2])


# -- bad node types ---------------------------------------------------------------------------
def test_node_type_outside_six_is_rejected():
    with pytest.raises(ValueError):
        TechniqueNode(id="x", node_type="HACKING", spec="s")  # type: ignore[arg-type]


def test_all_six_node_types_accepted():
    for t in NodeType:
        n = _node(f"n_{t.value}", t)
        assert n.node_type is t


def test_empty_spec_rejected():
    with pytest.raises(ValueError):
        TechniqueNode(id="x", node_type=NodeType.RECON, spec="   ")


# -- bad edge types ---------------------------------------------------------------------------
def test_edge_type_outside_four_is_rejected():
    with pytest.raises(ValueError):
        ProceduralEdge(src="a", dst="b", edge_type="CAUSES")  # type: ignore[arg-type]


def test_all_four_edge_types_accepted():
    for et in EdgeType:
        e = ProceduralEdge(src="a", dst="b", edge_type=et)
        assert e.edge_type is et


# -- Q / P range ------------------------------------------------------------------------------
def test_q_p_clamped_when_clamp_true():
    e = ProceduralEdge(src="a", dst="b", edge_type=EdgeType.ENABLES, Q=1.5, P=-0.2, _clamp=True)
    assert e.Q == 1.0 and e.P == 0.0


def test_q_p_rejected_when_clamp_false():
    with pytest.raises(ValueError):
        ProceduralEdge(src="a", dst="b", edge_type=EdgeType.ENABLES, Q=1.5, _clamp=False)
    with pytest.raises(ValueError):
        ProceduralEdge(src="a", dst="b", edge_type=EdgeType.ENABLES, P=-0.1, _clamp=False)


def test_q_nan_rejected():
    with pytest.raises(ValueError):
        ProceduralEdge(src="a", dst="b", edge_type=EdgeType.ENABLES, Q=math.nan)


def test_negative_counts_rejected():
    with pytest.raises(ValueError):
        ExperienceRecord(n_plus=-1)
    with pytest.raises(ValueError):
        ProceduralEdge(src="a", dst="b", edge_type=EdgeType.ENABLES, n_minus=-3)


# -- episodic facts cannot enter G_K ----------------------------------------------------------
def test_episodic_fact_cannot_be_added_to_procedural_graph():
    g = ProceduralGraph()
    fact = EpisodicFact(id="h1", kind=EpisodicFactKind.HOST)
    with pytest.raises(TypeError):
        g.add_node(fact)  # type: ignore[arg-type]


def test_technique_node_cannot_be_added_to_episodic_graph():
    g = EpisodicGraph("eng-1")
    with pytest.raises(TypeError):
        g.add_fact(_node("n1"))  # type: ignore[arg-type]


def test_edge_requires_both_endpoints_present():
    g = ProceduralGraph()
    g.add_node(_node("a"))
    with pytest.raises(ValueError):
        g.add_edge(ProceduralEdge(src="a", dst="missing", edge_type=EdgeType.ENABLES))


# -- serialization keeps the two graphs separate ----------------------------------------------
def test_serialize_procedural_rejects_episodic_graph():
    with pytest.raises(TypeError):
        serialize_procedural(EpisodicGraph("eng-1"))  # type: ignore[arg-type]


def test_serialize_episodic_rejects_procedural_graph():
    with pytest.raises(TypeError):
        serialize_episodic(ProceduralGraph())  # type: ignore[arg-type]


def test_procedural_roundtrip_preserves_everything():
    g = ProceduralGraph()
    a = _node("a", NodeType.ENUM)
    b = _node("b", NodeType.EXPLOIT)
    b.experience.record_success()
    b.experience.add_lesson(
        Lesson(ContextSignature("apache", "2.4.49", "none"), "path traversal works", True)
    )
    g.add_node(a)
    g.add_node(b)
    g.add_edge(ProceduralEdge("a", "b", EdgeType.ENABLES, Q=0.7, P=0.6, n_plus=1, visits=1))

    restored = deserialize_procedural(serialize_procedural(g))
    assert {n.id for n in restored.nodes()} == {"a", "b"}
    rb = restored.get_node("b")
    assert rb is not None and rb.experience.n_plus == 1
    assert rb.experience.lessons[0].context.service == "apache"
    re = restored.get_edge("a", "b", EdgeType.ENABLES)
    assert re is not None and re.Q == 0.7 and re.n_plus == 1


def test_episodic_roundtrip():
    g = EpisodicGraph("eng-9")
    g.add_fact(EpisodicFact("h1", EpisodicFactKind.HOST, {"ip": "10.0.0.5"}))
    g.add_fact(
        EpisodicFact("s1", EpisodicFactKind.SERVICE, service="apache", version="2.4.49")
    )
    g.relate("h1", "s1", "runs")
    restored = deserialize_episodic(serialize_episodic(g))
    assert len(restored) == 2
    assert restored.services()[0].service == "apache"
    assert restored.relations() == [("h1", "s1", "runs")]


# -- context signature helpers ----------------------------------------------------------------
def test_context_signature_normalization_and_major_version():
    sig = ContextSignature("  Apache ", "2.4.49", " WAF ").normalized()
    assert sig.service == "apache" and sig.defense == "waf"
    assert sig.major_version() == "2"


def test_reversibility_defaults_to_irreversible():
    # Fail-safe default so unknown techniques are treated as dangerous (SEGMENT 7).
    assert _node("n").reversibility is Reversibility.IRREVERSIBLE

"""Memory-layer tests: the verification gate, Bayesian update, and retrieval (SEGMENT 16)."""

import pytest

from axon.execution.result import ActionResult, StateTransition, TransitionKind
from axon.graph.episodic import EpisodicGraph
from axon.graph.procedural import ProceduralGraph
from axon.graph.schema import (
    ContextSignature,
    EdgeType,
    EpisodicFact,
    EpisodicFactKind,
    NodeType,
    ProceduralEdge,
    TechniqueNode,
)
from axon.knowledge.embeddings import HashingEmbedder
from axon.memory.read import MemoryReader, fold_result
from axon.memory.verify import Attribution, Outcome, VerificationGate
from axon.memory.write import WritebackEngine, beta_posterior

CFG = {
    "graph": {"alpha": 1.0, "beta": 1.0},
    "verify": {"require_state_transition": True},
    "memory": {
        "read": {"dense_top_k": 24, "frontier_cap": 4, "max_lessons_per_node": 3},
        "match": {"version_granularity": "major"},
    },
}


# -- the verification gate --------------------------------------------------------------------
def test_hallucinated_flag_with_no_trace_is_not_verified():
    gate = VerificationGate(CFG)
    res = ActionResult(
        technique_id="t", command="echo flag{fake}", claimed_success=True, claimed_outcome="flag"
    )  # no state transition / milestone
    v = gate.check(res)
    assert v.verified is False
    assert v.attribution is Attribution.HALLUCINATED
    assert v.outcome is Outcome.INCONCLUSIVE


def test_claimed_success_with_state_transition_is_verified():
    gate = VerificationGate(CFG)
    res = ActionResult(
        technique_id="t",
        command="exploit",
        claimed_success=True,
        state_transitions=[StateTransition(TransitionKind.NEW_SHELL, "uid=0")],
    )
    v = gate.check(res)
    assert v.verified is True and v.is_success


def test_tool_typo_is_not_charged_against_the_technique():
    gate = VerificationGate(CFG)
    res = ActionResult(
        technique_id="t",
        command="nmpa -sV target",  # typo'd binary
        exit_code=127,
        stderr="bash: nmpa: command not found",
    )
    v = gate.check(res)
    assert v.verified is False
    assert v.attribution is Attribution.TOOL_ERROR
    assert v.outcome is Outcome.INCONCLUSIVE


def test_timeout_is_a_tool_error_not_a_failure():
    gate = VerificationGate(CFG)
    res = ActionResult(technique_id="t", command="hydra ...", timed_out=True)
    v = gate.check(res)
    assert v.attribution is Attribution.TOOL_ERROR and v.verified is False


def test_genuine_hypothesis_failure_is_charged():
    gate = VerificationGate(CFG)
    res = ActionResult(
        technique_id="t",
        command="curl http://target/vuln",
        exit_code=0,
        stdout="403 Forbidden",
        claimed_success=False,
    )
    v = gate.check(res)
    assert v.verified is True
    assert v.is_genuine_failure
    assert v.outcome is Outcome.FAILURE


# -- writeback: nothing written when the gate fails -------------------------------------------
def _graph_with_edge():
    g = ProceduralGraph()
    g.add_node(TechniqueNode("a", NodeType.ENUM, "enum", embedding=[0.1]))
    g.add_node(TechniqueNode("b", NodeType.EXPLOIT, "exploit", embedding=[0.2]))
    edge = ProceduralEdge("a", "b", EdgeType.ENABLES, Q=0.5, P=0.5)
    g.add_edge(edge)
    return g, edge


def test_tool_error_promotes_nothing_and_charges_nothing():
    g, edge = _graph_with_edge()
    node_b = g.get_node("b")
    gate = VerificationGate(CFG)
    res = ActionResult("b", "nmpa", exit_code=127, stderr="command not found")
    v = gate.check(res)
    wb = WritebackEngine(CFG)
    report = wb.write(
        g, edge=edge, node=node_b, verification=v, result=res,
        state_context=ContextSignature("apache", "2.4.49"),
    )
    assert report.wrote_anything is False
    assert edge.n_plus == 0 and edge.n_minus == 0  # technique not charged
    assert node_b.experience.n_minus == 0
    # Structural growth also refused.
    grow = wb.grow(
        g, new_spec="novel chain", node_type=NodeType.EXPLOIT,
        reversibility=node_b.reversibility, from_node_id="a", edge_type=EdgeType.ENABLES,
        verification=v, result=res,
    )
    assert grow.wrote_anything is False and grow.new_node_id is None


# -- Bayesian update: one failure cannot drop a long-successful edge below usable --------------
def test_one_failure_does_not_tank_a_long_successful_edge():
    alpha = beta = 1.0
    # 50 verified successes, then a single failure.
    q_before = beta_posterior(50, 0, alpha, beta)
    q_after = beta_posterior(50, 1, alpha, beta)
    assert q_before > 0.95
    assert q_after > 0.9           # still clearly usable
    assert q_before - q_after < 0.05  # one fluke only nudges it


def test_writeback_updates_q_via_beta():
    g, edge = _graph_with_edge()
    node_b = g.get_node("b")
    gate = VerificationGate(CFG)
    wb = WritebackEngine(CFG)
    res = ActionResult(
        "b", "exploit", claimed_success=True,
        state_transitions=[StateTransition(TransitionKind.NEW_SHELL)],
    )
    v = gate.check(res)
    report = wb.write(
        g, edge=edge, node=node_b, verification=v, result=res,
        state_context=ContextSignature("apache", "2.4.49"),
    )
    assert report.old_Q == 0.5
    assert edge.n_plus == 1 and edge.visits == 1
    assert report.new_Q == pytest.approx(beta_posterior(1, 0, 1.0, 1.0))  # 2/3
    assert node_b.experience.n_plus == 1
    assert len(node_b.experience.lessons) == 1


# -- structural growth only with a verified state transition ----------------------------------
def test_growth_promotes_only_with_state_transition():
    g, edge = _graph_with_edge()
    node_b = g.get_node("b")
    gate = VerificationGate(CFG)
    wb = WritebackEngine(CFG, embedder=HashingEmbedder(dim=16))
    res = ActionResult(
        "b", "exploit", claimed_success=True,
        state_transitions=[StateTransition(TransitionKind.NEW_SHELL)],
    )
    v = gate.check(res)
    grow = wb.grow(
        g, new_spec="chained privesc via sudo misconfig", node_type=NodeType.PRIVESC,
        reversibility=node_b.reversibility, from_node_id="b", edge_type=EdgeType.ENABLES,
        verification=v, result=res,
    )
    assert grow.new_node_id is not None
    assert g.has_node(grow.new_node_id)


# -- retrieval: empty frontier and context cap ------------------------------------------------
def test_empty_graph_returns_empty_frontier_cleanly():
    reader = MemoryReader(HashingEmbedder(dim=32), CFG)
    g = ProceduralGraph()
    eg = EpisodicGraph("e1")
    result = reader.retrieve(g, eg)
    assert result.frontier == [] and result.seed_ids == []


def test_frontier_is_capped():
    reader = MemoryReader(HashingEmbedder(dim=64), CFG)  # frontier_cap=4
    g = ProceduralGraph()
    for i in range(20):
        g.add_node(
            TechniqueNode(
                f"n{i}", NodeType.EXPLOIT, f"exploit apache http server variant {i}",
                embedding=HashingEmbedder(dim=64).embed(f"apache http {i}"),
            )
        )
    eg = EpisodicGraph("e1")
    eg.add_fact(EpisodicFact("s1", EpisodicFactKind.SERVICE, service="apache", version="2.4.49",
                             attributes={"port": "80"}))
    result = reader.retrieve(g, eg)
    assert 0 < len(result.frontier) <= 4


def test_fold_keeps_context_small():
    big = "A" * 5000
    folded = fold_result(big, max_chars=800)
    assert len(folded) <= 850  # cap plus the marker text
    assert "folded" in folded

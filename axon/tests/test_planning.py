"""Planning + safety-gate tests (SEGMENT 6, SEGMENT 7, SEGMENT 16)."""

from axon.graph.procedural import ProceduralGraph
from axon.graph.schema import (
    EdgeType,
    NodeType,
    ProceduralEdge,
    Reversibility,
    TechniqueNode,
)
from axon.planning.reversibility import check_action
from axon.planning.search import Planner, back_up, puct_score

CFG = {"planning": {"c_puct": 1.4, "backtrack_q_threshold": 0.2}, "safety": {"q_min": 0.6}}


def _graph():
    g = ProceduralGraph()
    g.add_node(TechniqueNode("root", NodeType.RECON, "recon", embedding=[0.0]))
    # reversible enum sibling
    g.add_node(
        TechniqueNode("enum", NodeType.ENUM, "enumerate", embedding=[0.0],
                      reversibility=Reversibility.REVERSIBLE)
    )
    # irreversible exploit
    g.add_node(
        TechniqueNode("exploit", NodeType.EXPLOIT, "destructive exploit", embedding=[0.0],
                      reversibility=Reversibility.IRREVERSIBLE)
    )
    return g


# -- PUCT ------------------------------------------------------------------------------------
def test_puct_prefers_higher_q_when_priors_equal():
    hi = ProceduralEdge("root", "enum", EdgeType.ENABLES, Q=0.8, P=0.5, visits=1)
    lo = ProceduralEdge("root", "exploit", EdgeType.ENABLES, Q=0.3, P=0.5, visits=1)
    assert puct_score(hi, 4, 1.4) > puct_score(lo, 4, 1.4)


def test_puct_exploration_favors_unvisited_edge():
    # Equal Q; the less-visited edge gets a higher exploration bonus.
    visited = ProceduralEdge("root", "enum", EdgeType.ENABLES, Q=0.5, P=0.5, visits=10)
    fresh = ProceduralEdge("root", "exploit", EdgeType.ENABLES, Q=0.5, P=0.5, visits=0)
    assert puct_score(fresh, 10, 1.4) > puct_score(visited, 10, 1.4)


# -- the irreversibility gate (SEGMENT 7) ----------------------------------------------------
def test_low_confidence_irreversible_action_is_never_executed():
    g = _graph()
    exploit = g.get_node("exploit")
    edge = ProceduralEdge("root", "exploit", EdgeType.ENABLES, Q=0.4, P=0.9)  # Q below q_min
    decision = check_action(exploit, edge, q_min=0.6, budget_ok=True)
    assert decision.allowed is False


def test_irreversible_allowed_only_at_or_above_floor_and_budget():
    g = _graph()
    exploit = g.get_node("exploit")
    edge = ProceduralEdge("root", "exploit", EdgeType.ENABLES, Q=0.6, P=0.9)
    assert check_action(exploit, edge, q_min=0.6, budget_ok=True).allowed is True
    # same confidence but no budget -> held back
    assert check_action(exploit, edge, q_min=0.6, budget_ok=False).allowed is False


def test_reversible_action_always_allowed_even_at_low_q():
    g = _graph()
    enum = g.get_node("enum")
    edge = ProceduralEdge("root", "enum", EdgeType.ENABLES, Q=0.01, P=0.1)
    assert check_action(enum, edge, q_min=0.6, budget_ok=True).allowed is True


def test_choose_prefers_reversible_sibling_over_low_confidence_irreversible():
    g = _graph()
    planner = Planner(CFG)
    # Irreversible exploit scores highest by raw PUCT, but is below q_min -> must be skipped.
    irr = ProceduralEdge("root", "exploit", EdgeType.ENABLES, Q=0.5, P=0.99, visits=0)
    rev = ProceduralEdge("root", "enum", EdgeType.ENABLES, Q=0.45, P=0.2, visits=0)
    g.add_edge(irr)
    g.add_edge(rev)
    chosen, decision = planner.choose(g, "root", [irr, rev], budget_ok=True)
    assert chosen is not None
    assert chosen.edge.dst == "enum"  # reversible sibling picked
    assert decision.allowed is True


def test_choose_returns_none_when_only_unsafe_actions_exist():
    g = _graph()
    planner = Planner(CFG)
    irr = ProceduralEdge("root", "exploit", EdgeType.ENABLES, Q=0.1, P=0.9)
    g.add_edge(irr)
    chosen, decision = planner.choose(g, "root", [irr], budget_ok=True)
    assert chosen is None and decision.allowed is False


def test_backtrack_threshold():
    planner = Planner(CFG)
    assert planner.should_backtrack(0.1) is True
    assert planner.should_backtrack(0.5) is False
    assert planner.should_backtrack(None) is True


def test_back_up_increments_visits_along_path():
    g = _graph()
    e = ProceduralEdge("root", "enum", EdgeType.ENABLES, Q=0.5, P=0.5, visits=0)
    g.add_edge(e)
    back_up(g, [("root", "enum", EdgeType.ENABLES.value)])
    assert g.get_edge("root", "enum", EdgeType.ENABLES).visits == 1

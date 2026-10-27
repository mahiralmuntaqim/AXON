"""Graph schema — the foundation every other module reads from (SEGMENT 2).

Two kinds of graph, kept deliberately separate by the type system:

* Procedural graph G_K : persistent "what is possible". Nodes are *techniques*
  (:class:`TechniqueNode`), edges carry a learned value ``Q`` and an LLM prior ``P``.
* Episodic graph G_E : per-target *verified facts* (:class:`EpisodicFact`). Created fresh per
  engagement, destroyed after. Target secrets must never land in G_K.

This module only defines records + validation. The containers live in ``procedural.py`` and
``episodic.py``; serialization in ``persistence.py``. The split into different classes is the
mechanism that makes it hard to accidentally write an episodic fact into the procedural graph
(rule 3). Validation here enforces the closed node/edge type sets and the [0,1] range on Q/P.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Optional, Protocol, Sequence, runtime_checkable


# --------------------------------------------------------------------------------------------
# Closed type vocabularies. Anything outside these sets is rejected (rule in SEGMENT 2).
# --------------------------------------------------------------------------------------------
class NodeType(str, Enum):
    """The six technique types, in the tactic order they usually run (MITRE ATT&CK)."""

    RECON = "RECON"
    ENUM = "ENUM"
    EXPLOIT = "EXPLOIT"
    PRIVESC = "PRIVESC"
    LATERAL = "LATERAL"
    EXFIL = "EXFIL"


# Canonical ordering used by construction (precondition/enables transitions follow this).
NODE_TYPE_ORDER: tuple[NodeType, ...] = (
    NodeType.RECON,
    NodeType.ENUM,
    NodeType.EXPLOIT,
    NodeType.PRIVESC,
    NodeType.LATERAL,
    NodeType.EXFIL,
)


class EdgeType(str, Enum):
    """The four edge types connecting techniques."""

    PRECONDITION = "PRECONDITION"  # tail must hold before head is attemptable
    ENABLES = "ENABLES"            # tail success opens head
    ALTERNATIVE = "ALTERNATIVE"    # head is another way to achieve the same goal
    REFINES = "REFINES"            # head is a more specific variant of tail


class EpisodicFactKind(str, Enum):
    """Kinds of verified fact about the current target (G_E node labels)."""

    HOST = "HOST"
    SERVICE = "SERVICE"       # an open service, with a version
    CREDENTIAL = "CREDENTIAL"
    FOOTHOLD = "FOOTHOLD"


class Reversibility(str, Enum):
    """Whether executing a technique can be undone on a live target (SEGMENT 7)."""

    REVERSIBLE = "REVERSIBLE"
    IRREVERSIBLE = "IRREVERSIBLE"


# --------------------------------------------------------------------------------------------
# Context signatures and lessons.
# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ContextSignature:
    """Structured description of *when* a lesson applies.

    Deliberately structured (not a free string) so :mod:`axon.graph.matching` can compare
    signatures consistently. ``service`` and ``version`` describe the observed service;
    ``defense`` is any defense observed (e.g. "WAF", "modsecurity"), or ``None``.
    """

    service: Optional[str] = None
    version: Optional[str] = None
    defense: Optional[str] = None

    def normalized(self) -> "ContextSignature":
        """Lower-case and strip the string fields for stable comparison."""

        def norm(s: Optional[str]) -> Optional[str]:
            return s.strip().lower() if isinstance(s, str) and s.strip() else None

        return ContextSignature(norm(self.service), norm(self.version), norm(self.defense))

    def major_version(self) -> Optional[str]:
        """The leading numeric component of ``version`` (e.g. '2.4.49' -> '2'), or None."""
        if not self.version:
            return None
        head = self.version.strip().split(".")[0]
        return head or None


@dataclass(frozen=True)
class Lesson:
    """A reusable lesson keyed by the context it applies to (SEGMENT 5).

    One lesson is the pair (``context`` signature, ``text``). ``success`` records whether it
    was distilled from a win or a loss — lessons are distilled from failures too.
    """

    context: ContextSignature
    text: str
    success: bool


# --------------------------------------------------------------------------------------------
# Experience record (lives on every technique node).
# --------------------------------------------------------------------------------------------
def _validate_count(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative int, got {value!r}")
    return value


@dataclass
class ExperienceRecord:
    """Accumulated experience for a technique node. All learning lands here or on edges."""

    n_plus: int = 0           # verified successes
    n_minus: int = 0          # verified failures
    lessons: list[Lesson] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_count("n_plus", self.n_plus)
        _validate_count("n_minus", self.n_minus)

    def record_success(self) -> None:
        self.n_plus += 1

    def record_failure(self) -> None:
        self.n_minus += 1

    def add_lesson(self, lesson: Lesson) -> None:
        if not isinstance(lesson, Lesson):
            raise TypeError(f"expected Lesson, got {type(lesson).__name__}")
        self.lessons.append(lesson)


# --------------------------------------------------------------------------------------------
# Procedural graph records: TechniqueNode and ProceduralEdge.
# --------------------------------------------------------------------------------------------
def _validate_unit_interval(name: str, value: float, *, clamp: bool) -> float:
    """Ensure ``value`` is in [0, 1]. Clamp if allowed, otherwise reject (SEGMENT 2)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number, got {value!r}")
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite, got {value!r}")
    if 0.0 <= v <= 1.0:
        return v
    if clamp:
        return min(1.0, max(0.0, v))
    raise ValueError(f"{name} must be in [0, 1], got {v}")


@dataclass
class TechniqueNode:
    """A node in the procedural graph G_K: a single pentest technique.

    ``embedding`` may be ``None`` only transiently during construction; retrieval and
    construction fail loudly if a node reaches the graph without one (SEGMENT 3).
    """

    id: str
    node_type: NodeType
    spec: str                                   # text specification of the technique
    embedding: Optional[Sequence[float]] = None
    experience: ExperienceRecord = field(default_factory=ExperienceRecord)
    reversibility: Reversibility = Reversibility.IRREVERSIBLE  # fail-safe default (SEGMENT 7)
    # General (non-target-specific) technique metadata: tool name, install, usage, docs,
    # source category. Safe for G_K — it is "what is possible", not target secrets (rule 3).
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("TechniqueNode.id must be a non-empty string")
        if not isinstance(self.node_type, NodeType):
            # Reject any type outside the closed set of six.
            raise ValueError(
                f"node_type must be a NodeType (one of {[t.value for t in NodeType]}), "
                f"got {self.node_type!r}"
            )
        if not isinstance(self.spec, str) or not self.spec.strip():
            raise ValueError("TechniqueNode.spec must be a non-empty string")
        if not isinstance(self.reversibility, Reversibility):
            raise ValueError("reversibility must be a Reversibility enum")


@dataclass
class ProceduralEdge:
    """A directed edge in G_K, carrying a learned value ``Q`` and an LLM prior ``P``.

    ``n_plus``/``n_minus`` are the Beta trial counts behind ``Q`` (SEGMENT 5). ``visits`` is the
    bandit visit count ``N(a)`` used by the PUCT rule (SEGMENT 6).
    """

    src: str
    dst: str
    edge_type: EdgeType
    Q: float = 0.5
    P: float = 0.5
    n_plus: int = 0
    n_minus: int = 0
    visits: int = 0
    _clamp: bool = True  # whether out-of-range Q/P is clamped (True) or rejected (False)

    def __post_init__(self) -> None:
        if not isinstance(self.edge_type, EdgeType):
            raise ValueError(
                f"edge_type must be an EdgeType (one of {[e.value for e in EdgeType]}), "
                f"got {self.edge_type!r}"
            )
        if not self.src or not self.dst:
            raise ValueError("edge endpoints src/dst must be non-empty node ids")
        _validate_count("n_plus", self.n_plus)
        _validate_count("n_minus", self.n_minus)
        _validate_count("visits", self.visits)
        self.Q = _validate_unit_interval("Q", self.Q, clamp=self._clamp)
        self.P = _validate_unit_interval("P", self.P, clamp=self._clamp)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.src, self.dst, self.edge_type.value)

    def set_Q(self, value: float) -> None:
        self.Q = _validate_unit_interval("Q", value, clamp=self._clamp)

    def set_P(self, value: float) -> None:
        self.P = _validate_unit_interval("P", value, clamp=self._clamp)


# --------------------------------------------------------------------------------------------
# Episodic graph record: a verified fact about the current target.
# --------------------------------------------------------------------------------------------
@dataclass
class EpisodicFact:
    """A node in the episodic graph G_E: a verified fact about the *current* target.

    This is a distinct class from :class:`TechniqueNode`; the containers accept only their own
    class, which is the type-system mechanism keeping target secrets out of G_K (rule 3).
    """

    id: str
    kind: EpisodicFactKind
    attributes: dict[str, str] = field(default_factory=dict)
    # Signature derived from this fact, used to match lessons/preconditions.
    service: Optional[str] = None
    version: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("EpisodicFact.id must be a non-empty string")
        if not isinstance(self.kind, EpisodicFactKind):
            raise ValueError(
                f"kind must be an EpisodicFactKind (one of "
                f"{[k.value for k in EpisodicFactKind]}), got {self.kind!r}"
            )

    def context_signature(self, defense: Optional[str] = None) -> ContextSignature:
        return ContextSignature(self.service, self.version, defense).normalized()


# --------------------------------------------------------------------------------------------
# Graph backend protocol — the clean hook for a user-supplied graph (see "How to use", below).
# --------------------------------------------------------------------------------------------
@runtime_checkable
class GraphBackend(Protocol):
    """Minimal storage contract a procedural-graph backend must satisfy.

    ``procedural.ProceduralGraph`` ships a NetworkX-backed default, but graph construction and
    the memory layer depend only on this protocol, so a different graph library can be dropped
    in without a rewrite (per the "How to use these segments" note).
    """

    def add_node(self, node: TechniqueNode) -> None: ...
    def add_edge(self, edge: ProceduralEdge) -> None: ...
    def get_node(self, node_id: str) -> Optional[TechniqueNode]: ...
    def out_edges(self, node_id: str) -> list[ProceduralEdge]: ...
    def nodes(self) -> list[TechniqueNode]: ...
    def edges(self) -> list[ProceduralEdge]: ...


def copy_experience(record: ExperienceRecord) -> ExperienceRecord:
    """Deep-ish copy of an experience record (lessons are frozen, so shallow-copy the list)."""
    return ExperienceRecord(record.n_plus, record.n_minus, list(record.lessons))


def with_updated_counts(edge: ProceduralEdge, *, n_plus: int, n_minus: int) -> ProceduralEdge:
    """Return a copy of ``edge`` with new trial counts (used in tests/snapshots)."""
    return replace(edge, n_plus=n_plus, n_minus=n_minus)

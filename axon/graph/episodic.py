"""Episodic graph G_E — per-target verified facts (SEGMENT 2).

Created fresh at the start of every engagement and destroyed at the end. Holds only
:class:`EpisodicFact` nodes and simple typed relations between them. It is NEVER included in a
procedural snapshot — :mod:`axon.graph.persistence` provides separate serializers so the two
can never be saved together.
"""

from __future__ import annotations

from typing import Optional

from .schema import EpisodicFact, EpisodicFactKind


class EpisodicGraph:
    """Container for G_E: the current target's map as it fills in."""

    def __init__(self, engagement_id: str) -> None:
        self.engagement_id = engagement_id
        self._facts: dict[str, EpisodicFact] = {}
        # relations: list of (src_id, dst_id, relation_label), e.g. host --runs--> service
        self._relations: list[tuple[str, str, str]] = []

    def add_fact(self, fact: EpisodicFact) -> None:
        if not isinstance(fact, EpisodicFact):
            raise TypeError(
                f"EpisodicGraph accepts only EpisodicFact, got {type(fact).__name__}"
            )
        self._facts[fact.id] = fact

    def relate(self, src_id: str, dst_id: str, label: str) -> None:
        if src_id not in self._facts or dst_id not in self._facts:
            raise ValueError("both facts must exist before relating them")
        rel = (src_id, dst_id, label)
        if rel not in self._relations:
            self._relations.append(rel)

    def get_fact(self, fact_id: str) -> Optional[EpisodicFact]:
        return self._facts.get(fact_id)

    def facts(self) -> list[EpisodicFact]:
        return list(self._facts.values())

    def facts_of_kind(self, kind: EpisodicFactKind) -> list[EpisodicFact]:
        return [f for f in self._facts.values() if f.kind == kind]

    def relations(self) -> list[tuple[str, str, str]]:
        return list(self._relations)

    def services(self) -> list[EpisodicFact]:
        """Open services with versions — the backbone of the retrieval query (SEGMENT 4)."""
        return self.facts_of_kind(EpisodicFactKind.SERVICE)

    def __len__(self) -> int:
        return len(self._facts)

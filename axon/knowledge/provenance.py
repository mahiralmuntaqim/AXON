"""The provenance firewall (SEGMENT 3 / SEGMENT 12).

Public write-ups can leak benchmark solutions. The firewall runs at graph-construction time and
excludes any source tied to an evaluation benchmark, mirroring CRAKEN's exclusion policy (e.g.
CSAW material is excluded because it maps to NYU CTF). Every exclusion is logged so it can be
proven later exactly what was kept out.

IMPORTANT honesty note (stated in results too): the firewall controls what enters the *graph*,
not the frozen model's own pretraining memory of these sources. XBOW's injected flags therefore
remain the cleanest contamination-minimized measure.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Source-tag -> the evaluation benchmark it would leak. Extend as benchmarks are added.
DEFAULT_EXCLUSION_MAP: dict[str, str] = {
    "csaw": "NYU CTF Bench",
    "nyuctf": "NYU CTF Bench",
    "cybench": "Cybench",
    "autopenbench": "AutoPenBench",
    "xbow": "XBOW / XBEN",
    "xben": "XBOW / XBEN",
    "vulhub-writeup": "Vulhub",  # solution write-ups, not the CVE descriptions themselves
}


@dataclass
class Exclusion:
    source_id: str
    origin_tag: str
    benchmark: str


@dataclass
class ProvenanceFirewall:
    """Decides whether a source may be ingested, and logs every exclusion."""

    exclusion_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_EXCLUSION_MAP))
    log: list[Exclusion] = field(default_factory=list)

    def benchmark_for(self, origin_tag: str) -> str | None:
        return self.exclusion_map.get(origin_tag.strip().lower()) if origin_tag else None

    def is_excluded(self, origin_tag: str) -> bool:
        return self.benchmark_for(origin_tag) is not None

    def admit(self, source_id: str, origin_tag: str) -> bool:
        """Return True if the source may be ingested; otherwise log and return False."""
        benchmark = self.benchmark_for(origin_tag)
        if benchmark is not None:
            self.log.append(Exclusion(source_id, origin_tag, benchmark))
            return False
        return True

    def report(self) -> list[dict]:
        return [
            {"source_id": e.source_id, "origin_tag": e.origin_tag, "benchmark": e.benchmark}
            for e in self.log
        ]

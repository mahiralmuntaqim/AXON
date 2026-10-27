"""Knowledge-pack loader — real Segment 3 content for the procedural graph.

The ``knowledge_packs/`` folder holds curated CTF/pentest source content (six categories, each
with ``tools.json`` + ``playbook.md`` + ``resources.md``). This module turns that content into
G_K two ways, both filling the SEGMENT 3 "construction is an interface" hook:

* :func:`build_procedural_graph` — deterministic, offline, no LLM. Maps each tool's *role* onto
  one of the six technique types and wires category subgraphs along the tactic order. Use this
  to get a real, inspectable G_K immediately.
* :func:`to_source_docs` — packages each pack as a :class:`~axon.knowledge.construct.SourceDoc`
  so the LLM-based :class:`~axon.knowledge.construct.GraphConstructor` can extract from the same
  content when a real model is wired in.

Note on type mapping: AXON's six node types are pentest *tactics* (RECON..EXFIL); the packs are
CTF *categories* (crypto/pwn/rev/web/forensics/misc), which are orthogonal. The loader keeps the
original category and tool details in ``TechniqueNode.metadata`` (safe for G_K — general
knowledge, not target secrets) so retrieval can still filter by category/archetype.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..graph.procedural import ProceduralGraph
from ..graph.schema import (
    NODE_TYPE_ORDER,
    EdgeType,
    NodeType,
    ProceduralEdge,
    Reversibility,
    TechniqueNode,
)
from .embeddings import Embedder
from .provenance import ProvenanceFirewall

# knowledge_packs/packs lives at the repo root, two levels above axon/knowledge/.
DEFAULT_PACKS_DIR = Path(__file__).resolve().parents[2] / "knowledge_packs" / "packs"

# Packs are compiled from HackTricks / PayloadsAllTheThings / Awesome-CTF etc. — not tied to any
# evaluation benchmark, so the firewall admits them. Tagged for the provenance log all the same.
PACK_ORIGIN_TAG = "ctf-knowledge-pack"


@dataclass
class Pack:
    category: str
    archetypes: list[str]
    summary: str
    quick_triage: list[str]
    tools: list[dict]
    playbook_md: str = ""
    resources_md: str = ""


@dataclass
class PackGraphResult:
    graph: ProceduralGraph
    exclusions: list[dict] = field(default_factory=list)
    n_categories: int = 0
    n_tools: int = 0


# --------------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------------
def load_packs(packs_dir: str | Path = DEFAULT_PACKS_DIR) -> list[Pack]:
    """Read every ``<category>/tools.json`` (+ playbook/resources) under ``packs_dir``."""
    base = Path(packs_dir)
    if not base.is_dir():
        raise FileNotFoundError(f"knowledge packs directory not found: {base}")
    packs: list[Pack] = []
    for tools_json in sorted(base.glob("*/tools.json")):
        cat_dir = tools_json.parent
        data = json.loads(tools_json.read_text(encoding="utf-8"))
        packs.append(
            Pack(
                category=data.get("category", cat_dir.name),
                archetypes=list(data.get("archetypes", [])),
                summary=data.get("summary", ""),
                quick_triage=list(data.get("quick_triage", [])),
                tools=list(data.get("tools", [])),
                playbook_md=_read_optional(cat_dir / "playbook.md"),
                resources_md=_read_optional(cat_dir / "resources.md"),
            )
        )
    if not packs:
        raise FileNotFoundError(f"no */tools.json packs found under {base}")
    return packs


def _read_optional(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.is_file() else ""


# --------------------------------------------------------------------------------------------
# Tool role -> technique type (deterministic keyword classifier)
# --------------------------------------------------------------------------------------------
# Scored keyword cues per type. Highest score wins; ties fall back to the per-category default.
_TYPE_CUES: dict[NodeType, tuple[str, ...]] = {
    NodeType.RECON: (
        "identify", "fingerprint", "first look", "first thing", "triage", "detect",
        "read metadata", "which mitigations", "recon", "map the surface", "inspect",
        "read magic", "classify",
    ),
    NodeType.ENUM: (
        "discovery", "enumerate", "fuzz", "brute force", "brute-force", "wordlist",
        "content discovery", "scan", "carve", "extract embedded", "find + extract", "list",
        "dir", "vhost", "parameter",
    ),
    NodeType.EXPLOIT: (
        "exploit", "attack", "inject", "injection", "break", "crack", "forge", "overflow",
        "rop", "shellcode", "bypass", "escape", "hijack", "format-string", "deserial",
        "poison", "abuse", "solve", "decrypt", "factor",
    ),
    NodeType.PRIVESC: ("escalate", "privilege", "sudo", "gtfobins", "lolbas", "suid", "root"),
    NodeType.LATERAL: ("pivot", "lateral", "internal service", "ssrf to internal", "tunnel"),
    NodeType.EXFIL: (
        "recover the flag", "read the flag", "dump", "exfiltrate", "leak the", "recover a secret",
        "recover the secret", "decode the flag", "read a file", "file-read", "read files",
    ),
}


def classify_node_type(name: str, when: str, category_default: NodeType) -> NodeType:
    """Pick a technique type from the tool's name/role, defaulting per category on a tie."""
    text = f"{name} {when}".lower()
    scores: dict[NodeType, int] = {}
    for ntype, cues in _TYPE_CUES.items():
        scores[ntype] = sum(1 for cue in cues if cue in text)
    best = max(scores, key=lambda t: scores[t])
    return best if scores[best] > 0 else category_default


# Each CTF category's "center of gravity" type, used when a tool's role is ambiguous.
_CATEGORY_DEFAULT: dict[str, NodeType] = {
    "web": NodeType.EXPLOIT,
    "crypto": NodeType.EXPLOIT,
    "pwn": NodeType.EXPLOIT,
    "rev": NodeType.ENUM,       # reversing is mostly analysis/enumeration of logic
    "forensics": NodeType.ENUM,
    "misc": NodeType.EXPLOIT,
}


def _reversibility_for(ntype: NodeType) -> Reversibility:
    # Info-gathering is reversible; anything that changes/takes state is fail-safe irreversible.
    return (
        Reversibility.REVERSIBLE
        if ntype in (NodeType.RECON, NodeType.ENUM)
        else Reversibility.IRREVERSIBLE
    )


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "x"


# --------------------------------------------------------------------------------------------
# Deterministic graph construction
# --------------------------------------------------------------------------------------------
def build_procedural_graph(
    packs_dir: str | Path = DEFAULT_PACKS_DIR,
    *,
    embedder: Embedder,
    firewall: Optional[ProvenanceFirewall] = None,
) -> PackGraphResult:
    """Build a real G_K from the knowledge packs, offline (no LLM)."""
    firewall = firewall or ProvenanceFirewall()
    packs = load_packs(packs_dir)
    graph = ProceduralGraph()
    n_tools = 0
    n_categories = 0

    for pack in packs:
        if not firewall.admit(f"pack:{pack.category}", PACK_ORIGIN_TAG):
            continue  # (never excluded for these sources, but keep the firewall in the path)
        n_categories += 1
        cat = pack.category
        cat_default = _CATEGORY_DEFAULT.get(cat, NodeType.EXPLOIT)

        # A RECON "triage" node per category, from quick_triage first-moves.
        triage_id = f"{cat}::triage"
        triage_spec = f"{cat} triage / identify: " + " ".join(pack.quick_triage[:2]) if pack.quick_triage else f"{cat} initial recon"
        graph.add_node(
            TechniqueNode(
                id=triage_id, node_type=NodeType.RECON, spec=triage_spec[:600],
                embedding=embedder.embed(f"{cat} {pack.summary}"),
                reversibility=Reversibility.REVERSIBLE,
                metadata={"category": cat, "kind": "triage",
                          "archetypes": ",".join(pack.archetypes)},
            )
        )

        # One node per tool, typed by role.
        by_type: dict[NodeType, list[str]] = {t: [] for t in NodeType}
        by_type[NodeType.RECON].append(triage_id)
        for tool in pack.tools:
            name = str(tool.get("name", "tool"))
            when = str(tool.get("when", ""))
            ntype = classify_node_type(name, when, cat_default)
            nid = f"{cat}::{_slug(name)}"
            if graph.has_node(nid):
                continue  # dedupe within a category
            graph.add_node(
                TechniqueNode(
                    id=nid, node_type=ntype, spec=f"{name}: {when}"[:600],
                    embedding=embedder.embed(f"{cat} {name} {when}"),
                    reversibility=_reversibility_for(ntype),
                    metadata={
                        "category": cat, "tool": name,
                        "install": json.dumps(tool.get("install", {})),
                        "usage": str(tool.get("usage", ""))[:300],
                        "docs": str(tool.get("docs", "")),
                        "archetypes": ",".join(pack.archetypes),
                    },
                )
            )
            by_type[ntype].append(nid)
            n_tools += 1

        _wire_category(graph, by_type)

    return PackGraphResult(
        graph=graph, exclusions=firewall.report(),
        n_categories=n_categories, n_tools=n_tools,
    )


def _wire_category(graph: ProceduralGraph, by_type: dict[NodeType, list[str]]) -> None:
    """ENABLES along adjacent *present* tactic types; ALTERNATIVE within a type."""
    present = [t for t in NODE_TYPE_ORDER if by_type.get(t)]
    # ENABLES: each node of an earlier present tactic enables each node of the next present one.
    for i in range(len(present) - 1):
        cur, nxt = present[i], present[i + 1]
        p = 0.7 if cur is NodeType.RECON else 0.6
        for src in by_type[cur]:
            for dst in by_type[nxt]:
                if graph.get_edge(src, dst, EdgeType.ENABLES) is None:
                    graph.add_edge(ProceduralEdge(src, dst, EdgeType.ENABLES, P=p))
    # ALTERNATIVE: tools of the same type are alternative ways to do the same step.
    for group in by_type.values():
        for a in group:
            for b in group:
                if a != b and graph.get_edge(a, b, EdgeType.ALTERNATIVE) is None:
                    graph.add_edge(ProceduralEdge(a, b, EdgeType.ALTERNATIVE, P=0.5))


# --------------------------------------------------------------------------------------------
# SourceDoc adapter (for the LLM GraphConstructor path)
# --------------------------------------------------------------------------------------------
def to_source_docs(packs_dir: str | Path = DEFAULT_PACKS_DIR):
    """Package each pack as a SourceDoc for the LLM-based GraphConstructor (SEGMENT 3)."""
    from .construct import SourceDoc

    docs = []
    for pack in load_packs(packs_dir):
        tool_lines = "\n".join(
            f"- {t.get('name')}: {t.get('when')} (usage: {t.get('usage','')})"
            for t in pack.tools
        )
        text = (
            f"# {pack.category} (archetypes: {', '.join(pack.archetypes)})\n\n"
            f"{pack.summary}\n\n## Quick triage\n" + "\n".join(pack.quick_triage) +
            f"\n\n## Tools\n{tool_lines}\n\n## Playbook\n{pack.playbook_md}"
        )
        docs.append(SourceDoc(source_id=f"pack-{pack.category}", text=text,
                              origin_tag=PACK_ORIGIN_TAG))
    return docs

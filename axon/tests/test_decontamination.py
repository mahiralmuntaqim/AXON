"""Decontamination & provenance tests (SEGMENT 12, SEGMENT 16)."""

from axon.config import load_config
from axon.execution.sandbox import Sandbox
from axon.knowledge.construct import GraphConstructor, SourceDoc
from axon.knowledge.embeddings import HashingEmbedder
from axon.knowledge.provenance import ProvenanceFirewall
from axon.llm.client import LLMClient, LLMConfig, MockLLM


def test_web_search_is_off_during_eval_by_default():
    cfg = load_config()
    sandbox = Sandbox.from_config(cfg)
    assert sandbox.web_search_allowed() is False


def test_firewall_excludes_seeded_csaw_document_and_logs_it():
    fw = ProvenanceFirewall()
    assert fw.admit("doc-hacktricks", "hacktricks") is True
    assert fw.admit("doc-csaw-2021", "csaw") is False  # CSAW maps to NYU CTF
    report = fw.report()
    assert len(report) == 1
    assert report[0]["source_id"] == "doc-csaw-2021"
    assert report[0]["benchmark"] == "NYU CTF Bench"


def test_construction_excludes_eval_tied_sources_end_to_end():
    extraction = (
        '[{"spec": "nmap service scan", "type": "RECON", "reversibility": "REVERSIBLE"}]'
    )
    backend = MockLLM(routes=[(lambda p: "extract pentest techniques" in p, lambda p: extraction)])
    llm = LLMClient(backend, LLMConfig(model="mock"))
    gc = GraphConstructor(llm, HashingEmbedder(dim=32))

    result = gc.build(
        [
            SourceDoc("hack-1", "apache stuff", origin_tag="hacktricks"),
            SourceDoc("csaw-1", "ctf writeup", origin_tag="csaw"),  # must be excluded
        ]
    )
    # Only the hacktricks source contributed; csaw is in the exclusion log.
    assert any(e["origin_tag"] == "csaw" for e in result.exclusions)
    assert len(result.graph) >= 1


def test_sandbox_blocks_disallowed_host_and_tool():
    cfg = load_config()
    sandbox = Sandbox.from_config(cfg)
    # Disallowed public host.
    assert sandbox.host_allowed("8.8.8.8") is False
    # Allowed private/loopback host.
    assert sandbox.host_allowed("127.0.0.1") is True
    assert sandbox.host_allowed("192.168.1.10") is True
    # Tool allowlist.
    assert sandbox.tool_allowed("nmap") is True
    assert sandbox.tool_allowed("rm") is False

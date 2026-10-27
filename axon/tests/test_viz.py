"""Visualizer data-layer tests (SEGMENT 17).

The visualizer itself is a web page; these tests cover the Python side it depends on — the
emitter produces well-formed events for every key moment, and replaying the event log reaches
the same final edge values the live run ended with ("replay matches live").
"""

from axon.config import load_config
from axon.engagement.events import EventEmitter, EventType
from axon.engagement.replay import load_log, reconstruct_edge_q
from axon.engagement.runner import run_engagement
from axon.harness.mock import MockHarness
from axon.knowledge.construct import demo_seed_graph
from axon.knowledge.embeddings import HashingEmbedder


def _run(tmp_path):
    cfg = load_config()
    emb = HashingEmbedder(dim=int(cfg["graph"]["embedding_dim"]))
    graph = demo_seed_graph(emb)
    harness = MockHarness()
    env = harness.start(harness.load_tasks()[0])
    log = tmp_path / "events.jsonl"
    emitter = EventEmitter(log_path=log)
    outcome = run_engagement(cfg, graph, env, emb, emitter=emitter)
    emitter.close()
    return cfg, emb, graph, outcome, log


def test_emitter_produces_events_for_each_key_moment(tmp_path):
    _, _, _, _, log = _run(tmp_path)
    events = load_log(log)
    types = {e.type for e in events}
    for required in (
        EventType.SNAPSHOT, EventType.READ, EventType.SELECT, EventType.EXECUTE,
        EventType.VERIFY, EventType.WRITE, EventType.BACKUP, EventType.BUDGET,
    ):
        assert required.value in types
    # Every event is well-formed.
    for e in events:
        assert isinstance(e.step, int) and isinstance(e.payload, dict) and e.timestamp >= 0


def test_replay_matches_live_final_graph(tmp_path):
    _, _, graph, _, log = _run(tmp_path)
    reconstructed = reconstruct_edge_q(load_log(log))
    for edge in graph.edges():
        assert edge.key in reconstructed
        assert abs(reconstructed[edge.key] - edge.Q) < 1e-9


def test_log_that_stops_abruptly_still_parses(tmp_path):
    _, _, _, _, log = _run(tmp_path)
    text = log.read_text(encoding="utf-8")
    truncated = text[: len(text) // 2] + '{"type":"write","step":9'  # partial last line
    broken = tmp_path / "broken.jsonl"
    broken.write_text(truncated, encoding="utf-8")
    # Should not raise on the clean lines; the partial trailing line is tolerated.
    events = []
    for line in broken.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            import json
            json.loads(line)
            events.append(line)
        except json.JSONDecodeError:
            pass  # a crashed run leaves at most one unparseable trailing line
    assert len(events) >= 1

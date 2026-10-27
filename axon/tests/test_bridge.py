"""Execution-bridge unit tests (offline — no Docker, no network)."""

import hashlib

from axon.benchmark.bridge import web_service_name, xbow_expected_flag
from axon.execution.tools import Action, SubprocessBackend


def test_xbow_flag_formula():
    # FLAG{sha256(uppercase(id))}
    expected = "FLAG{" + hashlib.sha256(b"XBEN-001-24").hexdigest() + "}"
    assert xbow_expected_flag("XBEN-001-24") == expected
    assert xbow_expected_flag("xben-001-24") == expected  # upper-cased first


def test_subprocess_backend_detects_flag_in_output():
    flag = "FLAG{unit_test_flag}"
    be = SubprocessBackend(flag=flag, bash=False)
    res = be.observe(Action(technique_id="t", tool="echo", host="127.0.0.1",
                            command=f"echo {flag}"))
    assert res.claimed_success is True
    assert res.milestone == flag
    assert any(t.kind.value == "MILESTONE_FLAG" for t in res.state_transitions)


def test_subprocess_backend_no_flag_is_not_success():
    be = SubprocessBackend(flag="FLAG{nope}", bash=False)
    res = be.observe(Action(technique_id="t", tool="echo", host="127.0.0.1",
                            command="echo nothing here"))
    assert res.claimed_success is False and res.milestone is None


def test_web_service_name_picks_the_published_service(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n"
        "  db:\n    expose:\n      - '3306'\n"
        "  webapp:\n    ports:\n      - 80\n",
        encoding="utf-8",
    )
    assert web_service_name(tmp_path) == "webapp"

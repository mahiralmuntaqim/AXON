"""Deterministic offline harness (SEGMENT 11, for testing).

Encodes a tiny engagement as an outcome oracle so the whole loop runs end-to-end with no real
target and no network. Technique nodes map to concrete allowlisted commands against a localhost
sandbox; the oracle decides each outcome deterministically from the technique id, including a
genuine failure and a tool error so the verification gate is exercised.
"""

from __future__ import annotations

from ..engagement.state import EngagementState
from ..execution.result import ActionResult, StateTransition, TransitionKind
from ..execution.tools import Action
from ..graph.schema import EpisodicFact, EpisodicFactKind, TechniqueNode
from ..graph.episodic import EpisodicGraph
from .base import BenchmarkHarness, Task, TaskEnvironment

# Technique id -> (tool, command) using only allowlisted tools against localhost.
_COMMANDS = {
    "recon": ("nmap", "nmap -sV 127.0.0.1"),
    "enum_http": ("gobuster", "gobuster dir -u http://127.0.0.1 -w words.txt"),
    "exploit_cve": ("curl", "curl http://127.0.0.1/cve"),
    "exploit_bad": ("curl", "curl http://127.0.0.1/doomed"),
    "typo": ("nmap", "nmpa -sV 127.0.0.1"),  # deliberate typo -> tool error
}


class MockHarness(BenchmarkHarness):
    name = "mock"

    def load_tasks(self) -> list[Task]:
        return [Task(task_id="mock-001", goal="flag", category="web", root_node_id="recon")]

    def start(self, task: Task) -> TaskEnvironment:
        episodic = EpisodicGraph(task.task_id)

        def oracle(action: Action) -> ActionResult:
            tid = action.technique_id
            if tid == "recon":
                return ActionResult(
                    tid, action.command, exit_code=0, stdout="80/tcp open http apache 2.4.49",
                    claimed_success=True, cost=0.01,
                    state_transitions=[StateTransition(TransitionKind.SERVICE_DISCOVERED, "http")],
                    new_facts=[EpisodicFact("svc-http", EpisodicFactKind.SERVICE,
                                            service="apache", version="2.4.49",
                                            attributes={"port": "80"})],
                )
            if tid == "enum_http":
                return ActionResult(
                    tid, action.command, exit_code=0, stdout="/admin (200)",
                    claimed_success=True, cost=0.02,
                    state_transitions=[StateTransition(TransitionKind.HTTP_UNBLOCKED, "/admin")],
                    new_facts=[EpisodicFact("foot-admin", EpisodicFactKind.FOOTHOLD,
                                            attributes={"desc": "admin panel"})],
                )
            if tid == "exploit_bad":
                # Genuine hypothesis failure: ran fine, no success.
                return ActionResult(tid, action.command, exit_code=0, stdout="403 Forbidden",
                                    claimed_success=False, cost=0.05)
            if tid == "typo":
                return ActionResult(tid, action.command, exit_code=127,
                                    stderr="bash: nmpa: command not found", cost=0.0)
            # exploit_cve -> the solve: a real milestone flag.
            return ActionResult(
                tid, action.command, exit_code=0, stdout="flag{mock}",
                claimed_success=True, milestone="flag", cost=0.1,
                state_transitions=[StateTransition(TransitionKind.MILESTONE_FLAG, "flag{mock}")],
            )

        def action_factory(node: TechniqueNode, state: EngagementState) -> Action:
            tool, command = _COMMANDS.get(node.id, ("curl", f"curl http://127.0.0.1/{node.id}"))
            return Action(
                technique_id=node.id, tool=tool, host="127.0.0.1", command=command,
                cost={"recon": 0.01, "enum_http": 0.02, "exploit_cve": 0.1}.get(node.id, 0.05),
                reversible=node.reversibility.value == "REVERSIBLE",
            )

        from ..execution.tools import MockTarget

        return TaskEnvironment(
            task=task,
            target=MockTarget(oracle),
            action_factory=action_factory,
            goal_check=lambda result, state: result.milestone == "flag",
            episodic=episodic,
            supports_dry_run=True,
            milestones=["service", "foothold", "flag"],
        )

    def teardown(self, env: TaskEnvironment) -> None:
        # Episodic graph is simply dropped; nothing persisted (rule 3).
        return None

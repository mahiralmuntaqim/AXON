"""Execution bridge — run the AXON engagement loop against a live benchmark challenge.

This is the "hands" that `start()` needs: it brings up a challenge's Docker environment, wires a
real :class:`~axon.execution.tools.SubprocessBackend`, synthesizes concrete tool commands with
the (frozen) LLM, and checks the recovered flag. First target: XBOW/XBEN (web, docker-compose,
deterministic injected flag).

Authorization: only runs against the local sandboxed challenge containers (loopback), using the
allowlisted tools. It composes documented tools — it does not generate exploit code.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

import yaml

from ..execution.docker_exec import DockerExecBackend, DockerToolbox
from ..execution.sandbox import Sandbox
from ..execution.tools import Action, SubprocessBackend
from ..graph.episodic import EpisodicGraph
from ..graph.schema import EpisodicFact, EpisodicFactKind, TechniqueNode
from ..harness.base import Task, TaskEnvironment
from ..llm.client import LLMClient, LLMError
from ..llm.prompts import action_synthesis
from ..memory.read import state_summary


# --------------------------------------------------------------------------------------------
# XBOW flag + docker helpers
# --------------------------------------------------------------------------------------------
def xbow_expected_flag(challenge_id: str) -> str:
    """XBEN flag = FLAG{sha256(uppercase(challenge-id))} (see xbow/common.mk)."""
    digest = hashlib.sha256(challenge_id.upper().encode()).hexdigest()
    return f"FLAG{{{digest}}}"


def _compose(project: str, challenge_dir: Path, *args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "--project-directory", str(challenge_dir), "-p", project, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def web_service_name(challenge_dir: Path) -> Optional[str]:
    """The compose service that publishes a port (the web app), not the db."""
    compose = challenge_dir / "docker-compose.yml"
    if not compose.is_file():
        return None
    data = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
    services = data.get("services", {})
    for name, spec in services.items():
        if isinstance(spec, dict) and spec.get("ports"):
            return name
    # fallback: first non-db service
    for name in services:
        if name.lower() != "db":
            return name
    return None


def compose_up(project: str, challenge_dir: Path, flag: str, *, build: bool = True) -> None:
    if build:
        r = _compose(project, challenge_dir, "build",
                     "--build-arg", f"FLAG={flag}", "--build-arg", f"flag={flag}")
        if r.returncode != 0:
            raise RuntimeError(f"docker compose build failed: {r.stderr[-500:]}")
    r = _compose(project, challenge_dir, "up", "-d", "--wait")
    if r.returncode != 0:
        raise RuntimeError(f"docker compose up failed: {r.stderr[-500:]}")


def compose_down(project: str, challenge_dir: Path) -> None:
    _compose(project, challenge_dir, "down", "-v", timeout=180)


def web_port(project: str, challenge_dir: Path, service: str) -> Optional[int]:
    r = _compose(project, challenge_dir, "port", service, "80")
    m = re.search(r":(\d+)\s*$", (r.stdout or "").strip())
    return int(m.group(1)) if m else None


def web_internal_port(challenge_dir: Path, service: str) -> int:
    """The container-side port the web service listens on (for reaching it over the network)."""
    compose = challenge_dir / "docker-compose.yml"
    data = yaml.safe_load(compose.read_text(encoding="utf-8")) or {}
    spec = (data.get("services", {}) or {}).get(service, {}) or {}
    for p in spec.get("ports", []) or []:
        # entries look like "80", "8080:80", "0:80", "127.0.0.1:8080:80" → container port last.
        target = str(p).split(":")[-1].split("/")[0].strip()
        if target.isdigit():
            return int(target)
    return 80


def web_container_id(project: str, challenge_dir: Path, service: str) -> Optional[str]:
    r = _compose(project, challenge_dir, "ps", "-q", service, timeout=60)
    cid = (r.stdout or "").strip().splitlines()
    return cid[0] if cid else None


def container_networks(container_id: str) -> list[str]:
    """Names of every Docker network a container is attached to."""
    r = subprocess.run(
        ["docker", "inspect", "-f",
         "{{range $k, $v := .NetworkSettings.Networks}}{{$k}}\n{{end}}", container_id],
        capture_output=True, text=True, timeout=60,
    )
    return [n.strip() for n in (r.stdout or "").splitlines() if n.strip()]


# --------------------------------------------------------------------------------------------
# LLM-driven action synthesis (compose a documented tool command for a chosen technique)
# --------------------------------------------------------------------------------------------
class LlmActionFactory:
    """Turn a chosen technique node into a concrete :class:`Action` against the target.

    Uses the frozen LLM to compose one documented-tool command; falls back to the technique's
    stored usage hint (with the target substituted) when no LLM is available or it fails.
    """

    def __init__(self, llm: Optional[LLMClient], sandbox: Sandbox, target_url: str, host: str) -> None:
        self.llm = llm
        self.sandbox = sandbox
        self.target_url = target_url
        self.host = host

    def __call__(self, node: TechniqueNode, state) -> Action:
        tool = node.metadata.get("tool", "curl")
        usage = node.metadata.get("usage", "")
        findings = state_summary(state.episodic)
        command: Optional[str] = None

        if self.llm is not None:
            try:
                parsed = self.llm.complete_json(
                    action_synthesis(node.spec, tool, self.target_url, usage, findings),
                    validate=lambda d: isinstance(d, dict) and isinstance(d.get("command"), str),
                )
                command = parsed["command"].strip()
            except LLMError:
                command = None

        if not command:
            command = self._fallback_command(usage)

        # Derive the invoked tool from the command's first token (what the sandbox checks).
        invoked = self.sandbox.command_tool(command) or tool
        return Action(
            technique_id=node.id,
            tool=invoked,
            host=self.host,
            command=command,
            cost=0.05,
            reversible=node.reversibility.value == "REVERSIBLE",
        )

    def _fallback_command(self, usage: str) -> str:
        if usage:
            cmd = usage.replace("http://T", self.target_url).replace("https://T", self.target_url)
            cmd = re.sub(r"\bT\b", self.host, cmd)
            if cmd.split() and self.sandbox.command_tool(cmd):
                return cmd
        return f"curl -s -i {self.target_url}/"


# --------------------------------------------------------------------------------------------
# Build a live TaskEnvironment for an XBOW challenge
# --------------------------------------------------------------------------------------------
def make_xbow_env(
    task: Task,
    *,
    data_root: Path,
    cfg: dict,
    llm: Optional[LLMClient],
) -> tuple[TaskEnvironment, Callable[[], None]]:
    """Bring up the challenge and build its TaskEnvironment. Returns (env, teardown)."""
    challenge_dir = data_root / "benchmarks" / task.task_id
    if not challenge_dir.is_dir():
        raise FileNotFoundError(f"challenge dir not found: {challenge_dir}")

    project = task.task_id.lower()
    flag = xbow_expected_flag(task.task_id)
    service = web_service_name(challenge_dir)
    if service is None:
        raise RuntimeError(f"could not find a web service in {challenge_dir}/docker-compose.yml")

    compose_up(project, challenge_dir, flag)
    sandbox = Sandbox.from_config(cfg)
    timeout_s = float(cfg.get("engagement", {}).get("per_action_timeout_s", 120))
    tb_cfg = (cfg.get("execution", {}) or {}).get("toolbox", {}) or {}

    toolbox: Optional[DockerToolbox] = None
    if tb_cfg.get("enabled"):
        # Option A: run tools inside a toolbox container on the challenge's network. The target
        # is reached by its compose service name on its internal port — no host tools needed.
        cid = web_container_id(project, challenge_dir, service)
        if cid is None:
            compose_down(project, challenge_dir)
            raise RuntimeError(f"could not find the running container for service {service!r}")
        networks = container_networks(cid)
        internal_port = web_internal_port(challenge_dir, service)
        host = service
        target_url = f"http://{service}:{internal_port}"
        # Permit the service name as a target host on BOTH sandboxes: this factory's, and the
        # one run_engagement builds from cfg (so add it to cfg's allowlist too).
        sandbox.allow_host(service)
        ec = cfg.setdefault("execution", {})
        hosts = list(ec.get("allowed_target_hosts", []))
        if service not in hosts:
            ec["allowed_target_hosts"] = hosts + [service]
        toolbox = DockerToolbox(
            tb_cfg.get("image", "axon-attacker-toolbox:latest"),
            name=f"axon-toolbox-{project}",
            build_context=Path(__file__).resolve().parents[1] / "execution" / "toolbox",
            build=bool(tb_cfg.get("build", True)),
        )
        try:
            toolbox.ensure_image()
            toolbox.start(networks)
        except Exception:
            toolbox.stop()
            compose_down(project, challenge_dir)
            raise
        backend: object = DockerExecBackend(toolbox.name, flag=flag, timeout_s=timeout_s)
        port = internal_port
    else:
        # Fallback: run on the host against the published loopback port (needs host tools).
        port = web_port(project, challenge_dir, service)
        if port is None:
            compose_down(project, challenge_dir)
            raise RuntimeError("could not determine the challenge's mapped web port")
        host = "127.0.0.1"
        target_url = f"http://{host}:{port}"
        backend = SubprocessBackend(flag=flag, timeout_s=timeout_s, bash=(os.name == "nt"))

    episodic = EpisodicGraph(task.task_id)
    episodic.add_fact(
        EpisodicFact(
            id="svc-http", kind=EpisodicFactKind.SERVICE, service="apache", version="",
            attributes={"name": "http web app", "port": str(port), "url": target_url},
        )
    )

    env = TaskEnvironment(
        task=task,
        target=backend,
        action_factory=LlmActionFactory(llm, sandbox, target_url, host),
        goal_check=lambda result, state: result.milestone == flag,
        episodic=episodic,
        supports_dry_run=False,
        milestones=["flag"],
    )

    def teardown() -> None:
        if toolbox is not None:
            toolbox.stop()
        compose_down(project, challenge_dir)

    return env, teardown
